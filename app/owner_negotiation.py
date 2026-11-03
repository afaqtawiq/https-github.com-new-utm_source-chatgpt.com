"""Natural WhatsApp conversation with a load owner (owner-requested, Nov 2026).

1. The manager sends the owner's number (+ route) on WhatsApp -> confirms with «نفذ CODE» -> the agent opens
   the conversation (approved template text when outside the 24h window).
2. The owner's replies are answered naturally by Claude to collect: goods, weight, loading point (inside/outside
   port), unloading point, payment method, price. The agent never accepts or rejects a price and never commits.
3. When complete, the owner gets a short summary to confirm, and the manager receives the summary.
4. The manager approves with a commission he chooses («اعتمد الحمولة N عمولة 300») -> the load is offered to all
   drivers at owner price - commission (load_broadcast).
"""
import json
import os
import re

import httpx

from app.storage import db, utcnow

FIELDS = {'origin': 'التحميل من', 'loading_point': 'موقع التحميل (داخل/خارج الميناء)', 'destination': 'إلى',
          'unloading': 'موقع التنزيل', 'goods': 'نوع البضاعة', 'weight': 'الوزن (طن)', 'payment': 'طريقة الدفع',
          'price': 'السعر المطلوب (ريال)', 'loading_date': 'موعد التحميل'}
REQUIRED = ('origin', 'destination', 'weight', 'payment', 'price', 'loading_point')

