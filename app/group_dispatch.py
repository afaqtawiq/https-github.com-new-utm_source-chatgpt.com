"""Owner (23 Nov 2026): «المدير يتابع القروبات ويوزعها على الأقسام» — two declarations were posted in the Jeddah-port
group yesterday and nobody worked on them; Khaled should have priced the transport.

Every important group message (question / request / document) nobody from Afaq answered is taken by the general
manager after 3 minutes: he reads the attached PDFs, picks the department (transport → خالد, clearance → فيصل,
containers/line → سلطان, finance → نورة, otherwise خدمة العملاء), hands the request to that employee, and sends the
owner ONE bundled update with the employee's result. Nothing is ever posted in a group from here; any message to an
outside party still needs «نفذ».
"""
import asyncio
import datetime as dt
import json
import os
import re
import threading

import httpx

from app.storage import db, utcnow

WAIT_MINUTES = 3
_LOCK = threading.Lock()
ROUTES = [
    ('transport', re.compile(r'نقل|سطح|تريل|شاحن|دينا|لوري|سواق|سائق|توصيل|ترحيل|حمول|من الميناء الى|من الميناء إلى|truck|trailer|transport|delivery', re.I)),
    ('clearance', re.compile(r'بيان|بند|تعرف|فسح|سابر|تخليص|جمرك|رسوم|hs ?code|customs|declaration|saber|sfda|غذاء|دواء', re.I)),
    ('containers', re.compile(r'حاوي|بوليص|ميرسك|مسك|وكيل|ملاح|اذن تسليم|إذن تسليم|ارضيات|أرضيات|container|b/?l|bill of lading|maersk|msc|cosco|d/?o', re.I)),
    ('finance', re.compile(r'فاتور|سداد|كشف|حساب|تحويل|مبلغ|invoice|payment|statement', re.I)),
]
ASK = {
    'transport': ('اطلب أسعار نقل من السائقين المسجلين (أداة driver_price_request) لهذا الطلب، ثم أعطني أقل سعر وصل والسائق، '
                  'وإن لم تصل أسعار بعد فاذكر ما طلبته ومتى ترجع بالنتيجة. حدد نوع الشاحنة والمسار من المستندات.'),
    'clearance': 'راجع البيان/البند/الاشتراطات المطلوبة وأعطني النتيجة والخطوة التالية.',
    'containers': 'تحقق من البوليصة/الحاويات/الوكيل الملاحي ووصول الشحنة وأعطني النتيجة والخطوة التالية.',
    'finance': 'راجع المطلوب ماليًا (فاتورة/سداد/كشف) وأعطني النتيجة.',
    'service': 'افهم الطلب وأعطني الرد المقترح والخطوة التالية.',
}


def init():
    with db() as c:
        c.execute("ALTER TABLE whatsapp_group_messages ADD COLUMN IF NOT EXISTS dispatched_at TIMESTAMPTZ")
        c.execute("ALTER TABLE whatsapp_group_messages ADD COLUMN IF NOT EXISTS dispatch_dept TEXT")


def route(text):
    for key, rx in ROUTES:
        if rx.search(text or ''):
            return key
    return 'service'


def pending(now=None):
    """Bursts (same sender, same group) with an important unanswered message, older than WAIT_MINUTES, last 2 days."""
    now = now or utcnow()
    with db() as c:
        heads = c.execute('''SELECT * FROM whatsapp_group_messages WHERE important AND dispatched_at IS NULL
            AND received_at > %s AND received_at <= %s ORDER BY received_at LIMIT 6''',
                          (now - dt.timedelta(days=2), now - dt.timedelta(minutes=WAIT_MINUTES))).fetchall()
        out, seen = [], set()
        for h in heads:
            key = (h['conversation_id'], h['sender'])
            if key in seen:
                continue
            seen.add(key)
            burst = c.execute('''SELECT * FROM whatsapp_group_messages WHERE conversation_id=%s AND sender=%s AND direction='incoming'
                AND dispatched_at IS NULL AND received_at BETWEEN %s AND %s ORDER BY received_at''',
                              (h['conversation_id'], h['sender'], h['received_at'] - dt.timedelta(minutes=30),
                               h['received_at'] + dt.timedelta(minutes=30))).fetchall()
            out.append(burst)
        return out


