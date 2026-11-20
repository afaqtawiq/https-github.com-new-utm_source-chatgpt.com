"""Owner-requested (20 Nov 2026): Noura follows up the collection of an issued invoice on WhatsApp with the person
responsible for paying it. Each reminder is prepared with a «نفذ» code (nothing is sent without the owner), sent in the
exact text of the approved UTILITY template (reaches the payer outside the 24h window), and logged. Open invoices whose
last reminder is ≥ REMIND_DAYS old are listed to the owner each morning so the next reminder is one approval away.
"""
import asyncio
import datetime as dt
import os
import re

from app.storage import db, utcnow

TEMPLATE = 'afaaq_transport_payment_reminder_v1_ar'
REMIND_DAYS = int(os.getenv('COLLECTION_REMIND_DAYS', '3'))
RIYADH = dt.timezone(dt.timedelta(hours=3))
_READY = False


def body(name, number, date, amount):
    return (f'السلام عليكم {name}،\n'
            f'نذكّركم بفاتورة آفاق طويق للتخليص الجمركي رقم {number} بتاريخ {date} بمبلغ {amount} ريال.\n'
            'نأمل التكرم بالسداد، ويسعدنا تزويدكم بنسخة الفاتورة وبيانات الحساب البنكي أو كشف الحساب عند الطلب.\n'
            'للاستفسار ردّوا على هذه الرسالة أو اتصلوا على 0507665873.')


def template_spec():
    return {'name': TEMPLATE, 'language': 'ar', 'category': 'UTILITY', 'components': [
        {'type': 'body', 'text': body('{{1}}', '{{2}}', '{{3}}', '{{4}}'),
         'example': {'body_text': [['مؤسسة المثال', '3613', '2026-10-27', '7,131.55']]}}]}


async def ensure_template():
    from app import zernio_whatsapp as wa
    async with wa.client() as c:
        await wa.validate_account(c)
        for item in await wa.templates(c):
            if item.get('name') == TEMPLATE and item.get('language') == 'ar':
                return str(item.get('status') or 'UNKNOWN')
        result = await c.post(wa.BASE + '/whatsapp/templates', json={'accountId': wa.account_id(), **template_spec()})
        return 'SUBMITTED' if result.is_success else 'CREATE_FAILED_' + str(result.status_code)


