"""Carrier partners (owner plan 25 Nov 2026, step 3: «توقيع 5 ناقلين كشركاء»).

Transport companies in the carrier directory are partners, not customers. Khaled invites them — in the approved
template afaaq_transport_partner_rates_v1_ar, ONE «نفذ» for a batch of up to 20 — to send their truck types,
lanes and rates. A reply from an invited company is saved on the company (quote notes), the manager is told once,
and the customer agent answers it as a partner. Companies contacted by the daily outreach in the last 14 days,
or that declined, are never invited.
"""
import asyncio
import datetime as dt
import os
import re
import threading

from app.storage import db, utcnow

TEMPLATE = 'afaaq_transport_partner_rates_v1_ar'
BATCH = 20
REPLY_DAYS = 30
STOP = re.compile(r'^\s*(?:ايقاف|إيقاف|stop|unsubscribe|لا\s*ترسل)\s*$', re.I)


def body(company):
    return ('السلام عليكم {0}،\n'
            'معكم آفاق طويق للتخليص الجمركي والنقل في السعودية. نبحث عن شركاء نقل لحمولاتنا داخل المملكة وبين الخليج والسعودية، '
            'ونخلّص لشركائكم في المنافذ السعودية.\n'
            'إذا يناسبكم التعاون، أرسلوا لنا أنواع الشاحنات والمسارات اللي تخدمونها وأسعاركم.\n'
            'Afaq Tuwaiq (Saudi customs clearance & transport) is looking for trucking partners — please reply with your truck types, lanes and rates.\n'
            'للإيقاف اكتبوا: إيقاف').format(company)


