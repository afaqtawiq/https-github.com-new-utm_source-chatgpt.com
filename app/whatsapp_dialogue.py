"""Scoped outbound text evidence, never intent rules or execution authority."""
from datetime import timedelta
from hashlib import sha256
from app import whatsapp_agent_store as store
from app import whatsapp_agent_privacy as privacy


def table_exists(c, name):
    if getattr(c, 'dialect', None) == 'sqlite':
        return bool(c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=%s", (name,)).fetchone())
    row = c.execute('SELECT to_regclass(%s) AS name', (name,)).fetchone()
    return bool(row and dict(row).get('name'))


def ensure_local_context(c):
    c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_agent_manual_context(
        draft_token TEXT PRIMARY KEY,account_id TEXT NOT NULL,
        authorization_generation BIGINT NOT NULL,accepted_at TEXT NOT NULL,
        body_sha256 TEXT NOT NULL,recipient TEXT NOT NULL,conversation_id TEXT NOT NULL,
        binding_basis TEXT NOT NULL DEFAULT 'accepted_send')''')


def capture_accepted(c, item, *, now=None):
    """Bind generation at the actual accepted send, in its existing transaction.

    No text is copied, no scope is inferred from settings.updated_at, and old
    unbound drafts are not backfilled. Send review and local privacy screening
    only preserve local evidence. A separate, explicit sharing permission is
    required before any of this text can become model context.
    """
    item=dict(item)
    if not table_exists(c, 'whatsapp_agent_settings'):
        return
    settings = c.execute('SELECT mode,authorization_generation FROM whatsapp_agent_settings WHERE account_id=%s',
                         (item['account_id'],)).fetchone()
    if not settings or settings['mode'] == 'off':
        return
    body = item['body']
    if not isinstance(body, str) or len(body) > 1500 or not privacy.screen_question(body).allowed:
        return
    ensure_local_context(c)
    c.execute('''INSERT INTO whatsapp_agent_manual_context(draft_token,account_id,authorization_generation,accepted_at,body_sha256,recipient,conversation_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(draft_token) DO NOTHING''',
        (item['token'], item['account_id'], settings['authorization_generation'], store._stamp(now),
         sha256(body.encode()).hexdigest(), item['recipient'], item['conversation_id']))
    bind_at_acceptance(c,item,settings['authorization_generation'],now=now)


def manual_question(job, *, now=None, require_sharing=True):
    """Return bounded historical evidence; never infer pending/closed state.

    Explicit quotes select exactly one accepted outbound source. Without a
    quote the latest attempted send wins (an uncertain/new unsafe one blocks
    fallback). A correction may refer to an answered question within 24 hours.
    """
    now = store._time(now)
    with store.database() as c:
        if not table_exists(c, 'whatsapp_agent_manual_context'):
            return None
        target = store._row(c.execute('''SELECT j.*,s.mode,s.pilot_sender,
            s.authorization_generation AS current_generation
            FROM whatsapp_agent_jobs j JOIN whatsapp_agent_settings s ON s.account_id=j.account_id
            WHERE j.id=%s AND j.status='processing' AND j.lease_token=%s AND j.lease_until>%s
              AND j.authorization_generation=s.authorization_generation''',
            (job['id'], job['lease_token'], store._stamp(now))).fetchone())
        if not target or not store._enabled(target, target):
            return None
        data = target['payload']
        quoted = data.get('quoted_reference_present') is True
        quote = data.get('quoted_platform_message_id')
        if quoted and not quote:
            return None
        row = c.execute('''SELECT d.token,d.body,d.state,d.provider_message_id,d.updated_at,
                   m.accepted_at,m.authorization_generation,m.body_sha256,
                   m.recipient AS bound_recipient,m.conversation_id AS bound_conversation
            FROM whatsapp_inbox_drafts d LEFT JOIN whatsapp_agent_manual_context m
              ON m.draft_token=d.token AND m.account_id=d.account_id
            WHERE d.account_id=%s AND d.recipient=%s AND d.conversation_id=%s
              AND d.state<>'draft' AND d.updated_at<=%s
            ''' + (' AND d.provider_message_id=%s' if quoted else '') +
            ' ORDER BY d.updated_at DESC,d.token DESC LIMIT 1',
            (target['account_id'], target['sender'], target['conversation_id'], target['created_at']) +
            ((quote,) if quoted else ())).fetchone()
        if (not row or row['state'] != 'accepted' or not row['provider_message_id'] or
                row['authorization_generation'] != target['authorization_generation'] or not row['accepted_at']):
            return None
        accepted = store._time(row['accepted_at'])
        if not now - timedelta(days=1) < accepted <= store._time(target['created_at']) <= now:
            return None
        body = row['body']
        if not isinstance(body, str) or len(body) > 1500:
            return None
        if (sha256(body.encode()).hexdigest() != row['body_sha256'] or
                row['bound_recipient'] != target['sender'] or row['bound_conversation'] != target['conversation_id']):
            return None
        permission_id=source_permission(c,row['token'],{k:target[k] for k in ('account_id','conversation_id','authorization_generation')}|{'recipient':target['sender']},now=now)
        if require_sharing and not permission_id:
            return None
        checked = privacy.screen_question(body)
        if not checked.allowed:
            return None
        return {key: target[key] for key in ('account_id','sender','conversation_id','authorization_generation')} | {
            'before_job_id':target['id'], 'question':checked.safe_text, 'accepted_at':store._stamp(accepted),
            'status':'accepted', 'receipt_present':True, 'category':'administrative_text',
            'relation':'historical_not_pending', 'quoted':quoted,
            'sharing_authorized':bool(permission_id),'permission_id':permission_id}


def quoted_exchange(job, records):
    """Select only an already scoped, sent, text-only pair by outbound receipt."""
    quote = job['payload'].get('quoted_platform_message_id')
    if not quote or not records:
        return ()
    with store.database() as c:
        rows = c.execute("SELECT job_id FROM whatsapp_agent_outbox WHERE status='sent' AND provider_message_id=%s", (quote,)).fetchall()
    ids = {row['job_id'] for row in rows}
    matches = [record for record in records if record['job_id'] in ids]
    return matches if len(matches) == 1 else ()


# This control is deliberately OFF unless explicitly enabled after privacy review.
SHARING_FLAG = privacy.MANUAL_CONTEXT_SHARING_FLAG
PROVIDER = 'anthropic'
PURPOSE = 'administrative_question_context'


def sharing_enabled():
    import os
    return os.getenv(SHARING_FLAG, '') == '1'


def ensure_permissions(c):
    c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_agent_dialogue_permissions(
        id TEXT PRIMARY KEY,account_id TEXT NOT NULL,recipient TEXT NOT NULL,conversation_id TEXT NOT NULL,
        authorization_generation BIGINT NOT NULL,actor_id BIGINT NOT NULL,
        provider TEXT NOT NULL,purpose TEXT NOT NULL,scope_kind TEXT NOT NULL,draft_token TEXT,
        body_sha256 TEXT,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,revoked_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_agent_dialogue_bindings(
        draft_token TEXT PRIMARY KEY,permission_id TEXT NOT NULL)''')


def actor_active(c, actor_id):
    if not table_exists(c,'users') or not table_exists(c,'user_mfa'):
        return False
    user=c.execute('''SELECT u.role,u.is_active,m.mfa_enabled FROM users u
        JOIN user_mfa m ON m.user_id=u.id WHERE u.id=%s''',(actor_id,)).fetchone()
    if not user or user['role']!='admin' or not user['is_active'] or not user['mfa_enabled']:
        return False
    if table_exists(c,'role_permissions'):
        permission=c.execute("SELECT allowed FROM role_permissions WHERE role='admin' AND permission='send_whatsapp'").fetchone()
        if permission and not permission['allowed']:
            return False
    return True


def permission_valid(c, permission, scope, *, now=None):
    now=store._time(now)
    return bool(sharing_enabled() and permission and not permission['revoked_at']
        and permission['provider']==PROVIDER and permission['purpose']==PURPOSE
        and all(permission[k]==scope[k] for k in ('account_id','recipient','conversation_id','authorization_generation'))
        and store._time(permission['created_at'])<=now<store._time(permission['expires_at'])
        and actor_active(c,permission['actor_id']))


def grant_permission(c,item,actor_id,*,scope_kind,minutes=60,now=None):
    """Called only by the existing admin+permission+MFA+CSRF guarded UI route."""
    import secrets
    now=store._time(now)
    if not sharing_enabled() or scope_kind not in ('draft','conversation') or type(minutes) is not int or not 1<=minutes<=1440:
        raise ValueError('Sharing disabled or invalid scope/duration')
    if not actor_active(c,actor_id) or item.get('created_by')!=actor_id or item['state'] not in ('draft','accepted'):
        raise ValueError('Authorized administrator and reviewable draft required')
    if not privacy.screen_question(item['body']).allowed:
        raise ValueError('Text must pass the existing privacy gate')
    settings=c.execute('SELECT mode,authorization_generation FROM whatsapp_agent_settings WHERE account_id=%s',(item['account_id'],)).fetchone()
    if not settings or settings['mode']=='off':raise ValueError('Active agent scope required')
    ensure_permissions(c)
    scope={k:item[k] for k in ('account_id','recipient','conversation_id')}|{'authorization_generation':settings['authorization_generation']}
    if scope_kind=='draft' and source_permission(c,item['token'],scope,now=now):
        raise ValueError('Revoke or let the current draft binding expire before replacing it')
    permission_id=secrets.token_hex(24)
    c.execute('''INSERT INTO whatsapp_agent_dialogue_permissions
        (id,account_id,recipient,conversation_id,authorization_generation,actor_id,provider,purpose,
         scope_kind,draft_token,body_sha256,created_at,expires_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (permission_id,item['account_id'],item['recipient'],item['conversation_id'],settings['authorization_generation'],
         actor_id,PROVIDER,PURPOSE,scope_kind,item['token'] if scope_kind=='draft' else None,
         sha256(item['body'].encode()).hexdigest() if scope_kind=='draft' else None,
         store._stamp(now),store._stamp(now+timedelta(minutes=minutes))))
    # A standing grant covers future accepted questions, never old drafts by inference.
    if scope_kind=='draft' and item['state']=='accepted':
        # This is an explicit review of this exact existing draft, not an
        # automatic backfill or an assertion about its old send-time generation.
        if not item.get('updated_at'):
            raise ValueError('Accepted timestamp required')
        accepted=store._time(item['updated_at'])
        if not item.get('provider_message_id') or not now-timedelta(days=1)<accepted<=now:
            raise ValueError('Accepted receipt within 24 hours required')
        ensure_local_context(c)
        c.execute('''INSERT INTO whatsapp_agent_manual_context
            (draft_token,account_id,authorization_generation,accepted_at,body_sha256,recipient,conversation_id,binding_basis)
            VALUES(%s,%s,%s,%s,%s,%s,%s,'explicit_draft_review')
            ON CONFLICT(draft_token) DO UPDATE SET account_id=excluded.account_id,
            authorization_generation=excluded.authorization_generation,accepted_at=excluded.accepted_at,
            body_sha256=excluded.body_sha256,recipient=excluded.recipient,conversation_id=excluded.conversation_id,
            binding_basis=excluded.binding_basis''',
            (item['token'],item['account_id'],settings['authorization_generation'],store._stamp(accepted),
             sha256(item['body'].encode()).hexdigest(),item['recipient'],item['conversation_id']))
        bind_permission(c,item['token'],permission_id)
    return permission_id


def bind_permission(c,token,permission_id):
    c.execute('''INSERT INTO whatsapp_agent_dialogue_bindings(draft_token,permission_id) VALUES(%s,%s)
        ON CONFLICT(draft_token) DO UPDATE SET permission_id=excluded.permission_id''',(token,permission_id))


def bind_at_acceptance(c,item,generation,*,now=None):
    if not sharing_enabled() or not table_exists(c,'whatsapp_agent_dialogue_permissions'):
        return
    now=store._time(now)
    scope={k:item[k] for k in ('account_id','recipient','conversation_id')}|{'authorization_generation':generation}
    if c.execute('SELECT permission_id FROM whatsapp_agent_dialogue_bindings WHERE draft_token=%s',(item['token'],)).fetchone():
        return  # automatic capture must never replace an expired/revoked binding
    explicit=c.execute('''SELECT * FROM whatsapp_agent_dialogue_permissions
        WHERE draft_token=%s AND scope_kind='draft' AND actor_id=%s ORDER BY created_at DESC LIMIT 1''',
        (item['token'],item.get('created_by'))).fetchone()
    if explicit:
        if permission_valid(c,explicit,scope,now=now) and explicit['body_sha256']==sha256(item['body'].encode()).hexdigest():
            bind_permission(c,item['token'],explicit['id'])
        return  # no broader standing fallback after a specific refusal/expiry
    rows=c.execute('''SELECT * FROM whatsapp_agent_dialogue_permissions WHERE account_id=%s
        AND recipient=%s AND conversation_id=%s AND authorization_generation=%s
        AND revoked_at IS NULL ORDER BY created_at DESC''',
        (item['account_id'],item['recipient'],item['conversation_id'],generation)).fetchall()
    for permission in rows:
        if (permission['actor_id']==item.get('created_by') and permission_valid(c,permission,scope,now=now) and
                (permission['scope_kind']=='conversation' or
                 (permission['draft_token']==item['token'] and permission['body_sha256']==sha256(item['body'].encode()).hexdigest()))):
            bind_permission(c,item['token'],permission['id'])
            return


def revoke_permission(c,permission_id,*,account_id,actor_id,now=None):
    if not actor_active(c,actor_id) or not table_exists(c,'whatsapp_agent_dialogue_permissions'):
        raise ValueError('Permission unavailable')
    c.execute('''UPDATE whatsapp_agent_dialogue_permissions SET revoked_at=%s
        WHERE id=%s AND account_id=%s AND actor_id=%s AND revoked_at IS NULL''',
        (store._stamp(now),permission_id,account_id,actor_id))


def source_permission(c,token,scope,*,now=None):
    if not sharing_enabled() or not table_exists(c,'whatsapp_agent_dialogue_bindings'):
        return None
    row=c.execute('''SELECT p.* FROM whatsapp_agent_dialogue_bindings b
        JOIN whatsapp_agent_dialogue_permissions p ON p.id=b.permission_id WHERE b.draft_token=%s''',(token,)).fetchone()
    return row['id'] if permission_valid(c,row,scope,now=now) else None


def permissions_current(permission_ids,job,*,now=None):
    if not permission_ids:return True
    with store.database() as c:
        if not table_exists(c,'whatsapp_agent_dialogue_permissions'):return False
        scope={k:job[k] for k in ('account_id','conversation_id','authorization_generation')}|{'recipient':job['sender']}
        for pid in permission_ids:
            row=c.execute('SELECT * FROM whatsapp_agent_dialogue_permissions WHERE id=%s',(pid,)).fetchone()
            if not permission_valid(c,row,scope,now=now):return False
    return True


def history_permissions(records):
    found=set()
    with store.database() as c:
        for record in records:
            row=store._row(c.execute('SELECT diagnostics FROM whatsapp_agent_jobs WHERE id=%s',(record['job_id'],)).fetchone())
            if row:found.update(row['diagnostics'].get('administrative_permission_ids',[]))
    return sorted(found)


def filter_history(records,job):
    return [record for record in records if permissions_current(history_permissions([record]),job)]