def init():
    global _READY
    if _READY:
        return
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS invoice_collections(id BIGSERIAL PRIMARY KEY, invoice_no TEXT NOT NULL UNIQUE,
            customer TEXT NOT NULL, contact_name TEXT, phone TEXT NOT NULL, amount NUMERIC(14,2) NOT NULL, invoice_date DATE,
            status TEXT NOT NULL DEFAULT 'open', reminders INTEGER NOT NULL DEFAULT 0, last_sent_at TIMESTAMPTZ,
            paid_at TIMESTAMPTZ, notes TEXT, created_at TIMESTAMPTZ NOT NULL)''')
    _READY = True


def phone_digits(value):
    from app.customer_care import digits
    return digits(value)


def _money(value):
    text = str(value or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩٫٬', '0123456789.,')).replace(',', '')
    m = re.search(r'\d+(?:\.\d+)?', text)
    return float(m.group(0)) if m else 0.0


def message(row):
    name = row.get('contact_name') or row['customer']
    date = row['invoice_date'].isoformat() if row.get('invoice_date') else '-'
    return body(name, row['invoice_no'], date, f"{float(row['amount']):,.2f}")


def add(invoice_no, customer, amount, phone, contact_name='', invoice_date=None, notes=''):
    """Register (or update) the invoice to follow. Returns the row."""
    init()
    number = re.sub(r'[^\w-]', '', str(invoice_no or ''))[:40]
    phone = phone_digits(phone)
    value = _money(amount)
    if not number or not phone or value <= 0 or len(str(customer or '').strip()) < 2:
        raise ValueError('ناقص: رقم الفاتورة، اسم العميل، المبلغ، ورقم جوال المسؤول عن السداد.')
    try:
        date = dt.date.fromisoformat(str(invoice_date)[:10]) if invoice_date else None
    except ValueError:
        date = None
    with db() as c:
        return c.execute('''INSERT INTO invoice_collections(invoice_no,customer,contact_name,phone,amount,invoice_date,notes,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(invoice_no) DO UPDATE SET customer=EXCLUDED.customer,
            contact_name=COALESCE(NULLIF(EXCLUDED.contact_name,''),invoice_collections.contact_name), phone=EXCLUDED.phone,
            amount=EXCLUDED.amount, invoice_date=COALESCE(EXCLUDED.invoice_date,invoice_collections.invoice_date),
            notes=COALESCE(NULLIF(EXCLUDED.notes,''),invoice_collections.notes) RETURNING *''',
                         (number, ' '.join(str(customer).split())[:200], ' '.join(str(contact_name or '').split())[:80], phone,
                          value, date, str(notes or '')[:300], utcnow())).fetchone()


def get(invoice_no):
    init()
    with db() as c:
        return c.execute('SELECT * FROM invoice_collections WHERE invoice_no=%s', (re.sub(r'[^\w-]', '', str(invoice_no or '')),)).fetchone()


def send(invoice_no):
    """After «نفذ»: send the reminder (template text) and log it."""
    row = get(invoice_no)
    if not row:
        return 'الفاتورة غير مسجلة للمتابعة؛ لم يُرسل شيء.'
    if row['status'] != 'open':
        return f"الفاتورة {row['invoice_no']} مسددة/مغلقة؛ لم يُرسل شيء."
    import threading
    from contextvars import copy_context
    from app import zernio_whatsapp as z
    box = {}

    def run():
        try:
            box['result'] = asyncio.run(z.send(row['phone'], message(row)))
        except Exception as error:
            box['error'] = error
    worker = threading.Thread(target=copy_context().run, args=(run,))
    worker.start()
    worker.join(60)
    if 'error' in box:
        return f"تعذر إرسال التذكير: {str(box['error'])[:200]}"
    if 'result' not in box:
        return 'لم يتأكد إرسال التذكير خلال دقيقة؛ راجع المحادثة قبل إعادة المحاولة.'
    with db() as c:
        c.execute('UPDATE invoice_collections SET reminders=reminders+1,last_sent_at=%s WHERE id=%s', (utcnow(), row['id']))
    return (f"✅ أُرسل تذكير الفاتورة {row['invoice_no']} ({float(row['amount']):,.2f} ريال) إلى "
            f"{row.get('contact_name') or row['customer']} (+{row['phone']}). أتابعها وأذكّرك بعد {REMIND_DAYS} أيام إن لم تُسدد.")


def mark_paid(invoice_no):
    init()
    with db() as c:
        row = c.execute("UPDATE invoice_collections SET status='paid',paid_at=%s WHERE invoice_no=%s RETURNING *",
                        (utcnow(), re.sub(r'[^\w-]', '', str(invoice_no or '')))).fetchone()
    return (f"✅ أغلقت متابعة الفاتورة {row['invoice_no']} كمسددة. لا تنسَ تسجيل القبض (record_payment) ليُخصم من الرصيد."
            if row else 'لم أجد الفاتورة في المتابعة.')


def open_text():
    init()
    with db() as c:
        rows = c.execute("SELECT * FROM invoice_collections WHERE status='open' ORDER BY invoice_date NULLS LAST, id").fetchall()
    if not rows:
        return 'لا توجد فواتير تحت المتابعة.'
    today = dt.datetime.now(RIYADH).date()
    lines = []
    for r in rows:
        age = (today - r['invoice_date']).days if r.get('invoice_date') else None
        last = r['last_sent_at'].astimezone(RIYADH).strftime('%Y-%m-%d') if r.get('last_sent_at') else 'لم يُرسل'
        lines.append(f"• {r['invoice_no']} — {r['customer']}: {float(r['amount']):,.2f} ريال"
                     + (f' (عمرها {age} يوم)' if age is not None else '') + f" — تذكيرات {r['reminders']} (آخرها {last})")
    return 'فواتير تحت متابعة التحصيل:\n' + '\n'.join(lines)


def due_text():
    """Morning list for the owner: open invoices whose last reminder is ≥ REMIND_DAYS old."""
    init()
    with db() as c:
        rows = c.execute("""SELECT * FROM invoice_collections WHERE status='open' AND last_sent_at IS NOT NULL
            AND last_sent_at <= now() - (%s || ' days')::interval ORDER BY last_sent_at""", (str(REMIND_DAYS),)).fetchall()
    if not rows:
        return ''
    return ('💰 نورة: فواتير ما زالت بلا سداد بعد آخر تذكير — اكتب لنورة «ذكّر بالفاتورة <رقم>» لتجهيز التذكير التالي:\n'
            + '\n'.join(f"• {r['invoice_no']} — {r['customer']}: {float(r['amount']):,.2f} ريال (تذكيرات {r['reminders']})" for r in rows))


def register_worker(app):
    async def loop():
        from starlette.concurrency import run_in_threadpool
        from app.owner_briefing import deliver
        await asyncio.sleep(330)
        try:
            print('PAYMENT_REMINDER_TEMPLATE', await ensure_template(), flush=True)
        except Exception as exc:
            print('PAYMENT_REMINDER_TEMPLATE', 'ERROR_' + type(exc).__name__, flush=True)
        sent_day = None
        while True:
            try:
                now = dt.datetime.now(RIYADH)
                if now.hour == 9 and sent_day != now.date():
                    sent_day = now.date()
                    text = await run_in_threadpool(due_text)
                    if text:
                        await deliver(text)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('COLLECTION_WORKER', type(exc).__name__, str(exc)[:160], flush=True)
            await asyncio.sleep(600)

    @app.on_event('startup')
    async def start():
        app.state.collection_worker = asyncio.create_task(loop())
