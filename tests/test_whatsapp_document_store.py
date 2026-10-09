"""Private PDF staging tests: SQLite transactions, no storage import or network."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import importlib
import re
import sqlite3
import sys
from threading import RLock

import pytest
from app import whatsapp_document_store as store

NOW=datetime(2026,10,8,12,tzinfo=timezone.utc)
PDF=b'%PDF-1.4\nSynthetic bounded private fixture\n%%EOF'


@pytest.fixture
def db():
    connection=sqlite3.connect(':memory:',check_same_thread=False)
    connection.row_factory=sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    lock=RLock()
    class Connection:
        dialect='sqlite'
        def execute(self,statement,args=()):
            return connection.execute(statement.replace('%s','?'),args)
    @contextmanager
    def factory():
        with lock,connection:yield Connection()
    store.init_storage(db_factory=factory)
    yield factory
    connection.close()


def create(db,**changes):
    args=dict(creator_id=7,account_id='account',conversation_id='conversation',recipient='966500000001',
              filename='sample.pdf',caption='Reviewed caption',content=PDF,db_factory=db,now=NOW)
    args.update(changes)
    return store.create(**args)


def claim(db,row,**changes):
    args=dict(confirmed_sha256=row['sha256'],confirmed_recipient=row['recipient'],
              confirmed_account_id=row['account_id'],db_factory=db,now=NOW)
    args.update(changes)
    return store.claim(row['token'],row['creator_id'],**args)


def raw(db,token):
    with db() as connection:
        value=connection.execute('SELECT * FROM whatsapp_document_drafts WHERE token=%s',(token,)).fetchone()
        return dict(value) if value else None


def test_import_does_not_load_production_storage(monkeypatch):
    monkeypatch.delenv('DATABASE_URL',raising=False)
    before=sys.modules.get('app.storage')
    importlib.reload(store)
    assert sys.modules.get('app.storage') is before


def test_private_draft_preview_and_immutable_claim_committed_before_dispatch(db):
    store.init_storage(db_factory=db)
    row=create(db)
    assert row['state']=='draft' and row['byte_count']==len(PDF)
    assert row['sha256']==hashlib.sha256(PDF).hexdigest()
    assert re.fullmatch(r'wa-document-[0-9a-f]{64}',row['idempotency_key'])
    assert 'content_b64' not in row and 'content' not in row and 'send_token' not in row
    preview=store.get(row['token'],7,include_content=True,db_factory=db,now=NOW)
    assert preview['content']==PDF
    assert store.get(row['token'],8,include_content=True,db_factory=db,now=NOW) is None
    sending=claim(db,row)
    assert sending['state']=='sending' and sending['content']==PDF and sending['confirmed_at']==NOW.isoformat()
    assert raw(db,row['token'])['state']=='sending'
    assert store.send_authorized(row['token'],sending['send_token'],db_factory=db,now=NOW)
    for field in ('account_id','conversation_id','recipient','filename','caption','sha256','creator_id','idempotency_key'):
        assert sending[field]==row[field]
    with pytest.raises(store.StoreError) as error:claim(db,row)
    assert error.value.status_code==409


@pytest.mark.parametrize('field,value',[
    ('confirmed_sha256','0'*64),('confirmed_recipient','966500000002'),('confirmed_account_id','other'),
])
def test_exact_review_confirmation_cannot_retarget_document(db,field,value):
    row=create(db)
    with pytest.raises(store.StoreError) as error:claim(db,row,**{field:value})
    assert error.value.reason=='confirmation_mismatch'
    assert raw(db,row['token'])['state']=='draft'
    assert raw(db,row['token'])['content_b64']


def test_claim_and_cancel_are_creator_only(db):
    row=create(db)
    with pytest.raises(store.StoreError) as error:
        store.claim(row['token'],8,confirmed_sha256=row['sha256'],confirmed_recipient=row['recipient'],
            confirmed_account_id=row['account_id'],db_factory=db,now=NOW)
    assert error.value.status_code==404
    with pytest.raises(store.StoreError):store.cancel(row['token'],8,db_factory=db,now=NOW)
    assert raw(db,row['token'])['state']=='draft'


@pytest.mark.parametrize('outcome',['accepted','blocked','failed','uncertain','partial','public_link_warning'])
def test_terminal_outcomes_wipe_private_bytes_and_never_reopen(db,outcome):
    row=create(db);sending=claim(db,row)
    done=store.finish(row['token'],sending['send_token'],status=outcome,provider_ids=['wamid.synthetic'],db_factory=db,now=NOW)
    assert done['state']==outcome and done['provider_ids']==['wamid.synthetic']
    assert raw(db,row['token'])['content_b64'] is None
    assert done['sha256']==row['sha256'] and done['caption']==row['caption']
    assert not store.send_authorized(row['token'],sending['send_token'],db_factory=db,now=NOW)
    assert store.get(row['token'],7,include_content=True,db_factory=db,now=NOW)['content'] is None
    with pytest.raises(store.StoreError):claim(db,row)
    with pytest.raises(store.StoreError):
        store.finish(row['token'],sending['send_token'],status='accepted',db_factory=db,now=NOW)


def test_finish_requires_original_claim_token(db):
    row=create(db);sending=claim(db,row)
    with pytest.raises(store.StoreError):
        store.finish(row['token'],'wrong',status='accepted',db_factory=db,now=NOW)
    assert raw(db,row['token'])['state']=='sending'
    assert not store.send_authorized(row['token'],'wrong',db_factory=db,now=NOW)


def test_concurrent_claims_have_one_winner(db):
    row=create(db)
    def attempt(_):
        try:return claim(db,row)
        except store.StoreError:return None
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(attempt,range(8)))
    assert len([value for value in results if value])==1


def test_creator_count_and_total_byte_quotas_include_sending(db,monkeypatch):
    first=create(db);claim(db,first)
    create(db,content=PDF+b'2');create(db,content=PDF+b'3')
    with pytest.raises(store.StoreError) as error:create(db,content=PDF+b'4')
    assert error.value.reason=='staging_quota_exceeded'
    create(db,creator_id=8,content=PDF+b'4')
    monkeypatch.setattr(store,'MAX_ACTIVE_BYTES',len(PDF)*2)
    create(db,creator_id=9,content=PDF+b'a')
    with pytest.raises(store.StoreError):create(db,creator_id=9,content=PDF+b'b')


def test_concurrent_create_quota_never_exceeds_three(db):
    def attempt(number):
        try:return create(db,content=PDF+str(number).encode())
        except store.StoreError:return None
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(attempt,range(8)))
    assert len([value for value in results if value])==3


def test_duplicate_fingerprint_cross_creator_conversation_name_caption_and_plus(db):
    row=create(db)
    for values in ({'creator_id':8},{'conversation_id':'other'}, {'creator_id':8,'caption':'changed','filename':'new.pdf'}):
        with pytest.raises(store.StoreError) as error:create(db,**values)
        assert error.value.reason=='duplicate_frozen'
    for values in ({'filename':'renamed.pdf'},{'caption':'changed'},{'recipient':'+966500000001'}):
        recovered=create(db,**values)
        assert recovered['token']==row['token'] and recovered['filename']==row['filename'] and recovered['caption']==row['caption']
    plus=create(db,recipient='+966500000002')
    assert plus['recipient']=='966500000002'
    create(db,account_id='other-account')
    assert raw(db,row['token'])['state']=='draft'


@pytest.mark.parametrize('outcome',['uncertain','partial','public_link_warning','failed'])
def test_unresolved_reupload_stays_frozen_beyond_blob_expiry(db,outcome):
    row=create(db);sending=claim(db,row)
    store.finish(row['token'],sending['send_token'],status=outcome,db_factory=db,now=NOW)
    with pytest.raises(store.StoreError) as error:
        create(db,creator_id=8,caption='attempted bypass',filename='other.pdf',now=NOW+timedelta(days=3))
    assert error.value.reason=='duplicate_frozen'
    assert raw(db,row['token'])['content_b64'] is None


def test_accepted_duplicate_freeze_is_twenty_four_hours(db):
    row=create(db);sending=claim(db,row)
    store.finish(row['token'],sending['send_token'],status='accepted',db_factory=db,now=NOW)
    with pytest.raises(store.StoreError):create(db,now=NOW+timedelta(hours=23))
    new=create(db,now=NOW+timedelta(days=1))
    assert new['token']!=row['token'] and new['idempotency_key']!=row['idempotency_key']


def test_draft_expiry_purges_even_when_claim_raises(db):
    row=create(db)
    with pytest.raises(store.StoreError) as error:claim(db,row,now=NOW+timedelta(hours=1))
    assert error.value.status_code==410
    assert raw(db,row['token'])['state']=='expired' and raw(db,row['token'])['content_b64'] is None
    assert create(db,now=NOW+timedelta(hours=1))['state']=='draft'


def test_sending_expiry_is_uncertain_not_reclaimed_and_duplicate_stays_frozen(db):
    row=create(db);sending=claim(db,row)
    late=NOW+timedelta(hours=1)
    assert not store.send_authorized(row['token'],sending['send_token'],db_factory=db,now=late)
    assert store.cleanup(db_factory=db,now=late)==1
    assert raw(db,row['token'])['state']=='uncertain' and raw(db,row['token'])['content_b64'] is None
    with pytest.raises(store.StoreError):claim(db,row,now=late)
    with pytest.raises(store.StoreError):create(db,creator_id=8,now=late)
    late_audit=store.finish(row['token'],sending['send_token'],status='accepted',provider_ids=['late-id'],db_factory=db,now=late)
    assert late_audit['state']=='uncertain' and late_audit['provider_ids']==['late-id']
    assert raw(db,row['token'])['content_b64'] is None


def test_duplicate_rejection_does_not_roll_back_expired_byte_cleanup(db):
    row=create(db);claim(db,row)
    with pytest.raises(store.StoreError) as error:create(db,creator_id=8,now=NOW+timedelta(hours=1))
    assert error.value.reason=='duplicate_frozen'
    assert raw(db,row['token'])['state']=='uncertain' and raw(db,row['token'])['content_b64'] is None


def test_cancel_purges_and_allows_fresh_review_not_old_claim(db):
    row=create(db)
    assert store.cancel(row['token'],7,db_factory=db,now=NOW)['state']=='cancelled'
    assert raw(db,row['token'])['content_b64'] is None
    with pytest.raises(store.StoreError):claim(db,row)
    assert create(db)['token']!=row['token']


@pytest.mark.parametrize('field,value',[
    ('content_b64',base64.b64encode(PDF+b'TAMPER').decode()),('content_b64','not-base64!'),
    ('filename','changed.pdf'),('caption','changed caption'),('account_id','other'),
    ('conversation_id','other'),('recipient','966500000002'),('sha256','0'*64),('byte_count',1),
    ('idempotency_key','wa-document-'+'0'*64),
])
def test_claim_reverifies_bytes_and_every_review_binding(db,field,value):
    row=create(db)
    with db() as connection:
        connection.execute('UPDATE whatsapp_document_drafts SET '+field+'=%s WHERE token=%s',(value,row['token']))
    with pytest.raises(store.StoreError) as error:claim(db,row)
    assert error.value.reason=='integrity_failed'
    assert raw(db,row['token'])['state']=='blocked' and raw(db,row['token'])['content_b64'] is None


def test_readonly_send_guard_detects_binding_change_and_expiry(db):
    row=create(db);sending=claim(db,row)
    with db() as connection:
        connection.execute('UPDATE whatsapp_document_drafts SET caption=%s WHERE token=%s',('changed',row['token']))
    assert not store.send_authorized(row['token'],sending['send_token'],db_factory=db,now=NOW)
    assert raw(db,row['token'])['state']=='sending'


def test_long_valid_provider_ids_align_with_transport(db):
    row=create(db);sending=claim(db,row)
    provider_id='wamid:.'+'A'*1017
    assert len(provider_id)==1024
    finished=store.finish(row['token'],sending['send_token'],status='accepted',provider_ids=[provider_id],db_factory=db,now=NOW)
    assert finished['provider_ids']==[provider_id] and raw(db,row['token'])['content_b64'] is None


@pytest.mark.parametrize('ids', [['https://private.invalid/url'],['data:SECRET'],['/download/id'],['A'*1025],['id']*6])
def test_provider_audit_rejects_urls_unbounded_data_and_untrusted_shapes(db,ids):
    row=create(db);sending=claim(db,row)
    with pytest.raises(store.StoreError):
        store.finish(row['token'],sending['send_token'],status='accepted',provider_ids=ids,db_factory=db,now=NOW)
    assert raw(db,row['token'])['provider_ids']=='[]'


@pytest.mark.parametrize('changes',[
    {'filename':'../secret.pdf'},{'filename':'other.txt'},{'filename':'x\\y.pdf'},
    {'filename':'bad\r\n.pdf'},{'filename':'x.pdf:other.pdf'},{'filename':'a'*177+'.pdf'},
    {'filename':'أ'*130+'.pdf'},{'caption':'x'*1025},{'content':b'not pdf'},
])
def test_invalid_staging_inputs_rejected(db,changes):
    with pytest.raises(store.StoreError):create(db,**changes)


def test_oversized_file_rejected_before_any_staging(db):
    with pytest.raises(store.StoreError) as error:create(db,content=b'%PDF-'+b'x'*store.MAX_FILE_BYTES)
    assert error.value.status_code==413
    with db() as connection:
        assert connection.execute('SELECT COUNT(*) n FROM whatsapp_document_drafts').fetchone()['n']==0


@pytest.mark.parametrize('cleanup_first',[False,True])
def test_late_owned_provider_receipt_only_adds_bounded_audit_after_expiry(db,cleanup_first):
    row=create(db);sending=claim(db,row);late=NOW+timedelta(hours=1,seconds=1)
    if cleanup_first:store.cleanup(db_factory=db,now=late)
    audit=store.finish(row['token'],sending['send_token'],status='accepted',provider_ids=['late:receipt'],db_factory=db,now=late)
    assert audit['state']=='uncertain' and audit['reason']=='late_receipt_accepted'
    assert audit['provider_ids']==['late:receipt'] and raw(db,row['token'])['content_b64'] is None
    repeated=store.finish(row['token'],sending['send_token'],status='partial',provider_ids=['different-id'],db_factory=db,now=late)
    assert repeated['state']=='uncertain' and repeated['provider_ids']==['late:receipt']
    assert not store.send_authorized(row['token'],sending['send_token'],db_factory=db,now=late)
    with pytest.raises(store.StoreError):create(db,creator_id=8,now=late)


@pytest.mark.parametrize('field,value',[('caption','changed after claim'),('content_b64','corrupted')])
def test_integrity_failure_after_claim_freezes_uncertain_across_reuploads(db,field,value):
    row=create(db);sending=claim(db,row)
    with db() as connection:
        connection.execute('UPDATE whatsapp_document_drafts SET '+field+'=%s WHERE token=%s',(value,row['token']))
    audited=store.get(row['token'],7,include_content=True,db_factory=db,now=NOW)
    assert audited['state']=='uncertain' and audited['reason']=='integrity_failed'
    assert audited['content'] is None
    with pytest.raises(store.StoreError):create(db,creator_id=8)


def test_late_public_link_warning_is_visible_sticky_but_never_reopens(db):
    row=create(db);sending=claim(db,row);late=NOW+timedelta(hours=1,seconds=1)
    store.cleanup(db_factory=db,now=late)
    warning=store.finish(row['token'],sending['send_token'],status='public_link_warning',
        provider_ids=['warning:receipt'],db_factory=db,now=late)
    assert warning['state']=='uncertain' and warning['reason']=='late_receipt_public_link_warning'
    assert warning['provider_status']=='public_link_warning'
    later=store.finish(row['token'],sending['send_token'],status='accepted',provider_ids=['other-id'],db_factory=db,now=late)
    assert later['reason']=='late_receipt_public_link_warning' and later['provider_ids']==['warning:receipt']
    assert raw(db,row['token'])['content_b64'] is None
    with pytest.raises(store.StoreError):create(db,creator_id=8,now=late)


def test_lost_upload_response_recovers_only_same_owner_unexpired_draft_metadata(db):
    row=create(db)
    recovered=create(db,filename='changed.pdf',caption='changed caption',now=NOW+timedelta(minutes=5))
    assert recovered.pop('recovered') is True and recovered==row
    assert 'content' not in recovered and 'content_b64' not in recovered and 'send_token' not in recovered
    with db() as connection:
        assert connection.execute('SELECT COUNT(*) n FROM whatsapp_document_drafts').fetchone()['n']==1
    with pytest.raises(store.StoreError):create(db,creator_id=8)
    sending=claim(db,row)
    with pytest.raises(store.StoreError):create(db)
    store.finish(row['token'],sending['send_token'],status='uncertain',db_factory=db,now=NOW)
    with pytest.raises(store.StoreError):create(db)


@pytest.mark.parametrize('status,reason',[
    ('uncertain','invalid_receipt'),('uncertain','receipt_mismatch'),
    ('uncertain','contradictory_response'),('partial',None),('public_link_warning',None),
])
def test_receipt_quality_and_privacy_flag_are_independent_frozen_evidence(db,status,reason):
    row=create(db);sending=claim(db,row)
    result=store.finish(row['token'],sending['send_token'],status=status,
        provider_ids=['synthetic-receipt'],public_attachment_url_present=True,
        receipt_reason=reason,db_factory=db,now=NOW)
    assert result['state']==status and result['receipt_reason']==reason
    assert result['public_attachment_url_present'] and result['provider_ids']==['synthetic-receipt']
    assert raw(db,row['token'])['content_b64'] is None
    verified=store.get(row['token'],7,require_valid_binding=True,db_factory=db,now=NOW)
    assert verified['sha256']==row['sha256'] and verified['public_attachment_url_present']
    with pytest.raises(store.StoreError):claim(db,row)
    with pytest.raises(store.StoreError):create(db,creator_id=8)


def test_late_receipt_privacy_flag_and_first_quality_survive_further_evidence(db):
    row=create(db);sending=claim(db,row);late=NOW+timedelta(hours=1,seconds=1)
    first=store.finish(row['token'],sending['send_token'],status='uncertain',
        provider_ids=['synthetic-receipt'],receipt_reason='receipt_mismatch',
        public_attachment_url_present=True,db_factory=db,now=late)
    assert first['state']=='uncertain' and first['public_attachment_url_present']
    later=store.finish(row['token'],sending['send_token'],status='accepted',
        provider_ids=['different-receipt'],public_attachment_url_present=False,
        receipt_reason=None,db_factory=db,now=late)
    assert later['state']=='uncertain' and later['public_attachment_url_present']
    assert later['receipt_reason']=='receipt_mismatch' and later['provider_ids']==['synthetic-receipt']
    assert raw(db,row['token'])['content_b64'] is None
    with pytest.raises(store.StoreError):create(db,creator_id=8,now=late)


def test_late_privacy_evidence_can_be_added_without_replacing_receipt_quality(db):
    row=create(db);sending=claim(db,row);late=NOW+timedelta(hours=1,seconds=1)
    first=store.finish(row['token'],sending['send_token'],status='uncertain',
        provider_ids=['synthetic-receipt'],receipt_reason='invalid_receipt',
        db_factory=db,now=late)
    assert not first['public_attachment_url_present']
    later=store.finish(row['token'],sending['send_token'],status='partial',
        public_attachment_url_present=True,receipt_reason='partial_failure',db_factory=db,now=late)
    assert later['state']=='uncertain' and later['public_attachment_url_present']
    assert later['receipt_reason']=='invalid_receipt' and later['provider_ids']==['synthetic-receipt']


@pytest.mark.parametrize('changes',[
    {'public_attachment_url_present':'https://private.invalid?token=secret'},
    {'public_attachment_url_present':1}, {'receipt_reason':'https://private.invalid?token=secret'},
    {'receipt_reason':{'error':'private body'}},
])
def test_privacy_receipt_audit_rejects_unbounded_shapes_without_modification(db,changes):
    row=create(db);sending=claim(db,row);before=raw(db,row['token'])
    with pytest.raises((store.StoreError,TypeError)):
        store.finish(row['token'],sending['send_token'],status='uncertain',db_factory=db,now=NOW,**changes)
    assert raw(db,row['token'])==before


@pytest.mark.parametrize('field,value',[
    ('filename','changed.pdf'),('caption','changed caption'),('account_id','other'),
    ('conversation_id','other'),('recipient','966500000002'),('sha256','0'*64),('byte_count',1),
    ('idempotency_key','wa-document-'+'0'*64),
    ('created_at',(NOW-timedelta(hours=1)).isoformat()),
    ('expires_at',(NOW+timedelta(hours=2)).isoformat()),
])
def test_terminal_diagnostic_get_verifies_immutable_binding_without_mutation(db,field,value):
    row=create(db);sending=claim(db,row)
    store.finish(row['token'],sending['send_token'],status='public_link_warning',
        provider_ids=['synthetic-receipt'],db_factory=db,now=NOW)
    with db() as connection:
        connection.execute('UPDATE whatsapp_document_drafts SET '+field+'=%s WHERE token=%s',(value,row['token']))
    before=raw(db,row['token'])
    with pytest.raises(store.StoreError) as caught:
        store.get(row['token'],7,require_valid_binding=True,db_factory=db,now=NOW)
    assert caught.value.status_code==409 and caught.value.reason=='integrity_failed'
    assert raw(db,row['token'])==before and before['content_b64'] is None


def test_terminal_binding_read_keeps_creator_scoping(db):
    row=create(db);sending=claim(db,row)
    store.finish(row['token'],sending['send_token'],status='accepted',
        provider_ids=['synthetic-receipt'],db_factory=db,now=NOW)
    assert store.get(row['token'],8,require_valid_binding=True,db_factory=db,now=NOW) is None
    assert store.get(row['token'],7,require_valid_binding=True,db_factory=db,now=NOW)['state']=='accepted'


@pytest.mark.parametrize('state,reason',[
    ('public_link_warning','public_link_warning'),
    ('uncertain','late_receipt_public_link_warning'),
    ('uncertain','integrity_failed_public_link_warning'),
])
def test_legacy_privacy_warning_remains_boolean_evidence_after_migration(db,state,reason):
    row=create(db);sending=claim(db,row)
    store.finish(row['token'],sending['send_token'],status='public_link_warning',db_factory=db,now=NOW)
    with db() as connection:
        connection.execute('''UPDATE whatsapp_document_drafts
            SET state=%s,reason=%s,public_attachment_url_present=0 WHERE token=%s''',(state,reason,row['token']))
    result=store.get(row['token'],7,db_factory=db,now=NOW)
    assert result['public_attachment_url_present'] is True and result['state']==state
    assert result['receipt_reason'] is None


def test_public_privacy_flag_is_boolean_for_rows_without_warnings(db):
    row=create(db)
    assert row['public_attachment_url_present'] is False
    assert store.get(row['token'],7,db_factory=db,now=NOW)['public_attachment_url_present'] is False
