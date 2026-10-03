"""Owned official-mail CRM associations and approval-only reply drafts.

Ingestion never sends, creates customers or requests, advances sales stages,
closes tasks, or creates drafts. Matched prospect replies record only a reply or
stop. Only an explicit authenticated POST creates a blank reply draft.
"""
from fastapi import HTTPException
from app.storage import db, one, utcnow
from app.mail_threads import message_id, references, select_match, address


def init():
    with db() as c:
        for name in ('in_reply_to', 'message_references', 'sender_address', 'manual_reply_address'):
            c.execute('ALTER TABLE spacemail_inbox ADD COLUMN IF NOT EXISTS '+name+' TEXT')
        c.execute('ALTER TABLE spacemail_inbox ADD COLUMN IF NOT EXISTS duplicate_of BIGINT REFERENCES spacemail_inbox(id)')
        c.execute('ALTER TABLE outbound_messages ADD COLUMN IF NOT EXISTS mail_user_id BIGINT REFERENCES users(id)')
        c.execute('ALTER TABLE outbound_messages ADD COLUMN IF NOT EXISTS reply_inbox_id BIGINT REFERENCES spacemail_inbox(id)')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS outbound_reply_inbox_once ON outbound_messages(reply_inbox_id) WHERE reply_inbox_id IS NOT NULL')
        c.execute('ALTER TABLE sales_followups ADD COLUMN IF NOT EXISTS outbound_message_id BIGINT REFERENCES outbound_messages(id)')
        c.execute('''CREATE TABLE IF NOT EXISTS official_mail_links(
            inbox_id BIGINT PRIMARY KEY REFERENCES spacemail_inbox(id),
            user_id BIGINT NOT NULL REFERENCES users(id), status TEXT NOT NULL, reason TEXT NOT NULL,
            opportunity_id BIGINT REFERENCES opportunities(id) ON DELETE SET NULL,
            account_id BIGINT REFERENCES accounts(id) ON DELETE SET NULL,
            matched_outbound_id BIGINT REFERENCES outbound_messages(id) ON DELETE SET NULL,
            followup_id BIGINT REFERENCES sales_followups(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS official_mail_message_identity ON spacemail_inbox(user_id,message_id)')
        c.execute('CREATE INDEX IF NOT EXISTS outbound_provider_message_identity ON outbound_messages(provider_message_id)')
    from app.prospect_outreach import init as init_prospect_outreach
    init_prospect_outreach()


def ingest(uid, reconsider=False):
    """Bounded, idempotent local ingestion. Existing rows lacking headers stay review."""
    added = 0
    with db() as c:
        # Serialize mailbox ingestion and duplicate classification across pollers.
        c.execute('SELECT user_id FROM spacemail_connections WHERE user_id=%s FOR UPDATE', (uid,))
        items = c.execute('''SELECT i.* FROM spacemail_inbox i WHERE i.user_id=%s
            AND (NOT EXISTS(SELECT 1 FROM official_mail_links l WHERE l.inbox_id=i.id)
                OR (%s AND EXISTS(SELECT 1 FROM official_mail_links l WHERE l.inbox_id=i.id AND l.reason='no_exact_thread' AND l.status='review')))
            ORDER BY i.id DESC LIMIT 200''', (uid,reconsider)).fetchall()
        for item in items:
            match, reason = None, 'unsafe_or_legacy_headers'
            if item.get('duplicate_of'):
                reason = 'duplicate_message'
            elif item.get('manual_reply_address') and message_id(item.get('message_id')):
                ids = list(dict.fromkeys(references(item.get('message_references')) + references(item.get('in_reply_to'))))
                candidates = []
                if ids:
                    candidates = c.execute('''SELECT m.id,m.opportunity_id,m.prospect_id,o.account_id,m.recipient,m.provider_message_id,
                        m.mail_user_id
                        FROM outbound_messages m LEFT JOIN opportunities o ON o.id=m.opportunity_id
                        JOIN approvals a ON a.id=m.approval_id AND a.entity_type='outbound_message'
                            AND a.entity_id=m.id AND a.kind='external_send' AND a.status='approved'
                        WHERE m.status='sent' AND m.provider_message_id=ANY(%s)
                          AND (m.provider='spacemail' OR (m.provider='gmail' AND m.provider_message_id LIKE '%%@shodai.cc>'))''', (ids,)).fetchall()
                match, reason = select_match(candidates, item['manual_reply_address'], uid, item.get('in_reply_to'), references(item.get('message_references')))
            task = None
            if match and match.get('opportunity_id'):
                tasks = c.execute('SELECT id FROM sales_followups WHERE outbound_message_id=%s ORDER BY id', (match['id'],)).fetchall()
                task = tasks[0]['id'] if len(tasks) == 1 else None
            c.execute('''INSERT INTO official_mail_links(inbox_id,user_id,status,reason,opportunity_id,prospect_id,
                account_id,matched_outbound_id,followup_id,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(inbox_id) DO UPDATE SET status=excluded.status,reason=excluded.reason,
                    opportunity_id=excluded.opportunity_id,prospect_id=excluded.prospect_id,account_id=excluded.account_id,
                    matched_outbound_id=excluded.matched_outbound_id,followup_id=excluded.followup_id
                    WHERE official_mail_links.status='review' AND official_mail_links.reason='no_exact_thread'
                ''', (item['id'], uid, 'linked' if match else 'review', reason,
                    match.get('opportunity_id') if match else None, match.get('prospect_id') if match else None,
                    match.get('account_id') if match else None,
                    match['id'] if match else None, task, utcnow()))
            if match and match.get('prospect_id'):
                from app.prospect_outreach import ingest_reply
                ingest_reply(c, item, match)
            added += 1
    return added


def authorize(session, message):
    """Do not expose an admin-owned mailbox through the broader outbound pages."""
    if not message or (message.get('reply_inbox_id') is None and message.get('prospect_id') is None):
        return
    from app.fine_permissions import has_permission
    if (session.get('role') != 'admin' or not has_permission(session, 'manage_gmail')
            or session['user_id'] != message.get('mail_user_id')):
        raise HTTPException(403, 'Official mailbox access required')


def validate_reply(c, outbound, uid):
    item = c.execute('''SELECT i.*,l.status link_status,l.user_id link_user_id,
        l.opportunity_id,l.prospect_id,l.account_id,l.matched_outbound_id
        FROM spacemail_inbox i JOIN official_mail_links l ON l.inbox_id=i.id
        WHERE i.id=%s AND i.user_id=%s''', (outbound['reply_inbox_id'], uid)).fetchone()
    if (not item or item['link_status'] != 'linked' or item.get('link_user_id') != uid
            or bool(item.get('opportunity_id')) == bool(item.get('prospect_id'))
            or (item.get('prospect_id') and item.get('account_id') is not None)
            or not item.get('matched_outbound_id') or item.get('duplicate_of')
            or item.get('notice_kind') not in (None, 'none')
            or item.get('opportunity_id') != outbound.get('opportunity_id')
            or item.get('prospect_id') != outbound.get('prospect_id')
            or not address(item.get('manual_reply_address'))
            or item.get('manual_reply_address') != address(outbound.get('recipient'))
            or not message_id(item.get('message_id')) or outbound.get('mail_user_id') != uid):
        raise HTTPException(409, 'Official reply identity needs review')
    if item.get('prospect_id'):
        from app.prospect_outreach import ensure_reply_allowed
        prospect = ensure_reply_allowed(c, item['prospect_id'], uid)
        if (outbound.get('purpose') != 'official_reply'
                or prospect['recipient'] != item['manual_reply_address']):
            raise HTTPException(409, 'Official reply identity needs review')
    return item


def create_draft(inbox_id, session):
    from app.fine_permissions import has_permission
    if session.get('role') != 'admin' or not has_permission(session, 'manage_gmail') or not has_permission(session, 'send_email'):
        raise HTTPException(403)
    with db() as c:
        item = c.execute('''SELECT i.*,l.status link_status,l.user_id link_user_id,
            l.opportunity_id,l.prospect_id,l.account_id,l.matched_outbound_id FROM spacemail_inbox i
            JOIN official_mail_links l ON l.inbox_id=i.id WHERE i.id=%s AND i.user_id=%s FOR UPDATE OF i''',
            (inbox_id, session['user_id'])).fetchone()
        if not item:
            raise HTTPException(404)
        if (item['link_status'] != 'linked' or item.get('link_user_id') != session['user_id']
                or bool(item.get('opportunity_id')) == bool(item.get('prospect_id'))
                or (item.get('prospect_id') and item.get('account_id') is not None)
                or not item.get('matched_outbound_id') or item.get('duplicate_of')
                or item.get('notice_kind') not in (None, 'none')
                or not address(item.get('manual_reply_address')) or not message_id(item['message_id'])):
            raise HTTPException(409, 'Unmatched or ambiguous mail needs review; no reply draft created')
        if item.get('prospect_id'):
            from app.prospect_outreach import ensure_reply_allowed
            prospect = ensure_reply_allowed(c, item['prospect_id'], session['user_id'])
            if prospect['recipient'] != item['manual_reply_address']:
                raise HTTPException(409, 'Official reply identity needs review')
        existing = c.execute('SELECT * FROM outbound_messages WHERE reply_inbox_id=%s', (inbox_id,)).fetchone()
        if existing:
            authorize(session, existing)
            validate_reply(c, existing, session['user_id'])
            return existing['id']
        subject = item['subject'] or ('مراسلتكم مع آفاق طويق' if item.get('prospect_id') else 'طلبكم لدى آفاق طويق')
        subject = subject if subject.lower().startswith('re:') else 'Re: '+subject
        now = utcnow()
        row = c.execute('''INSERT INTO outbound_messages(opportunity_id,prospect_id,purpose,channel,recipient,subject,body,
            proposal_text,status,created_by,mail_user_id,reply_inbox_id,created_at,updated_at)
            VALUES(%s,%s,'official_reply','email',%s,%s,'','','draft',%s,%s,%s,%s,%s) RETURNING id''',
            (item.get('opportunity_id'), item.get('prospect_id'), item['manual_reply_address'], subject, session['user_id'],
             session['user_id'], inbox_id, now, now)).fetchone()
        c.execute('INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at) VALUES(%s,%s,%s,%s,%s,%s)',
            (session['user_id'], 'create_official_reply_draft', 'outbound_message', row['id'], 'Blank custom reply draft; not sent', now))
        return row['id']
