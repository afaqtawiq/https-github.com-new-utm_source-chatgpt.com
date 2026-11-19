"""Collaboration around the official mailbox (owner request, 19 Nov 2026: «لو المختص بالوكلاء عايز يرسل إيميل…»).

- Every email that leaves the official mailbox is logged with the office employee who prepared it, so دانة (email desk)
  sees all outgoing mail, not only her own.
- When an answer to one of those emails arrives, it is routed back: a note in that employee's office history (so the
  next conversation with him knows it) and a short WhatsApp note to the owner. Nothing is sent outside the company.
"""
import contextvars
import re

from app.storage import db, utcnow

# (department key, person) of the office employee whose prepared email is being sent right now.
MAIL_FROM = contextvars.ContextVar('afaq_mail_from', default=None)
_READY = False


def init():
    global _READY
    if _READY:
        return
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS office_mail_log(id BIGSERIAL PRIMARY KEY, department TEXT NOT NULL DEFAULT '',
            person TEXT NOT NULL DEFAULT '', recipient TEXT NOT NULL, subject TEXT NOT NULL DEFAULT '', message_id TEXT,
            created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS office_mail_log_mid ON office_mail_log(message_id)')
        c.execute('''CREATE TABLE IF NOT EXISTS office_mail_routed(inbox_id BIGINT PRIMARY KEY, log_id BIGINT NOT NULL,
            department TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL)''')
    _READY = True


def record(recipient, subject, message_id):
    """Called by spacemail.send after a successful send. Never raises."""
    try:
        from app import spacemail
        if str(recipient or '').strip().lower() == spacemail.ADDRESS:
            return
        init()
        dept, person = MAIL_FROM.get() or ('', '')
        with db() as c:
            c.execute('''INSERT INTO office_mail_log(department,person,recipient,subject,message_id,created_at)
                VALUES(%s,%s,%s,%s,%s,%s)''', (dept, person, str(recipient)[:300], str(subject or '')[:300],
                                             str(message_id or '').strip()[:300] or None, utcnow()))
    except Exception as exc:
        print('OFFICE_MAIL_LOG', type(exc).__name__, str(exc)[:120], flush=True)


def sent(c, days=7, limit=12):
    init()
    rows = c.execute('''SELECT l.*, (SELECT COUNT(*) FROM office_mail_routed r WHERE r.log_id=l.id) replies
        FROM office_mail_log l WHERE l.created_at > NOW() - make_interval(days => %s) ORDER BY l.id DESC LIMIT %s''',
                     (int(days), int(limit))).fetchall()
    if not rows:
        return f'📤 لم يخرج بريد من البريد الرسمي خلال آخر {days} أيام.'
    out = [f'📤 البريد الصادر (آخر {days} أيام):']
    for r in rows:
        who = r['person'] or 'المنصة'
        out.append(f"• {r['created_at']:%d/%m %H:%M} — {who} → {r['recipient']}: {r['subject'][:80]}"
                   + (f" — ↩️ وصل رد ({r['replies']})" if r['replies'] else ' — بانتظار رد'))
    return '\n'.join(out)


def _ids(text):
    return [x.strip() for x in re.findall(r'<[^<>\s]+>', str(text or ''))]


def route_replies(deliver=None):
    """Match new incoming mail to logged outgoing mail by In-Reply-To / References; returns how many were routed."""
    from app import virtual_office
    init()
    with db() as c:
        if not c.execute("SELECT to_regclass('spacemail_inbox') t").fetchone()['t']:
            return 0
        rows = c.execute('''SELECT i.id, i.sender, i.subject, i.body, i.in_reply_to, i.message_references FROM spacemail_inbox i
            WHERE i.imported_at > NOW() - INTERVAL '7 days' AND i.duplicate_of IS NULL
              AND NOT EXISTS(SELECT 1 FROM office_mail_routed r WHERE r.inbox_id=i.id)
              AND (COALESCE(i.in_reply_to,'')<>'' OR COALESCE(i.message_references,'')<>'') ORDER BY i.id LIMIT 30''').fetchall()
    routed = 0
    for row in rows:
        ids = _ids(row['in_reply_to']) + _ids(row['message_references'])
        if not ids:
            continue
        with db() as c:
            log = c.execute('''SELECT * FROM office_mail_log WHERE message_id = ANY(%s) ORDER BY id DESC LIMIT 1''', (ids,)).fetchone()
            if not log:
                continue
            claimed = c.execute('''INSERT INTO office_mail_routed(inbox_id,log_id,department,created_at) VALUES(%s,%s,%s,%s)
                ON CONFLICT DO NOTHING RETURNING inbox_id''', (row['id'], log['id'], log['department'], utcnow())).fetchone()
        if not claimed:
            continue
        routed += 1
        preview = re.sub(r'\s+', ' ', row['body'] or '').strip()[:500]
        key = log['department'] if log['department'] in virtual_office.DEPARTMENTS else 'email'
        person = virtual_office.DEPARTMENTS[key].get('person', '')
        virtual_office.log(key, 'بريد', row['sender'] or '', f"↩️ رد وارد على إيميلك «{log['subject'][:120]}» (رسالة #{row['id']})",
                           f'نص الرد: {preview}')
        note = (f"📨 وصل رد من {row['sender']} على إيميل {log['person'] or 'المنصة'} «{log['subject'][:90]}»\n{preview[:300]}\n"
                f"حوّلته لـ{person}. التفاصيل: «دانة: افتحي الرسالة #{row['id']}».")
        try:
            if deliver is None:
                from app.owner_briefing import deliver as wa
                from app.transport_desk import run_async
                run_async(lambda: wa(note), timeout=60)
            else:
                deliver(note)
        except Exception as exc:
            print('OFFICE_MAIL_ROUTE_NOTE', type(exc).__name__, str(exc)[:120], flush=True)
    return routed
