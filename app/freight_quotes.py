"""سلطان — دليل وكلاء الملاحة وطلبات عروض أسعار الشحن (طلب المالك، 26 نوفمبر 2026):
«سلطان مدير الحاويات والملاحة ما عندو بيانات وكلاء الملاحة مع انها كلها مسجلة في الوكيل».

الدليل نفسه في shipping_agents / shipping_agent_contacts (صفحة «وكلاء الملاحة»)؛ هذه الوحدة تعطي سلطان:
- عرض الدليل كاملًا أو بالبحث (الوكيل، جهات التواصل، البريد والهاتف).
- تجهيز طلب عرض سعر شحن لعدة وكلاء دفعة واحدة؛ لا يُرسل شيء إلا بعد «نفذ» من المدير، ومن البريد الرسمي.
"""
import json
import re

from app.storage import db, utcnow

# أولوية جهة التواصل لطلب عرض سعر (الأقرب للمبيعات والحجز أولًا)
QUOTE_PURPOSES = ('sales', 'booking', 'export', 'quotation', 'rate', 'customer service', 'customer support', 'general',
                  'contact', 'operations', 'import')
MAX_BATCH = 15
SIZES = {'20': "20' DV", '40': "40' DV", '40hc': "40' HC", '45': "45' HC"}


def _rows(query=''):
    with db() as c:
        if not c.execute("SELECT to_regclass('shipping_agents') t").fetchone()['t']:
            return []
        agents = c.execute("SELECT id, name, website, port FROM shipping_agents WHERE status='active' ORDER BY name").fetchall()
        contacts = c.execute("""SELECT agent_id, purpose, email, phone, contact_name FROM shipping_agent_contacts
            WHERE status='active' ORDER BY id""").fetchall()
    by_agent = {}
    for r in contacts:
        by_agent.setdefault(r['agent_id'], []).append(r)
    q = str(query or '').strip().casefold()
    out = []
    for a in agents:
        items = by_agent.get(a['id'], [])
        hay = ' '.join([a['name']] + [str(x['email'] or '') + ' ' + str(x['purpose'] or '') for x in items]).casefold()
        if q and q not in hay:
            continue
        out.append(dict(a, contacts=items))
    return out


def directory_text(query=''):
    agents = _rows(query)
    if not agents:
        return ('ما لقيت وكيلًا بهذا الاسم في دليل وكلاء الملاحة.' if query else
                'دليل وكلاء الملاحة فارغ في النظام؛ افتح صفحة «وكلاء الملاحة» مرة واحدة لتحميله.')
    if not query and len(agents) > 12:
        return (f'🚢 دليل وكلاء الملاحة في جدة: {len(agents)} وكيلًا مسجلًا.\n'
                + '، '.join(a['name'] for a in agents)
                + '\n\nاكتب اسم الوكيل لعرض جهات تواصله، مثل: «بيانات وكيل MSC».')
    lines = [f'🚢 دليل وكلاء الملاحة ({len(agents)}):']
    for a in agents[:12]:
        lines.append(f"\n• {a['name']}" + (f" — {a['website']}" if a.get('website') else ''))
        for x in a['contacts'][:8]:
            bits = [x['email'] or '', x['phone'] or '', x['contact_name'] or '']
            lines.append(f"   - {x['purpose']}: " + ' | '.join(b for b in bits if b))
    return '\n'.join(lines)


def quote_contact(contacts):
    with_mail = [x for x in contacts if x.get('email')]
    for key in QUOTE_PURPOSES:
        for x in with_mail:
            if key in str(x['purpose'] or '').casefold():
                return x
    return with_mail[0] if with_mail else None


def compose(agent_name, req):
    size = SIZES.get(str(req['size']).lower().replace(' ', '').replace("'", ''), str(req['size']))
    subject = f"Rate request / طلب عرض سعر — {req['pol']} → {req['pod']} — {req['count']} x {size}"
    details_en = [f"Port of loading: {req['pol']}", f"Port of discharge: {req['pod']}", f"Equipment: {req['count']} x {size}"]
    details_ar = [f"ميناء الشحن: {req['pol']}", f"ميناء الوصول: {req['pod']}", f"الحاويات: {req['count']} × {size}"]
    if req.get('commodity'):
        details_en.append(f"Commodity: {req['commodity']}")
        details_ar.append(f"البضاعة: {req['commodity']}")
    if req.get('ready'):
        details_en.append(f"Cargo ready: {req['ready']}")
        details_ar.append(f"جاهزية البضاعة: {req['ready']}")
    body = (f"Dear {agent_name} team,\n\n"
            "Kindly provide your best ocean freight rate for the following shipment:\n"
            + '\n'.join('- ' + d for d in details_en)
            + "\n\nPlease include free time at destination, local charges, transit time and the validity of the rate.\n\n"
            "السادة فريق " + agent_name + " المحترمين،\n\nنرجو تزويدنا بأفضل سعر شحن بحري للشحنة التالية:\n"
            + '\n'.join('- ' + d for d in details_ar)
            + "\n\nمع توضيح أيام السماح في ميناء الوصول، والرسوم المحلية، ومدة الرحلة، وصلاحية العرض.\n\n"
            "Best regards / مع التحية،\nآفاق طويق للتخليص الجمركي والنقل — Afaq Tuwaiq\ninfo@afaqtawiqs.net · 0530130435")
    return subject, body


