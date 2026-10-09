"""Private, expiring PDF staging and a non-retryable manager document outbox.

Only local DB operations live here. Storage is imported lazily; callers inject a
transaction context factory in tests. A successful claim commits before returning
bytes, and no API ever reopens sending or a terminal send outcome.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json
import re
import secrets
import unicodedata

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ACTIVE_BYTES = 60 * 1024 * 1024
MAX_ACTIVE_DRAFTS = 3
TTL_SECONDS = 3600
ACCEPTED_FREEZE_SECONDS = 86400
TERMINAL_SEND_STATES = frozenset({'accepted','blocked','failed','uncertain','partial','public_link_warning'})
TERMINAL_STATES = TERMINAL_SEND_STATES | {'cancelled','expired'}
_SHA = re.compile(r'^[0-9a-f]{64}$')
_TOKEN = re.compile(r'^[A-Za-z0-9_-]{32,80}$')
_PROVIDER_ID = re.compile(r'^[A-Za-z0-9_.:+/=\-]{1,1024}$')
_BINDINGS = ('token','creator_id','account_id','conversation_id','recipient','filename','caption',
             'sha256','byte_count','idempotency_key','fingerprint','created_at','expires_at')


class StoreError(RuntimeError):
    def __init__(self, status_code, safe_reason):
        self.status_code = status_code
        self.reason = safe_reason
        super().__init__(safe_reason)


@contextmanager
def database():
    from app.storage import db
    with db() as connection:
        yield connection


def _now(value=None):
    value = value or datetime.now(timezone.utc)
    if isinstance(value,str):
        value = datetime.fromisoformat(value.replace('Z','+00:00'))
    if not isinstance(value,datetime) or value.tzinfo is None:
        raise StoreError(400,'invalid_timestamp')
    return value.astimezone(timezone.utc)


def _stamp(value=None):
    return _now(value).isoformat()


def _lock(connection, skip=False):
    if getattr(connection,'dialect',None)=='sqlite':
        return ''
    return ' FOR UPDATE'+(' SKIP LOCKED' if skip else '')


def _field(value, name, maximum=512):
    if (not isinstance(value,str) or not value or value != value.strip() or len(value)>maximum or
            any(unicodedata.category(char) in ('Cc','Cf','Zl','Zp') for char in value)):
        raise StoreError(400,'invalid_'+name)
    return value


def _creator(value):
    if type(value) is int and value>0:
        value=str(value)
    return _field(value,'creator_id',128)


def _filename(value):
    _field(value,'filename',180)
    if (len(value.encode('utf-8'))>255 or not value.lower().endswith('.pdf') or
            not value[:-4].strip(' .') or any(char in value for char in '/\\:"')):
        raise StoreError(400,'invalid_filename')
    return value


def _caption(value):
    if not isinstance(value,str) or len(value)>1024 or '\x00' in value:
        raise StoreError(400,'invalid_caption')
    return value


def _json(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),sort_keys=True,allow_nan=False)


def _binding_hash(row):
    values={key:row[key] for key in _BINDINGS}
    values['created_at'],values['expires_at']=_stamp(values['created_at']),_stamp(values['expires_at'])
    return hashlib.sha256(_json(values).encode('utf-8')).hexdigest()


def _valid_binding(row):
    try:
        return hmac.compare_digest(row['binding_sha256'],_binding_hash(row))
    except (KeyError,TypeError,ValueError,StoreError):
        return False


def _decode(row):
    encoded=row.get('content_b64')
    if not isinstance(encoded,str) or len(encoded)>4*((MAX_FILE_BYTES+2)//3):
        raise StoreError(409,'integrity_failed')
    try:
        content=base64.b64decode(encoded,validate=True)
    except (ValueError,TypeError):
        raise StoreError(409,'integrity_failed') from None
    if (not content or len(content)>MAX_FILE_BYTES or len(content)!=row['byte_count'] or
            not content.startswith(b'%PDF-') or not isinstance(row.get('sha256'),str) or
            not hmac.compare_digest(hashlib.sha256(content).hexdigest(),row['sha256'])):
        raise StoreError(409,'integrity_failed')
    return content


def _public(row, *, content=None, include_content=False, send_token=False):
    if not row:
        return None
    result={key:value for key,value in dict(row).items()
            if key not in ('content_b64','binding_sha256','fingerprint','send_token')}
    result['provider_ids']=json.loads(result.get('provider_ids') or '[]')
    # Durable bounded receipt category is encoded in reason for late receipts;
    # expose a stable UI field without adding an unbounded provider payload.
    reason=result.get('reason','')
    receipt=reason.removeprefix('late_receipt_') if reason.startswith('late_receipt_') else reason
    result['provider_status']=receipt if receipt in TERMINAL_SEND_STATES else (
        'public_link_warning' if reason=='integrity_failed_public_link_warning' else None)
    # Old terminal rows predate the separate audit flag. Their recorded warning
    # remains privacy evidence after migration, independent of receipt quality.
    result['public_attachment_url_present']=bool(result.get('public_attachment_url_present')) or (
        result.get('state')=='public_link_warning' or result['provider_status']=='public_link_warning')
    for key in ('created_at','expires_at','updated_at','confirmed_at','sending_at','completed_at'):
        if result.get(key) is not None:
            result[key]=_stamp(result[key])
    if include_content:
        result['content']=content
    if send_token:
        result['send_token']=row['send_token']
    return result


DDL=(
    '''CREATE TABLE IF NOT EXISTS whatsapp_document_creators (
        creator_id TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS whatsapp_document_fingerprints (
        fingerprint TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS whatsapp_document_drafts (
        token TEXT PRIMARY KEY,creator_id TEXT NOT NULL REFERENCES whatsapp_document_creators(creator_id),
        account_id TEXT NOT NULL,conversation_id TEXT NOT NULL,recipient TEXT NOT NULL,
        filename TEXT NOT NULL,caption TEXT NOT NULL,sha256 TEXT NOT NULL,
        byte_count BIGINT NOT NULL CHECK(byte_count>0 AND byte_count<=20971520),
        content_b64 TEXT,binding_sha256 TEXT NOT NULL,
        fingerprint TEXT NOT NULL REFERENCES whatsapp_document_fingerprints(fingerprint),
        idempotency_key TEXT NOT NULL UNIQUE,
        state TEXT NOT NULL CHECK(state IN ('draft','sending','accepted','blocked','failed','uncertain',
            'partial','public_link_warning','cancelled','expired')),
        send_token TEXT,provider_ids TEXT NOT NULL DEFAULT '[]',reason TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,expires_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        confirmed_at TIMESTAMPTZ,sending_at TIMESTAMPTZ,completed_at TIMESTAMPTZ)''',
    'CREATE INDEX IF NOT EXISTS whatsapp_document_creator_idx ON whatsapp_document_drafts(creator_id,state,expires_at)',
    'CREATE INDEX IF NOT EXISTS whatsapp_document_fingerprint_idx ON whatsapp_document_drafts(fingerprint,state)',
    'CREATE INDEX IF NOT EXISTS whatsapp_document_expiry_idx ON whatsapp_document_drafts(expires_at,state)',
)


def init_storage(*,db_factory=None):
    with (db_factory or database)() as connection:
        for statement in DDL:
            connection.execute(statement)
        for name, definition in (('public_attachment_url_present', 'INTEGER NOT NULL DEFAULT 0'),
                                 ('receipt_reason', 'TEXT')):
            if getattr(connection, 'dialect', None) == 'sqlite':
                columns = {row['name'] for row in connection.execute('PRAGMA table_info(whatsapp_document_drafts)').fetchall()}
                if name not in columns:
                    connection.execute('ALTER TABLE whatsapp_document_drafts ADD COLUMN ' + name + ' ' + definition)
            else:
                connection.execute('ALTER TABLE whatsapp_document_drafts ADD COLUMN IF NOT EXISTS ' + name + ' ' + definition)


def _creator_lock(connection,creator,now,*,create=False):
    if create:
        connection.execute('''INSERT INTO whatsapp_document_creators(creator_id,created_at) VALUES(%s,%s)
            ON CONFLICT(creator_id) DO NOTHING''',(creator,_stamp(now)))
    return connection.execute('SELECT creator_id FROM whatsapp_document_creators WHERE creator_id=%s'+
        _lock(connection),(creator,)).fetchone()


def _row(connection,token,*,creator=None,lock=False):
    args=[token]
    scope=''
    if creator is not None:
        scope=' AND creator_id=%s'
        args.append(creator)
    row=connection.execute('SELECT * FROM whatsapp_document_drafts WHERE token=%s'+scope+
        (_lock(connection) if lock else ''),tuple(args)).fetchone()
    return dict(row) if row else None


def _terminal(connection,row,state,reason,now,*,provider_ids=None):
    if state not in TERMINAL_STATES:
        raise StoreError(400,'invalid_terminal_state')
    connection.execute('''UPDATE whatsapp_document_drafts SET state=%s,reason=%s,content_b64=NULL,
        provider_ids=%s,completed_at=%s,updated_at=%s WHERE token=%s''',
        (state,reason,_json(provider_ids if provider_ids is not None else json.loads(row['provider_ids'])),
         _stamp(now),_stamp(now),row['token']))
    return _row(connection,row['token'])


def _expire(connection,row,now):
    if row['state'] in ('draft','sending') and _now(row['expires_at'])<=now:
        state='uncertain' if row['state']=='sending' else 'expired'
        return _terminal(connection,row,state,'sending_expired' if state=='uncertain' else 'expired',now)
    return row


def _cleanup(connection,now,*,creator=None,fingerprint=None,limit=100):
    args=[_stamp(now)]
    scope=''
    if creator is not None:
        scope+=' AND creator_id=%s';args.append(creator)
    if fingerprint is not None:
        scope+=' AND fingerprint=%s';args.append(fingerprint)
    args.append(max(1,min(int(limit),100)))
    rows=connection.execute('''SELECT token,state,reason FROM whatsapp_document_drafts
        WHERE content_b64 IS NOT NULL AND (expires_at<=%s OR state NOT IN ('draft','sending'))'''+scope+
        ' ORDER BY expires_at,token LIMIT %s'+_lock(connection,skip=True),tuple(args)).fetchall()
    for raw in rows:
        row=dict(raw)
        state=('uncertain' if row['state']=='sending' else 'expired') if row['state'] in ('draft','sending') else row['state']
        reason=('sending_expired' if row['state']=='sending' else 'expired') if row['state'] in ('draft','sending') else row['reason']
        connection.execute('''UPDATE whatsapp_document_drafts SET content_b64=NULL,state=%s,reason=%s,
            updated_at=%s,completed_at=COALESCE(completed_at,%s) WHERE token=%s''',
            (state,reason,_stamp(now),_stamp(now),row['token']))
    return len(rows)


def cleanup(*,creator_id=None,db_factory=None,now=None,limit=100):
    current=_now(now)
    creator=_creator(creator_id) if creator_id is not None else None
    with (db_factory or database)() as connection:
        return _cleanup(connection,current,creator=creator,limit=limit)


def create(*,creator_id,account_id,conversation_id,recipient,filename,content,caption='',db_factory=None,now=None):
    creator=_creator(creator_id)
    account=_field(account_id,'account_id')
    conversation=_field(conversation_id,'conversation_id')
    target=_field(recipient,'recipient',32)
    if not re.fullmatch(r'\+?[1-9][0-9]{6,14}',target):
        raise StoreError(400,'invalid_recipient')
    target=target.lstrip('+')
    name,caption=_filename(filename),_caption(caption)
    if not isinstance(content,(bytes,bytearray)) or not content:
        raise StoreError(400,'invalid_content')
    if len(content)>MAX_FILE_BYTES:
        raise StoreError(413,'file_too_large')
    content=bytes(content)
    if not content.startswith(b'%PDF-'):
        raise StoreError(400,'invalid_pdf_header')
    current=_now(now)
    digest=hashlib.sha256(content).hexdigest()
    fingerprint=hashlib.sha256(_json([account,target,digest]).encode()).hexdigest()
    token=secrets.token_urlsafe(32)
    row=dict(token=token,creator_id=creator,account_id=account,conversation_id=conversation,
        recipient=target,filename=name,caption=caption,sha256=digest,byte_count=len(content),
        fingerprint=fingerprint,idempotency_key='wa-document-'+hashlib.sha256(token.encode()).hexdigest(),
        created_at=_stamp(current),expires_at=_stamp(current+timedelta(seconds=TTL_SECONDS)))
    binding=_binding_hash(row)
    # Cleanup commits independently even when the following admission fails.
    with (db_factory or database)() as connection:
        _cleanup(connection,current,creator=creator)
        _cleanup(connection,current,fingerprint=fingerprint)
    with (db_factory or database)() as connection:
        # Global per-recipient/file arbitration precedes creator quota locking.
        connection.execute('''INSERT INTO whatsapp_document_fingerprints(fingerprint,created_at) VALUES(%s,%s)
            ON CONFLICT(fingerprint) DO NOTHING''',(fingerprint,_stamp(current)))
        connection.execute('SELECT fingerprint FROM whatsapp_document_fingerprints WHERE fingerprint=%s'+
            _lock(connection),(fingerprint,)).fetchone()
        _creator_lock(connection,creator,current,create=True)
        duplicate=connection.execute('''SELECT token FROM whatsapp_document_drafts WHERE fingerprint=%s AND
            (state IN ('draft','sending','uncertain','partial','public_link_warning','failed')
             OR (state='accepted' AND completed_at>%s)) LIMIT 1''',
            (fingerprint,_stamp(current-timedelta(seconds=ACCEPTED_FREEZE_SECONDS)))).fetchone()
        if duplicate:
            existing=_row(connection,duplicate['token'],lock=True)
            if (existing and existing['state']=='draft' and existing['creator_id']==creator and
                    existing['account_id']==account and existing['recipient']==target and
                    existing['conversation_id']==conversation and existing['sha256']==digest and
                    _now(existing['expires_at'])>current and _valid_binding(existing)):
                # Lost-upload-response recovery only. Original review bindings,
                # token and expiry remain untouched, including filename/caption.
                recovered=_public(existing)
                recovered['recovered']=True
                return recovered
            raise StoreError(409,'duplicate_frozen')
        quota=connection.execute('''SELECT COUNT(*) n,COALESCE(SUM(byte_count),0) total
            FROM whatsapp_document_drafts WHERE creator_id=%s AND state IN ('draft','sending')
            AND expires_at>%s AND content_b64 IS NOT NULL''',(creator,_stamp(current))).fetchone()
        if quota['n']>=MAX_ACTIVE_DRAFTS or quota['total']+len(content)>MAX_ACTIVE_BYTES:
            raise StoreError(429,'staging_quota_exceeded')
        connection.execute('''INSERT INTO whatsapp_document_drafts
            (token,creator_id,account_id,conversation_id,recipient,filename,caption,sha256,byte_count,
             content_b64,binding_sha256,fingerprint,idempotency_key,state,reason,created_at,expires_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft','staged',%s,%s,%s)''',
            (token,creator,account,conversation,target,name,caption,digest,len(content),
             base64.b64encode(content).decode('ascii'),binding,fingerprint,row['idempotency_key'],
             row['created_at'],row['expires_at'],_stamp(current)))
        return _public(_row(connection,token))


def get(token,creator_id,*,include_content=False,require_valid_binding=False,db_factory=None,now=None):
    creator=_creator(creator_id)
    if not isinstance(token,str) or not _TOKEN.fullmatch(token):
        return None
    current=_now(now)
    with (db_factory or database)() as connection:
        row=_row(connection,token,creator=creator,lock=True)
        if not row:
            return None
        if require_valid_binding and not _valid_binding(row):
            raise StoreError(409, 'integrity_failed')
        row=_expire(connection,row,current)
        content=None
        if row['state'] in ('draft','sending'):
            if not _valid_binding(row):
                row=_terminal(connection,row,'uncertain' if row['state']=='sending' else 'blocked','integrity_failed',current)
            elif include_content:
                try:content=_decode(row)
                except StoreError:
                    row=_terminal(connection,row,'uncertain' if row['state']=='sending' else 'blocked','integrity_failed',current)
        return _public(row,content=content,include_content=include_content)


def claim(token,creator_id,*,confirmed_sha256,confirmed_recipient,confirmed_account_id,db_factory=None,now=None):
    creator=_creator(creator_id)
    current=_now(now)
    error=None;result=None
    with (db_factory or database)() as connection:
        if not _creator_lock(connection,creator,current):
            raise StoreError(404,'draft_not_found')
        row=_row(connection,token,creator=creator,lock=True)
        if not row:
            raise StoreError(404,'draft_not_found')
        row=_expire(connection,row,current)
        if row['state']=='expired':
            error=StoreError(410,'draft_expired')
        elif row['state']!='draft':
            error=StoreError(409,'draft_not_sendable')
        elif not _valid_binding(row):
            _terminal(connection,row,'blocked','integrity_failed',current)
            error=StoreError(409,'integrity_failed')
        elif (not isinstance(confirmed_sha256,str) or not _SHA.fullmatch(confirmed_sha256) or
              confirmed_sha256!=row['sha256'] or confirmed_recipient!=row['recipient'] or
              confirmed_account_id!=row['account_id']):
            error=StoreError(409,'confirmation_mismatch')
        else:
            try:content=_decode(row)
            except StoreError:
                _terminal(connection,row,'blocked','integrity_failed',current)
                error=StoreError(409,'integrity_failed')
            else:
                send_token=secrets.token_urlsafe(32)
                connection.execute('''UPDATE whatsapp_document_drafts SET state='sending',send_token=%s,
                    confirmed_at=%s,sending_at=%s,updated_at=%s,reason='send_claimed' WHERE token=%s''',
                    (send_token,_stamp(current),_stamp(current),_stamp(current),token))
                result=_public(_row(connection,token),content=content,include_content=True,send_token=True)
    if error:
        raise error
    return result


def send_authorized(token,send_token,*,db_factory=None,now=None):
    if not isinstance(send_token,str) or not _TOKEN.fullmatch(send_token):
        return False
    with (db_factory or database)() as connection:
        row=_row(connection,token)
        return bool(row and row['state']=='sending' and row['send_token']==send_token and
            _now(row['expires_at'])>_now(now) and row['content_b64'] is not None and _valid_binding(row))


def _provider_ids(values):
    if not isinstance(values,(list,tuple)) or len(values)>5:
        raise StoreError(400,'invalid_provider_ids')
    safe=[]
    for value in values:
        if (not isinstance(value,str) or not _PROVIDER_ID.fullmatch(value) or
                '://' in value or value.lower().startswith(('http:','https:','ftp:','file:','data:','mailto:','www.','/'))):
            raise StoreError(400,'invalid_provider_ids')
        if value not in safe:safe.append(value)
    return safe


def finish(token,send_token,*,status,provider_ids=(),public_attachment_url_present=False,
           receipt_reason=None,db_factory=None,now=None):
    if status not in TERMINAL_SEND_STATES:
        raise StoreError(400,'invalid_terminal_state')
    ids=_provider_ids(provider_ids)
    if type(public_attachment_url_present) is not bool:
        raise StoreError(400, 'invalid_privacy_flag')
    if receipt_reason is not None and (not isinstance(receipt_reason, str) or receipt_reason not in {
            'partial_failure', 'public_link_warning', 'invalid_receipt','receipt_mismatch','contradictory_response',
            'conversation_mismatch', 'provider_error', 'redirect', 'network_error',
            'malformed_response', 'uncertain'}):
        raise StoreError(400, 'invalid_receipt_reason')
    current=_now(now)
    error=None;result=None
    with (db_factory or database)() as connection:
        row=_row(connection,token,lock=True)
        if not row or not send_token or row['send_token']!=send_token:
            raise StoreError(409,'send_not_owned')
        row=_expire(connection,row,current)
        late_reason = row['reason'].removeprefix('late_receipt_') if row['reason'].startswith('late_receipt_') else None
        if row['state']=='uncertain' and (row['reason']=='sending_expired' or late_reason in TERMINAL_SEND_STATES):
            # A late owned receipt is audit evidence only. Preserve uncertainty,
            # the frozen fingerprint and wiped bytes; never reopen or resend.
            existing=json.loads(row['provider_ids'])
            reason=row['reason'] if late_reason else 'late_receipt_'+status
            if status=='public_link_warning' or late_reason=='public_link_warning':
                reason='late_receipt_public_link_warning'
            connection.execute('''UPDATE whatsapp_document_drafts SET provider_ids=%s,reason=%s,updated_at=%s
                WHERE token=%s''',(_json(existing or ids),reason,_stamp(current),token))
            result=_public(_row(connection,token))
        elif row['state']!='sending':
            error=StoreError(409,'send_already_terminal')
        elif not _valid_binding(row):
            result=_public(_terminal(connection,row,'uncertain','integrity_failed_public_link_warning' if status=='public_link_warning' else 'integrity_failed',current,provider_ids=ids))
        else:
            result=_public(_terminal(connection,row,status,status,current,provider_ids=ids))
        if result is not None:
            connection.execute('''UPDATE whatsapp_document_drafts
                SET public_attachment_url_present=CASE WHEN public_attachment_url_present=1 OR %s=1 THEN 1 ELSE 0 END,
                    receipt_reason=COALESCE(receipt_reason,%s) WHERE token=%s''',
                (int(public_attachment_url_present or status=='public_link_warning'),receipt_reason,token))
            result=_public(_row(connection,token))
    if error:raise error
    return result


def cancel(token,creator_id,*,db_factory=None,now=None):
    creator=_creator(creator_id);current=_now(now);error=None;result=None
    with (db_factory or database)() as connection:
        if not _creator_lock(connection,creator,current):
            raise StoreError(404,'draft_not_found')
        row=_row(connection,token,creator=creator,lock=True)
        if not row:raise StoreError(404,'draft_not_found')
        row=_expire(connection,row,current)
        if row['state']!='draft':error=StoreError(409,'draft_not_cancellable')
        else:result=_public(_terminal(connection,row,'cancelled','cancelled',current))
    if error:raise error
    return result