SYSTEM = """أنت موظف تنسيق نقل في «آفاق طويق للتخليص الجمركي والنقل» تتكلم على واتساب مع صاحب حمولة.
هدفك جمع تفاصيل الحمولة بطريقة طبيعية وودية جدًا وباللهجة السعودية المهذبة، رسالة قصيرة في كل مرة، وسؤال أو سؤالين فقط في كل رد،
ولا تعيد سؤالًا أجاب عنه. المعلومات المطلوبة: مدينة/موقع التحميل وهل التحميل داخل الميناء أم خارجه، الوجهة وموقع التنزيل،
نوع البضاعة، الوزن بالطن، طريقة الدفع، السعر المطلوب، وموعد التحميل إن أمكن.
قواعد صارمة: لا تقبل السعر ولا ترفضه ولا تفاوض بأرقام من عندك ولا تعد بسائق أو موعد؛ إذا سأل عن السعر أو طلب رأيك قل إنك ستعرض
التفاصيل على الإدارة وتعود له. لا تطلب بيانات بنكية. لا تذكر أنك ذكاء اصطناعي إلا إذا سُئلت.
إذا وصلتك بيانات «من إعلان الحمولة في نقليات» فاذكرها له واطلب تأكيدها أو تصحيحها بدل أن تسأل عنها من جديد.
عندما تكتمل المعلومات أرسل له ملخصًا قصيرًا واطلب منه تأكيده بكلمة «تمام».
أرجع JSON فقط بالشكل: {"reply": "نص الرسالة للعميل", "fields": {...المعروف حتى الآن بالمفاتيح: origin, loading_point, destination,
unloading, goods, weight, payment, price, loading_date}, "complete": true/false, "owner_confirmed": true/false}
complete=true فقط إذا توفرت: origin, destination, weight, payment, price, loading_point. owner_confirmed=true فقط إذا أكد صاحب
الحمولة الملخص صراحة."""


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS owner_negotiations(
            id BIGSERIAL PRIMARY KEY, phone TEXT NOT NULL, status TEXT NOT NULL, fields TEXT NOT NULL DEFAULT '{}',
            commission TEXT, broadcast_id BIGINT, created_by TEXT, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)''')
        c.execute('ALTER TABLE owner_negotiations ADD COLUMN IF NOT EXISTS naqliat_load_id BIGINT')
        c.execute("CREATE INDEX IF NOT EXISTS owner_negotiations_phone ON owner_negotiations(phone) WHERE status IN ('open','complete','confirmed')")


def digits(phone):
    d = re.sub(r'\D', '', str(phone or ''))
    if d.startswith('05') and len(d) == 10:
        d = '966' + d[1:]
    return d


def active(phone):
    d = digits(phone)
    if len(d) < 9:
        return None
    init()
    with db() as c:
        return c.execute("""SELECT * FROM owner_negotiations WHERE right(phone,9)=%s AND status IN ('open','complete','confirmed')
            ORDER BY id DESC LIMIT 1""", (d[-9:],)).fetchone()


def summary(fields):
    fields = {k: v for k, v in (fields or {}).items() if not k.startswith('_')}
    return '\n'.join('• ' + label + ': ' + str(fields.get(key)) for key, label in FIELDS.items() if fields.get(key))


async def opening(phone, origin, destination):
    """Try the approved owner-inquiry templates (v4, v3 short, v2) — the first approved match is sent."""
    from app import zernio_whatsapp as z
    from app.transport_owner import inquiry, legacy_v2_inquiry, short_inquiry
    last = None
    for build in (inquiry, short_inquiry, legacy_v2_inquiry):
        try:
            await z.send(phone, build(origin, destination))
            return
        except z.WhatsAppBlocked as exc:
            last = exc
            if 'قالب' not in str(exc):
                raise
    raise last


def start(action, actor):
    """Executed after the manager's confirmation code. Sends the opening message and reports the real result."""
    import asyncio
    import threading
    init()
    phone = digits(action.get('phone'))
    if str(action.get('origin') or '').strip() in ('', 'غير محدد') or str(action.get('destination') or '').strip() in ('', 'غير محدد'):
        return 'مسار الحمولة غير معروف (من/إلى)؛ لم أرسل شيئًا لصاحب الحمولة. أرسل لقطة الحمولة أو اكتب المسار.'
    fields = {'origin': action.get('origin') or '', 'destination': action.get('destination') or ''}
    load_id = action.get('load_id')
    with db() as c:
        if load_id:
            from app import transport_desk
            load = transport_desk.load_row(c, load_id)
            if load:
                fields['_listing'] = transport_desk.listing(load)
        nid = c.execute('''INSERT INTO owner_negotiations(phone,status,fields,created_by,created_at,updated_at,naqliat_load_id)
            VALUES(%s,'open',%s,%s,%s,%s,%s) RETURNING id''', (phone, json.dumps(fields, ensure_ascii=False), actor, utcnow(), utcnow(),
                                                              int(load_id) if load_id else None)).fetchone()['id']
    outcome = {}

    def run():
        try:
            asyncio.run(opening(phone, fields['origin'], fields['destination']))
            outcome['ok'] = True
        except Exception as exc:
            outcome['error'] = str(exc)[:200]
            print('OWNER_NEGOTIATION_OPEN_FAILED', nid, type(exc).__name__, str(exc)[:160], flush=True)
            with db() as c:
                c.execute("UPDATE owner_negotiations SET status='open_failed',updated_at=%s WHERE id=%s", (utcnow(), nid))
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(45)
    if outcome.get('ok'):
        if load_id:
            with db() as c:
                c.execute("UPDATE naqliat_loads SET status='contacted' WHERE id=%s", (int(load_id),))
        return (f'✅ أرسلت رسالة الاستفسار لصاحب الحمولة (+{phone}) — ملف رقم {nid}. سأكمل معه بشكل طبيعي وأرسل لك الملخص '
                'للاعتماد. لن أقبل أو أرفض أي سعر.')
    if 'error' in outcome:
        return (f'❌ لم تصل رسالة الافتتاح لصاحب الحمولة (+{phone}): {outcome["error"]}\n'
                'اكتب «حالة القوالب» لأعرض لك اعتماد القوالب في Meta.\n'
                'السبب غالبًا أن قوالب «استفسار الحمولة» غير معتمدة في Meta لهذا الرقم. الحل المؤقت: ابدأ أنت المحادثة معه '
                'من رقم الوكيل (أو يراسلنا هو)، ثم أعد الأمر وسأكمل التفاوض داخل نافذة الـ24 ساعة.')
    return f'⏳ جارٍ إرسال رسالة الافتتاح لصاحب الحمولة (+{phone}) — ملف {nid}.'


async def notify_manager(text):
    from app.owner_briefing import deliver
    await deliver(text)


async def reply(phone, message, history):
    """Answer an active owner conversation. Returns text or None (no active negotiation / failure)."""
    row = active(phone)
    if not row:
        return None
    key = os.getenv('ANTHROPIC_API_KEY', '').strip()
    from app.whatsapp_natural import model
    if not key:
        return None
    fields = json.loads(row['fields'] or '{}')
    msgs = []
    for entry in list(history or ())[-8:]:
        q, a = str((entry or {}).get('question') or ''), str((entry or {}).get('reply') or (entry or {}).get('reply_text') or '')
        if q and a:
            msgs += [{'role': 'user', 'content': q[:1500]}, {'role': 'assistant', 'content': a[:1500]}]
    known = {k: v for k, v in fields.items() if not k.startswith('_')}
    seen = fields.get('_listing') or {}
    hint = ('\nمن إعلان الحمولة في نقليات (اطلب تأكيده فقط ولا تعتبره مؤكدًا): ' + json.dumps(seen, ensure_ascii=False)) if seen else ''
    msgs.append({'role': 'user', 'content': 'المعروف حتى الآن: ' + json.dumps(known, ensure_ascii=False) + hint + '\nرسالة صاحب الحمولة: ' + str(message)[:2000]})
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post('https://api.anthropic.com/v1/messages', json={'model': model(), 'max_tokens': 800, 'system': SYSTEM, 'messages': msgs},
                                  headers={'x-api-key': key, 'anthropic-version': '2023-06-01'})
        text = ''.join(p.get('text', '') for p in r.json().get('content', []) if p.get('type') == 'text')
        data = json.loads(re.search(r'\{.*\}', text, re.S).group(0))
    except Exception as exc:
        print('OWNER_NEGOTIATION_MODEL', type(exc).__name__, flush=True)
        return None
    new = {k: v for k, v in (data.get('fields') or {}).items() if k in FIELDS and v not in (None, '', 'null')}
    fields.update(new)
    complete = all(fields.get(k) for k in REQUIRED)
    status = 'confirmed' if complete and data.get('owner_confirmed') else ('complete' if complete else 'open')
    with db() as c:
        c.execute('UPDATE owner_negotiations SET fields=%s,status=%s,updated_at=%s WHERE id=%s',
                  (json.dumps(fields, ensure_ascii=False), status, utcnow(), row['id']))
    if status == 'confirmed' and row['status'] != 'confirmed':
        await notify_manager(f"📦 حمولة جاهزة للاعتماد — ملف {row['id']} (صاحب الحمولة +{row['phone']})\n" + summary(fields)
                             + f"\nللإرسال للسائقين اكتب: اعتمد الحمولة {row['id']} عمولة <المبلغ>")
    out = str(data.get('reply') or '').strip()
    return out[:1200] or None


def approve(nid, commission, actor_name=''):
    """Manager approval: driver price = owner price - commission chosen now; offer to all drivers."""
    from app import load_broadcast
    init()
    with db() as c:
        row = c.execute('SELECT * FROM owner_negotiations WHERE id=%s', (int(re.sub(r'\D', '', str(nid)) or 0),)).fetchone()
    if not row:
        return 'لا يوجد ملف حمولة بهذا الرقم.'
    if row['status'] not in ('complete', 'confirmed'):
        return 'تفاصيل الحمولة لم تكتمل بعد؛ ما زلت أجمعها من صاحب الحمولة.\n' + summary(json.loads(row['fields'] or '{}'))
    fields = json.loads(row['fields'] or '{}')
    try:
        price = float(re.sub(r'[^\d.]', '', str(fields.get('price'))))
        cut = float(re.sub(r'[^\d.]', '', str(commission)))
    except ValueError:
        return 'السعر أو العمولة غير واضحين؛ لم يُرسل شيء.'
    if cut < 0 or cut >= price:
        return 'العمولة يجب أن تكون أقل من سعر صاحب الحمولة.'
    weight = re.sub(r'[^\d.]', '', str(fields.get('weight'))) or str(fields.get('weight'))
    origin = str(fields.get('origin')) + (' (' + str(fields['loading_point']) + ')' if fields.get('loading_point') else '')
    result = load_broadcast.start({'origin': origin, 'destination': fields.get('destination'), 'weight': weight,
                                   'driver_price': price - cut, 'unloading': fields.get('unloading') or fields.get('destination'),
                                   'payment': fields.get('payment'), 'negotiation_id': row['id']}, actor_name)
    with db() as c:
        c.execute("UPDATE owner_negotiations SET status='approved',commission=%s,updated_at=%s WHERE id=%s", (str(cut), utcnow(), row['id']))
    return f'اعتمدت ملف {row["id"]}: سعر صاحب الحمولة {price:,.0f} − عمولة {cut:,.0f} = سعر السائق {price - cut:,.0f} ريال.\n' + result