def parse_request(args):
    req = {k: re.sub(r'[\x00-\x1f\x7f]', ' ', str(args.get(k) or '')).strip()[:120]
           for k in ('pol', 'pod', 'size', 'count', 'commodity', 'ready', 'agents')}
    req['count'] = re.sub(r'\D', '', req['count']) or '1'
    missing = [label for key, label in (('pol', 'ميناء الشحن'), ('pod', 'ميناء الوصول'), ('size', 'مقاس الحاوية')) if not req[key]]
    return req, missing


def prepare(args, make_code):
    """Prepare the quote emails; nothing is sent. Returns the Arabic summary with the «نفذ» code."""
    req, missing = parse_request(args)
    if missing:
        return 'لطلب عروض الأسعار أحتاج: ' + '، '.join(missing) + '. مثال: «اطلب عروض أسعار شحن من شنغهاي إلى جدة، 2 حاوية 40، أثاث».'
    wanted = [w.strip() for w in re.split(r'[,،/]| و ', req['agents']) if w.strip()] if req['agents'] and req['agents'] not in ('الكل', 'all', 'كلهم') else []
    agents = []
    for a in _rows():
        if wanted and not any(w.casefold() in a['name'].casefold() for w in wanted):
            continue
        agents.append(a)
    emails, skipped = [], []
    for a in agents:
        contact = quote_contact(a['contacts'])
        if not contact:
            skipped.append(a['name'] + (f" ({a['website']})" if a.get('website') else ''))
            continue
        subject, body = compose(a['name'], req)
        emails.append({'agent': a['name'], 'to': contact['email'], 'purpose': contact['purpose'], 'subject': subject, 'body': body})
    if not emails:
        return ('ما لقيت وكيلًا مسجلًا له بريد بهذه الأسماء.'
                + (' بدون بريد في الدليل: ' + '، '.join(skipped) + ' — اطلب منهم من موقعهم أو أضف بريدهم في صفحة «وكلاء الملاحة».' if skipped else '')
                + ' اكتب «دليل وكلاء الملاحة» لعرض الأسماء.')
    batch, rest = emails[:MAX_BATCH], emails[MAX_BATCH:]
    code = make_code({'tool': 'freight_quote_send', 'dept': 'containers', 'request': req, 'emails': batch})
    lines = [f"📨 سلطان: جهزت طلب عرض سعر شحن {req['pol']} ← {req['pod']} — {req['count']} × {req['size']}"
             + (f" — {req['commodity']}" if req.get('commodity') else '') + f' إلى {len(batch)} وكيل:']
    lines += [f"• {e['agent']} — {e['to']} ({e['purpose']})" for e in batch]
    if rest:
        lines.append(f'(وبقي {len(rest)} وكيل؛ حددهم بالاسم في طلب ثانٍ.)')
    if skipped:
        lines.append('⚠️ بدون بريد في الدليل (لم أجهّز لهم): ' + '، '.join(skipped[:10]) + ' — أضف بريدهم في صفحة «وكلاء الملاحة».')
    lines.append(f'\nالرسالة بالعربي والإنجليزي من البريد الرسمي، ولا يُرسل شيء قبل موافقتك.\nللإرسال اكتب: نفذ {code}')
    return '\n'.join(lines)


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS freight_quote_requests(id BIGSERIAL PRIMARY KEY, agent TEXT NOT NULL, email TEXT NOT NULL,
            pol TEXT NOT NULL, pod TEXT NOT NULL, equipment TEXT NOT NULL, commodity TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT '', sent_by TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL)''')


def execute(c, action, actor, send):
    """After «نفذ»: send each prepared email with send(to, subject, body) and record the result."""
    init()
    req = action.get('request') or {}
    sent, failed = [], []
    for e in (action.get('emails') or [])[:MAX_BATCH]:
        try:
            send(e['to'], e['subject'], e['body'])
            status, error = 'sent', ''
            sent.append(e['agent'])
        except Exception as exc:
            status, error = 'failed', type(exc).__name__
            failed.append(e['agent'])
        c.execute('''INSERT INTO freight_quote_requests(agent,email,pol,pod,equipment,commodity,status,error,sent_by,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                  (e['agent'], e['to'], req.get('pol', ''), req.get('pod', ''), f"{req.get('count', '')} x {req.get('size', '')}",
                   req.get('commodity', ''), status, error, actor[:40], utcnow()))
    return (f'✅ أُرسل طلب عرض السعر إلى {len(sent)} وكيل: ' + '، '.join(sent) if sent else 'لم يُرسل شيء.') + (
        f'\n⚠️ تعذر الإرسال إلى: {"، ".join(failed)}' if failed else '') + (
        '\nالردود تصل على البريد الرسمي، واسألني «وش وصل من عروض الأسعار؟».' if sent else '')


def requests_text():
    init()
    with db() as c:
        rows = c.execute('SELECT * FROM freight_quote_requests ORDER BY id DESC LIMIT 30').fetchall()
    if not rows:
        return 'لم تُرسل طلبات عروض أسعار بعد.'
    return '📨 آخر طلبات عروض الأسعار:\n' + '\n'.join(
        f"• {r['created_at']:%d/%m} {r['agent']} — {r['pol']} ← {r['pod']} {r['equipment']} — "
        + ('أُرسل' if r['status'] == 'sent' else 'تعذر') for r in rows)
