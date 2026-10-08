"""Private-document races on ONLY an isolated schema in localhost/afaaq_test.

No application bootstrap, live DATABASE_URL, model, provider, upload or network
outside the explicitly configured disposable test PostgreSQL is used.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
import os
import secrets
import socket
import sys
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
NOW=datetime(2026,10,8,12,tzinfo=timezone.utc)
PDF=b'%PDF-1.4\nPrivate synthetic acceptance fixture\n%%EOF'


def verify(factory):
    from app import whatsapp_document_store as store
    store.init_storage(db_factory=factory);store.init_storage(db_factory=factory)
    def create(creator=7,**changes):
        options=dict(creator_id=creator,account_id='synthetic-account',conversation_id='synthetic-conversation',
            recipient='966500000001',filename='synthetic.pdf',caption='Synthetic review',content=PDF,
            db_factory=factory,now=NOW)
        options.update(changes)
        return store.create(**options)
    def claim(row,**changes):
        options=dict(confirmed_sha256=row['sha256'],confirmed_recipient=row['recipient'],
            confirmed_account_id=row['account_id'],db_factory=factory,now=NOW)
        options.update(changes)
        return store.claim(row['token'],row['creator_id'],**options)
    def row(token):
        with factory() as connection:
            return dict(connection.execute('SELECT * FROM whatsapp_document_drafts WHERE token=%s',(token,)).fetchone())
    def parallel(function,count=8):
        with ThreadPoolExecutor(max_workers=count) as pool:
            return list(pool.map(function,range(count)))
    def attempt(function):
        try:return function()
        except store.StoreError as error:return error.reason

    # Fingerprint locks choose one creator despite changed names/captions/threads
    # and equivalent +phone forms. No normal API can modify the reviewed bindings.
    duplicates=parallel(lambda number:attempt(lambda:create(100+number,
        recipient='+966500000001' if number%2 else '966500000001',
        filename='name-'+str(number)+'.pdf',caption='caption-'+str(number),
        conversation_id='conversation-'+str(number))),12)
    winners=[value for value in duplicates if isinstance(value,dict)]
    assert len(winners)==1 and duplicates.count('duplicate_frozen')==11
    draft=winners[0]
    assert draft['recipient']=='966500000001'
    assert store.get(draft['token'],'wrong-owner',db_factory=factory,now=NOW) is None
    for change in ({'confirmed_sha256':'0'*64},{'confirmed_recipient':'966500000009'},
                   {'confirmed_account_id':'other-account'}):
        assert attempt(lambda:claim(draft,**change))=='confirmation_mismatch'
    claims=parallel(lambda _:attempt(lambda:claim(draft)),8)
    claimed=[value for value in claims if isinstance(value,dict)]
    assert len(claimed)==1 and claims.count('draft_not_sendable')==7
    sending=claimed[0]
    assert sending['content']==PDF and row(draft['token'])['state']=='sending'
    assert sending['confirmed_at']==NOW.isoformat()
    assert store.send_authorized(draft['token'],sending['send_token'],db_factory=factory,now=NOW)
    long_id='wamid:.'+'A'*1017
    completed=store.finish(draft['token'],sending['send_token'],status='partial',provider_ids=[long_id],db_factory=factory,now=NOW)
    assert completed['provider_ids']==[long_id] and row(draft['token'])['content_b64'] is None
    assert attempt(lambda:create(999,filename='renamed.pdf',caption='new caption',now=NOW+timedelta(days=2)))=='duplicate_frozen'
    assert attempt(lambda:claim(draft))=='draft_not_sendable'

    # Distinct fingerprints still share one creator quota, under real row locks.
    quota=parallel(lambda number:attempt(lambda:create(500,content=PDF+str(number).encode())),8)
    quota_rows=[value for value in quota if isinstance(value,dict)]
    assert len(quota_rows)==3 and quota.count('staging_quota_exceeded')==5
    with factory() as connection:
        usage=connection.execute("""SELECT COUNT(*) n,SUM(byte_count) total FROM whatsapp_document_drafts
            WHERE creator_id='500' AND state IN ('draft','sending')""").fetchone()
        assert usage['n']==3 and usage['total']<=store.MAX_ACTIVE_BYTES

    # A never-claimed expired draft is wiped and can only be replaced by a new
    # explicit review. Existing old tokens never become sendable again.
    expiring=create(600,content=PDF+b'expiring')
    late=NOW+timedelta(hours=1)
    assert attempt(lambda:claim(expiring,now=late))=='draft_expired'
    assert row(expiring['token'])['content_b64'] is None
    restaged=create(601,content=PDF+b'expiring',now=late)
    assert restaged['token']!=expiring['token']
    assert store.cancel(restaged['token'],601,db_factory=factory,now=late)['state']=='cancelled'
    assert row(restaged['token'])['content_b64'] is None

    # An in-flight upload expires to uncertain forever. Late owned receipts add
    # bounded audit evidence and a sticky public-link category, never a retry.
    inflight=create(700,content=PDF+b'inflight')
    owned=claim(inflight)
    store.cleanup(db_factory=factory,now=late)
    assert row(inflight['token'])['state']=='uncertain' and row(inflight['token'])['content_b64'] is None
    receipt=store.finish(inflight['token'],owned['send_token'],status='public_link_warning',
        provider_ids=['late:provider-id'],db_factory=factory,now=late)
    assert receipt['state']=='uncertain' and receipt['reason']=='late_receipt_public_link_warning'
    repeated=store.finish(inflight['token'],owned['send_token'],status='accepted',
        provider_ids=['must-not-replace'],db_factory=factory,now=late)
    assert repeated['provider_ids']==['late:provider-id'] and repeated['reason']=='late_receipt_public_link_warning'
    assert not store.send_authorized(inflight['token'],owned['send_token'],db_factory=factory,now=late)
    assert attempt(lambda:create(701,content=PDF+b'inflight',now=late))=='duplicate_frozen'

    # Cleanup/admission races cannot resurrect an in-flight token or allow a
    # replacement upload. Cleanup commits even if replacement is rejected.
    race=create(800,content=PDF+b'cleanup-race')
    race_send=claim(race)
    def cleanup_race(number):
        if number%2:return store.cleanup(db_factory=factory,now=late)
        return attempt(lambda:create(801+number,content=PDF+b'cleanup-race',now=late))
    results=parallel(cleanup_race,8)
    assert all(value=='duplicate_frozen' for value in results[::2])
    assert row(race['token'])['state']=='uncertain' and row(race['token'])['content_b64'] is None
    assert not store.send_authorized(race['token'],race_send['send_token'],db_factory=factory,now=late)

    # Tampered bytes or reviewed metadata cannot cross the claim boundary, and
    # the integrity failure is committed together with the private-byte wipe.
    for index,(column,value) in enumerate((('content_b64','invalid-base64'),('caption','mutated caption'))):
        damaged=create(900+index,content=PDF+('tamper-'+str(index)).encode())
        with factory() as connection:
            connection.execute('UPDATE whatsapp_document_drafts SET '+column+'=%s WHERE token=%s',(value,damaged['token']))
        assert attempt(lambda:claim(damaged))=='integrity_failed'
        assert row(damaged['token'])['state']=='blocked' and row(damaged['token'])['content_b64'] is None

    print('PASS: private document fingerprint/quota races, immutable confirmation, single claim, '
          'terminal/TTL byte wiping, unresolved duplicate freeze, late receipt audit and integrity fencing. '
          'External uploads/model/provider calls: 0.')


def main():
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    url=os.environ.get('AFAAQ_TEST_DATABASE_URL','')
    target=urlsplit(url)
    if (target.scheme not in ('postgres','postgresql') or target.hostname not in ('localhost','127.0.0.1')
            or target.path!='/afaaq_test' or target.query or target.fragment):
        raise RuntimeError('Requires local disposable afaaq_test without URL parameters')
    schema='whatsapp_document_test_'+secrets.token_hex(8)
    original=socket.socket.connect
    def local_only(sock,address):
        if isinstance(address,tuple) and address[0] not in ('localhost','127.0.0.1','::1'):
            raise AssertionError('External network forbidden in document acceptance tests')
        return original(sock,address)
    @contextmanager
    def factory():
        with psycopg.connect(url,row_factory=dict_row) as connection:
            connection.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            connection.execute("SET LOCAL lock_timeout='10s'")
            connection.execute("SET LOCAL statement_timeout='20s'")
            yield connection
    with patch.object(socket.socket,'connect',local_only):
        with psycopg.connect(url,autocommit=True) as connection:
            connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            try:verify(factory)
            finally:connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__=='__main__':
    main()
