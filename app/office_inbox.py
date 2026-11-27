"""Every piece of work that reaches the Afaq WhatsApp number goes to the virtual office (owner, 27 Nov 2026: «بما انو رقم
الجوال هذا والقروبات الفيها اصبحت مخصصة لافاق طويق انا عايز اي شغل يرد للواتساب يروح للمكتب الافتراضي ويشتغلو عليه»).

Private customer chats: after the customer agent has queued its own reply, the request (text that asks for something, or
a document / photo) is kept here; when the customer has been quiet for a few minutes the whole burst is handed to the
right department manager (transport → خالد, clearance → فيصل, containers → سلطان, finance → نورة, else خدمة العملاء),
who does the internal work with his tools and prepares the next reply. Nothing is sent to the customer from here: any
outside message still waits for «نفذ». The owner gets a WhatsApp update only when a «نفذ» code is waiting for him;
everything else is in the department's history in the office.
Groups are handled the same way by group_dispatch (now every request, answered or not).
OFFICE_INBOX_ENABLED=0 turns it off; OFFICE_INBOX_DAILY_CAP (default 60) caps the department runs per day.
"""
import asyncio
import datetime as dt
import json
import os
import re
import threading

from app.storage import db, utcnow

RIYADH = dt.timezone(dt.timedelta(hours=3))
QUIET_MINUTES = 3
CODE = re.compile(r'نفذ\s+[A-F0-9]{6}')
_LOCK = threading.Lock()
_READY = False


def enabled():
    return os.getenv('OFFICE_INBOX_ENABLED', '1') != '0'


def daily_cap():
    try:
        return max(0, int(os.getenv('OFFICE_INBOX_DAILY_CAP', '60')))
    except ValueError:
        return 60