def template_spec():
    return {'name': TEMPLATE, 'language': 'ar', 'category': 'MARKETING', 'components': [
        {'type': 'body', 'text': body('{{1}}'), 'example': {'body_text': [['مؤسسة الخليج للنقل']]}}]}


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS carrier_invites(carrier_id BIGINT PRIMARY KEY, phone TEXT NOT NULL,
            company TEXT NOT NULL, status TEXT NOT NULL, error TEXT, reply TEXT, sent_at TIMESTAMPTZ, replied_at TIMESTAMPTZ,
            created_by TEXT, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS carrier_partner_settings(id INTEGER PRIMARY KEY CHECK(id=1),
            template_status TEXT NOT NULL, checked_at TIMESTAMPTZ NOT NULL)''')


def template_status():
    init()
    with db() as c:
        row = c.execute('SELECT template_status FROM carrier_partner_settings WHERE id=1').fetchone()
    return row['template_status'] if row else 'UNKNOWN'


async def ensure_template():
    from app import zernio_whatsapp as wa
    async with wa.client() as c:
        await wa.validate_account(c)
        status = None
        for item in await wa.templates(c):
            if item.get('name') == TEMPLATE and item.get('language') == 'ar':
                status = str(item.get('status') or 'UNKNOWN')
        if status is None:
            result = await c.post(wa.BASE + '/whatsapp/templates', json={'accountId': wa.account_id(), **template_spec()})
            status = 'SUBMITTED' if result.is_success else 'CREATE_FAILED_' + str(result.status_code)
    init()
    with db() as c:
        c.execute('''INSERT INTO carrier_partner_settings(id,template_status,checked_at) VALUES(1,%s,%s)
            ON CONFLICT(id) DO UPDATE SET template_status=EXCLUDED.template_status, checked_at=EXCLUDED.checked_at''', (status, utcnow()))
    return status


def _digits(phone):
    d = re.sub(r'\D', '', str(phone or ''))
    if d.startswith('00'):
        d = d[2:]
    if d.startswith('05') and len(d) == 10:
        d = '966' + d[1:]
    return d if 11 <= len(d) <= 15 else ''


def candidates(limit=BATCH):
    """Directory carriers with a phone, never invited, not declined, not reached by the daily outreach in 14 days.
    Companies that contacted us first, then Saudi carriers (domestic lanes), then the rest."""
    init()
    with db() as c:
        if not c.execute("SELECT to_regclass('carrier_companies') t").fetchone()['t']:
            return []
        rows = c.execute('''SELECT k.id, k.company_name, k.phone, k.country, k.notes, k.capacity FROM carrier_companies k
            WHERE COALESCE(k.contact_consent,'unknown')<>'declined' AND COALESCE(k.phone,'')<>''
              AND NOT EXISTS (SELECT 1 FROM carrier_invites i WHERE i.carrier_id=k.id) ORDER BY k.id''').fetchall()
        recent = set()
        if c.execute("SELECT to_regclass('daily_prospects') t").fetchone()['t']:
            recent = {re.sub(r'\D', '', r['phone'])[-9:] for r in c.execute(
                "SELECT phone FROM daily_prospects WHERE phone<>'' AND updated_at > NOW() - INTERVAL '14 days' AND status<>'pending'").fetchall()}
        suppressed = set()
        if c.execute("SELECT to_regclass('marketing_suppressions') t").fetchone()['t']:
            suppressed = {re.sub(r'\D', '', r['recipient'])[-9:] for r in c.execute(
                "SELECT recipient FROM marketing_suppressions WHERE channel='whatsapp'").fetchall()}
    out, seen = [], set()
    for r in rows:
        phone = _digits(r['phone'])
        if not phone or phone[-9:] in recent or phone[-9:] in suppressed or phone in seen:
            continue
        seen.add(phone)
        first = 0 if 'واتساب' in str(r['notes'] or '') else 1 if r['country'] == 'SA' else 2
        out.append((first, r['id'], dict(r, phone=phone)))
    out.sort(key=lambda x: (x[0], x[1]))
    return [r for _, _, r in out[:limit]]


def preview(limit=BATCH):
    """(ids, text) — text says why nothing can be sent when ids is empty."""
    status = template_status()
    rows = candidates(limit)
    if not rows:
        return [], 'ما فيه شركات نقل جديدة بأرقام في دليل الناقلين (أو كلها تواصلنا معها). أضف شركات من /carriers أو اطلب من ريم البحث.'
    lines = [f'🤝 دعوة {len(rows)} شركة نقل للشراكة وإرسال أسعارها:']
    lines += [f"• {r['company_name']} (+{r['phone']})" + (f" — {r['capacity']}" if r.get('capacity') else '') for r in rows[:20]]
    lines += ['', 'الرسالة:', body('<اسم الشركة>')]
    if status != 'APPROVED':
        lines.append(f'\n⏳ قالب الدعوة بانتظار اعتماد ميتا (الحالة: {status}). ما أقدر أرسل قبل الاعتماد؛ أعد الطلب بعد ما يعتمد.')
        return [], '\n'.join(lines)
    return [r['id'] for r in rows], '\n'.join(lines)


def start(action, actor=''):
    if os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') != '1':
        return 'الإرسال الخارجي متوقف على الخادم؛ لم يُرسل شيء.'
    ids = [int(i) for i in action.get('ids') or []][:BATCH]
    if not ids:
        return 'ما فيه شركات في الطلب.'
    init()
    with db() as c:
        rows = c.execute('''SELECT id, company_name, phone FROM carrier_companies WHERE id = ANY(%s)
            AND COALESCE(contact_consent,'unknown')<>'declined' ''', (ids,)).fetchall()
        claimed = []
        rows = sorted(rows, key=lambda r: ids.index(r['id']))
        for r in rows:
            phone = _digits(r['phone'])
            if phone and c.execute('''INSERT INTO carrier_invites(carrier_id,phone,company,status,created_by,created_at)
                    VALUES(%s,%s,%s,'sending',%s,%s) ON CONFLICT DO NOTHING RETURNING carrier_id''',
                    (r['id'], phone, r['company_name'], actor, utcnow())).fetchone():
                claimed.append((r['id'], phone, r['company_name']))
    if not claimed:
        return 'كل الشركات في الطلب دُعيت مسبقًا؛ لم يُرسل شيء.'

    async def send_all():
        from app import zernio_whatsapp as z
        for cid, phone, name in claimed:
            status, error = 'sent', None
            try:
                await z.send('+' + phone, body(name))
            except Exception as exc:  # never retried automatically
                status, error = ('failed' if isinstance(exc, z.WhatsAppBlocked) else 'uncertain'), str(exc)[:200]
            with db() as c:
                c.execute('UPDATE carrier_invites SET status=%s,error=%s,sent_at=%s WHERE carrier_id=%s', (status, error, utcnow(), cid))
            await asyncio.sleep(float(os.getenv('LOAD_BROADCAST_DELAY', '1.2')))
        print('CARRIER_INVITES', len(claimed), flush=True)
    threading.Thread(target=lambda: asyncio.run(send_all()), daemon=True).start()
    return (f'✅ بدأ إرسال دعوة الشراكة لـ {len(claimed)} شركة نقل. أي رد يوصلك فورًا ويتسجل على الشركة؛ '
            'اكتب «حالة الناقلين الشركاء» لمتابعة الردود والأسعار.')


def on_reply(sender, text):
    """An invited company wrote back. Returns a manager notice the first time, else None; '' if not an invited company."""
    d = re.sub(r'\D', '', str(sender or ''))[-9:]
    if len(d) < 9:
        return ''
    try:
        init()
        with db() as c:
            inv = c.execute('''SELECT * FROM carrier_invites WHERE right(phone,9)=%s AND status IN ('sent','uncertain','replied')
                AND sent_at > %s''', (d, utcnow() - dt.timedelta(days=REPLY_DAYS))).fetchone()
            if not inv:
                return ''
            text = ' '.join(str(text or '').split())[:600]
            if STOP.match(text):
                c.execute("UPDATE carrier_companies SET contact_consent='declined', updated_at=%s WHERE id=%s", (utcnow(), inv['carrier_id']))
                c.execute("UPDATE carrier_invites SET status='declined', reply=%s, replied_at=%s WHERE carrier_id=%s", (text, utcnow(), inv['carrier_id']))
                return f'🚫 {inv["company"]} طلبت إيقاف رسائل الشراكة؛ أوقفتها.'
            first = inv['status'] != 'replied'
            c.execute("UPDATE carrier_invites SET status='replied', reply=COALESCE(reply || E'\\n','') || %s, replied_at=%s WHERE carrier_id=%s",
                      (text, utcnow(), inv['carrier_id']))
            c.execute("""UPDATE carrier_companies SET quote_notes=left(COALESCE(NULLIF(quote_notes,'') || E'\\n','') || %s, 4000),
                updated_at=%s WHERE id=%s""", (utcnow().strftime('%Y-%m-%d') + ': ' + text, utcnow(), inv['carrier_id']))
    except Exception as exc:
        print('CARRIER_PARTNER_REPLY', type(exc).__name__, str(exc)[:120], flush=True)
        return ''
    if not first:
        return None
    return (f'🤝 رد شريك نقل: {inv["company"]} (+{inv["phone"]})\n«{text[:400]}»\n'
            'سجلت الرد على الشركة في دليل الناقلين. خالد: إذا فيه أسعار، قارنها بجدول الأسعار (rate_card).')


def status_text(limit=15):
    init()
    with db() as c:
        counts = {r['status']: r['n'] for r in c.execute('SELECT status, COUNT(*) n FROM carrier_invites GROUP BY status').fetchall()}
        replies = c.execute("""SELECT company, phone, reply, replied_at FROM carrier_invites WHERE status='replied'
            ORDER BY replied_at DESC LIMIT %s""", (limit,)).fetchall()
    if not counts:
        return 'ما أرسلنا دعوات شراكة للناقلين بعد. اكتب «ادعُ شركات النقل للشراكة» لتجهيز دفعة. (حالة القالب: ' + template_status() + ')'
    lines = ['🤝 الناقلون الشركاء:',
             f"دُعيت {sum(counts.values())} — ردت {counts.get('replied', 0)} — أوقفت {counts.get('declined', 0)} — "
             f"تعذر {counts.get('failed', 0) + counts.get('uncertain', 0)}"]
    for r in replies:
        lines.append(f"• {r['company']} (+{r['phone']}): {str(r['reply'] or '')[-250:]}")
    return '\n'.join(lines)


def register_worker(app):
    async def loop():
        await asyncio.sleep(330)
        while True:
            try:
                print('CARRIER_PARTNER_TEMPLATE', await ensure_template(), flush=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('CARRIER_PARTNER_TEMPLATE', 'ERROR_' + type(exc).__name__, flush=True)
            await asyncio.sleep(6 * 3600)

    @app.on_event('startup')
    async def _start():
        app.state.carrier_partner_task = asyncio.create_task(loop())