def _read_pdfs(burst, limit=3):
    """Download the burst's attachments from the provider and read PDFs (same reader as the WhatsApp documents)."""
    from app import load_vision
    out = []
    key = os.getenv('ZERNIO_API_KEY', '')
    if not key:
        return out
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for m in burst:
            for i in range(min(int(m['media'] or 0), 3)):
                if len(out) >= limit:
                    return out
                try:
                    path = (f"https://zernio.com/api/v1/inbox/conversations/{m['conversation_id']}/messages/"
                            f"{m['message_id']}/attachments/{i}")
                    r = client.get(path, params={'accountId': m['account_id'], 'format': 'json'}, headers={'Authorization': 'Bearer ' + key})
                    r.raise_for_status()
                    url = r.json().get('url')
                    if not url or not str(url).startswith('https://'):
                        continue
                    data = client.get(url).content
                    if not data.startswith(b'%PDF'):
                        continue
                    fields = asyncio.run(load_vision.extract_pdf(data))
                    out.append({k: v for k, v in (fields or {}).items() if v not in (None, '', [], {})})
                except Exception as exc:
                    print('GROUP_DISPATCH_PDF', type(exc).__name__, str(exc)[:120], flush=True)
    return out


def dispatch(burst):
    from app import virtual_office
    head = burst[-1]
    group = head['group_name'] or 'قروب'
    who = head['sender_name'] or ('+' + head['sender'] if head['sender'] else 'عضو')
    text = ' '.join(' '.join(str(m['text']).split()) for m in burst if m['text'])[:1500]
    docs = _read_pdfs(burst) if any(m['media'] for m in burst) else []
    files = sum(int(m['media'] or 0) for m in burst)
    blob = text + ' ' + json.dumps(docs, ensure_ascii=False)
    key = route(blob)
    person = virtual_office.DEPARTMENTS[key].get('person') or key
    answered = all(m['answered_at'] is not None for m in burst)
    request = (f'طلب وصل في قروب «{group}» من {who}' + (' (رد عليه أحد من الفريق في القروب)' if answered else ' ولم يرد عليه أحد من آفاق')
               + f':\n«{text or "(مرفقات بدون نص)"}»'
               + (f'\nالمرفقات: {files}' if files else '')
               + (('\nما قرأته من المستندات:\n' + json.dumps(docs, ensure_ascii=False)[:2500]) if docs else '')
               + '\n\nالمطلوب منك: ' + ASK[key]
               + '\nلا ترسل أي شيء في القروب؛ أي رسالة لطرف خارجي تُجهّز برمز «نفذ» للمالك. ردك يصل للمالك عن طريق المدير.')
    try:
        reply = virtual_office.ask(key, request, 'المدير العام (متابعة القروبات)', manager=True, channel='قروب',
                                   chat=virtual_office.owner_chat())
    except Exception as exc:
        reply = 'تعذر الحصول على رد الموظف الآن (' + type(exc).__name__ + ').'
    with db() as c:
        c.execute('UPDATE whatsapp_group_messages SET dispatched_at=%s, dispatch_dept=%s WHERE id = ANY(%s)',
                  (utcnow(), key, [m['id'] for m in burst]))
    return (f'📥 قروب «{group}» — {who}: «{text[:300] or "مرفقات"}»' + (f' (+{files} مرفق)' if files else '')
            + f'\n➡️ وزّعته على {person}. النتيجة:\n{reply[:1500]}')


def run_round():
    """One pass (never two at once). Returns how many requests were handed to departments."""
    if os.getenv('GROUP_DISPATCH_ENABLED', '1') == '0' or not _LOCK.acquire(blocking=False):
        return 0
    try:
        init()
        n = 0
        from app import office_inbox
        for burst in pending():
            if office_inbox.runs_today() >= office_inbox.daily_cap():
                print('GROUP_DISPATCH_CAP', office_inbox.daily_cap(), flush=True)
                break
            unanswered = any(m['answered_at'] is None for m in burst)
            text = dispatch(burst)
            print('GROUP_DISPATCHED', burst[-1]['conversation_id'][:12], len(burst), unanswered, flush=True)
            # The owner hears about it when nobody from Afaq answered in the group or a «نفذ» code waits for him;
            # otherwise the work is in the department's history in the office.
            if unanswered or office_inbox.CODE.search(text):
                try:
                    from app.owner_briefing import deliver
                    asyncio.run(deliver(text))
                except Exception as exc:
                    print('GROUP_DISPATCH_DELIVER', type(exc).__name__, str(exc)[:120], flush=True)
            n += 1
        return n
    except Exception as exc:
        print('GROUP_DISPATCH', type(exc).__name__, str(exc)[:160], flush=True)
        return 0
    finally:
        _LOCK.release()


def kick():
    threading.Thread(target=run_round, daemon=True).start()