def init():
    global _READY
    if _READY:
        return
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS office_inbox(id BIGSERIAL PRIMARY KEY, channel TEXT NOT NULL DEFAULT 'customer',
            account_id TEXT NOT NULL, conversation_id TEXT NOT NULL, message_id TEXT NOT NULL UNIQUE, sender TEXT NOT NULL DEFAULT '',
            sender_name TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '', media INTEGER NOT NULL DEFAULT 0,
            received_at TIMESTAMPTZ NOT NULL, dispatched_at TIMESTAMPTZ, dept TEXT, result TEXT)''')
        c.execute('CREATE INDEX IF NOT EXISTS office_inbox_open ON office_inbox(conversation_id, received_at) WHERE dispatched_at IS NULL')
    _READY = True


def keep(account_id, conversation_id, message_id, sender, sender_name, text, media, at=None):
    """Called from the customer intake (never raises). Only work: a request / question, or files."""
    try:
        if not enabled() or not conversation_id or not message_id:
            return False
        from app.group_watch import important
        if not important(text, media):
            return False
        init()
        with db() as c:
            row = c.execute('''INSERT INTO office_inbox(account_id,conversation_id,message_id,sender,sender_name,text,media,received_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(message_id) DO NOTHING RETURNING id''',
                            (account_id, conversation_id, str(message_id)[:255], re.sub(r'\D', '', str(sender or ''))[:20],
                             str(sender_name or '')[:120], str(text or '')[:4000], int(media or 0), at or utcnow())).fetchone()
        return bool(row)
    except Exception as exc:
        print('OFFICE_INBOX_KEEP', type(exc).__name__, str(exc)[:120], flush=True)
        return False


def pending(now=None):
    """Bursts (one conversation) whose last message is older than QUIET_MINUTES, last 2 days, not yet handed over."""
    now = now or utcnow()
    init()
    with db() as c:
        convs = c.execute('''SELECT conversation_id, MAX(received_at) last FROM office_inbox WHERE dispatched_at IS NULL
            AND received_at > %s GROUP BY conversation_id HAVING MAX(received_at) <= %s ORDER BY MIN(received_at) LIMIT 5''',
                          (now - dt.timedelta(days=2), now - dt.timedelta(minutes=QUIET_MINUTES))).fetchall()
        return [c.execute('''SELECT * FROM office_inbox WHERE conversation_id=%s AND dispatched_at IS NULL AND received_at > %s
            ORDER BY received_at''', (r['conversation_id'], now - dt.timedelta(days=2))).fetchall() for r in convs]


def runs_today():
    init()
    start = dt.datetime.combine(utcnow().astimezone(RIYADH).date(), dt.time(0), RIYADH)
    with db() as c:
        n = c.execute('SELECT COUNT(DISTINCT conversation_id || dept) n FROM office_inbox WHERE dispatched_at >= %s', (start,)).fetchone()['n']
        try:
            n += c.execute('''SELECT COUNT(DISTINCT conversation_id || sender) n FROM whatsapp_group_messages WHERE dispatched_at >= %s''',
                           (start,)).fetchone()['n']
        except Exception:
            pass
    return n


def _customer_line(burst):
    """Who the customer is for us: name / number / open shipment file, when known."""
    head = burst[-1]
    who = head['sender_name'] or ('+' + head['sender'] if head['sender'] else 'عميل')
    extra = ''
    try:
        from app import shipment_files
        files = shipment_files.find(head['sender'][-9:]) if head['sender'] else []
        if files:
            extra = f" — ملف شحنة مفتوح: {files[0].get('bill_no') or ''} ({files[0].get('customer') or ''})"
    except Exception:
        pass
    return who + (f" (+{head['sender']})" if head['sender'] and head['sender_name'] else '') + extra


def dispatch(burst):
    from app import group_dispatch, virtual_office
    text = ' '.join(' '.join(str(m['text']).split()) for m in burst if m['text'])[:1500]
    files = sum(int(m['media'] or 0) for m in burst)
    docs = group_dispatch._read_pdfs(burst) if files else []
    key = group_dispatch.route(text + ' ' + json.dumps(docs, ensure_ascii=False))
    person = virtual_office.DEPARTMENTS[key].get('person') or key
    who = _customer_line(burst)
    request = (f'رسالة عميل على واتساب آفاق من {who}:\n«{text or "(مرفقات بدون نص)"}»'
               + (f'\nالمرفقات: {files}' if files else '')
               + (('\nما قرأته من المستندات:\n' + json.dumps(docs, ensure_ascii=False)[:2500]) if docs else '')
               + '\n\nوكيل آفاق رد على العميل تلقائيًا. المطلوب منك الشغل الداخلي الحين: ' + group_dispatch.ASK[key]
               + '\nجهّز الرد التالي للعميل؛ أي رسالة له تُجهّز برمز «نفذ» للمالك ولا تُرسل بدون موافقته.')
    try:
        reply = virtual_office.ask(key, request, 'المدير العام (واتساب العملاء)', manager=True, channel='واتساب عميل',
                                   chat=virtual_office.owner_chat())
    except Exception as exc:
        reply = 'تعذر الحصول على رد الموظف الآن (' + type(exc).__name__ + ').'
    with db() as c:
        c.execute('UPDATE office_inbox SET dispatched_at=%s, dept=%s, result=%s WHERE id = ANY(%s)',
                  (utcnow(), key, reply[:4000], [m['id'] for m in burst]))
    note = (f'📥 عميل {who}: «{text[:300] or "مرفقات"}»' + (f' (+{files} مرفق)' if files else '')
            + f'\n➡️ اشتغل عليه {person}:\n{reply[:1500]}')
    return note, bool(CODE.search(reply))


def run_round():
    """One pass (never two at once). Returns how many conversations were handed to departments."""
    if not enabled() or not _LOCK.acquire(blocking=False):
        return 0
    try:
        n = 0
        for burst in pending():
            if runs_today() >= daily_cap():
                print('OFFICE_INBOX_CAP', daily_cap(), flush=True)
                break
            note, needs_owner = dispatch(burst)
            print('OFFICE_INBOX_DISPATCHED', burst[-1]['conversation_id'][:12], len(burst), needs_owner, flush=True)
            if needs_owner:
                try:
                    from app.owner_briefing import deliver
                    asyncio.run(deliver(note))
                except Exception as exc:
                    print('OFFICE_INBOX_DELIVER', type(exc).__name__, str(exc)[:120], flush=True)
            n += 1
        return n
    except Exception as exc:
        print('OFFICE_INBOX', type(exc).__name__, str(exc)[:160], flush=True)
        return 0
    finally:
        _LOCK.release()


def kick():
    threading.Thread(target=run_round, daemon=True).start()
