"""Owner (22 Nov 2026): «أبغى المكتب يشتغل كأنه مكتب واقعي ينفذ كل المهام من الشحن إلى تسليم المستودع — الموظفون ما يعرفون
مين صاحب شحنة مدى التطوير وكيف يتواصلون معه».

One shipment file per bill of lading, shared by every manager:
- the customer (consignee) and HOW TO REACH HIM (contact name, phone, email — as written on the B/L / arrival notice),
  shipper, goods, HS code, vessel/voyage, ports, ETA, containers, declaration number;
- one stage, from booked to empty container returned, with the next step and the department responsible;
- a history line for every change.
Files are opened automatically from every shipping document read (WhatsApp or office upload) and kept up to date by
tracking (ETA), declarations and the team. Internal records only; nothing is sent to anyone.
"""
import datetime as dt
import json
import re

from app.storage import db, utcnow

RIYADH = dt.timezone(dt.timedelta(hours=3))
STAGES = [
    ('booked', 'تم الشحن من بلد التصدير', 'سلطان: تتبع الوصول، وفيصل: جهّز البيان قبل الوصول بـ48 ساعة'),
    ('arriving', 'السفينة قادمة (أقل من 3 أيام)', 'فيصل: البيان مقدّم؟ خالد: رتّب النقل'),
    ('arrived', 'وصلت الميناء', 'فيصل: متابعة البيان — الأرضيات مجانية 3 أيام من التنزيل'),
    ('declared', 'البيان مقدّم', 'فيصل: متابعة المعاينة والرسوم'),
    ('inspection', 'تحت المعاينة', 'فيصل/الميدان: حضور المعاينة'),
    ('duties', 'بانتظار سداد الرسوم', 'نورة/العميل: سداد الرسوم'),
    ('released', 'تم الفسح', 'خالد: إسناد الشاحنات وسحب الحاويات'),
    ('trucking', 'الحاويات في الطريق', 'خالد: متابعة التسليم'),
    ('delivered', 'تم التسليم للمستودع', 'سلطان: إرجاع الحاويات فارغة قبل آخر يوم مجاني'),
    ('returned', 'أُرجعت الحاويات فارغة', 'نورة: المطالبة المالية وإقفال الملف'),
    ('closed', 'الملف مقفل', '—'),
]
STAGE_AR = {k: (label, nxt) for k, label, nxt in STAGES}
ORDER = [k for k, _, _ in STAGES]
_READY = False


def init():
    global _READY
    if _READY:
        return
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS shipment_files(id BIGSERIAL PRIMARY KEY, bill_no TEXT NOT NULL UNIQUE,
            customer TEXT NOT NULL DEFAULT '', contact_name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '', shipper TEXT NOT NULL DEFAULT '', goods TEXT NOT NULL DEFAULT '',
            hs_code TEXT NOT NULL DEFAULT '', shipping_line TEXT NOT NULL DEFAULT '', vessel TEXT NOT NULL DEFAULT '',
            voyage TEXT NOT NULL DEFAULT '', pol TEXT NOT NULL DEFAULT '', pod TEXT NOT NULL DEFAULT '', eta TIMESTAMPTZ,
            containers TEXT NOT NULL DEFAULT '[]', declaration_no TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL DEFAULT 'booked',
            notes TEXT NOT NULL DEFAULT '', history TEXT NOT NULL DEFAULT '[]', created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL)''')
        seed(c)
    _READY = True


SEED = [  # the two Maersk bills the owner sent on 21 Nov 2026 (read from the B/L PDFs); ETA from maersk.com tracking.
    ('280395806', ['MRSU7003986'], '1 × 40HC — 76 بالة — 26,706.4 كجم'),
    ('280395789', ['CAAU5931068', 'MRSU2377010', 'MRSU3400033', 'TCNU2747285', 'MRSU7057940'], '5 × 40HC — 370 بالة — 129,538 كجم'),
]


def seed(c):
    now = utcnow()
    eta = dt.datetime(2026, 11, 22, 22, 0, tzinfo=RIYADH)
    for bill, boxes, note in SEED:
        c.execute('''INSERT INTO shipment_files(bill_no,customer,contact_name,phone,email,shipper,goods,hs_code,shipping_line,vessel,
            voyage,pol,pod,eta,containers,stage,notes,history,created_at,updated_at)
            VALUES(%s,'MADA ALTTATWIR ALLHADITH FOR TRADING (مؤسسة مدى التطوير الحديث للتجارة)','ADEL','966540844446',
            'adelmushababb@gmail.com','YUYAO DAFA CHEMICAL FIBER CO., LTD','ألياف بوليستر قصيرة (Polyester Staple Fiber)','550490000000',
            'Maersk','MAERSK CHARLESTON','641W','Ningbo','Jeddah',%s,%s,'arriving',%s,%s,%s,%s) ON CONFLICT(bill_no) DO NOTHING''',
                  (bill, eta, json.dumps(boxes), note, json.dumps([dt.datetime.now(RIYADH).strftime('%d/%m %H:%M') +
                                                                   ' — فُتح الملف من البوليصة وتتبع ميرسك'], ensure_ascii=False), now, now))


def _clean(v, n=200):
    return ' '.join(str(v or '').split())[:n]


def _phone(v):
    d = re.sub(r'\D', '', str(v or ''))
    if d.startswith('00'):
        d = d[2:]
    if d.startswith('05') and len(d) == 10:
        d = '966' + d[1:]
    return d if 9 <= len(d) <= 15 else ''


def _bill(v):
    return re.sub(r'[^A-Za-z0-9]', '', str(v or '')).upper()[:40]


def _eta(v):
    if not v:
        return None
    if isinstance(v, dt.datetime):
        return v
    try:
        return dt.datetime.fromisoformat(str(v)[:19]).replace(tzinfo=RIYADH) if 'T' in str(v) else \
            dt.datetime.combine(dt.date.fromisoformat(str(v)[:10]), dt.time(12), RIYADH)
    except ValueError:
        return None


def _log(row, text):
    try:
        hist = json.loads(row.get('history') or '[]') if row else []
    except ValueError:
        hist = []
    hist.append(dt.datetime.now(RIYADH).strftime('%d/%m %H:%M') + ' — ' + text)
    return json.dumps(hist[-40:], ensure_ascii=False)


def upsert_from_document(fields, source='مستند ملاحي'):
    """Open/refresh the file from a shipping document's extracted fields. Returns the row or None."""
    bill = _bill(fields.get('bill_no'))
    if not bill:
        return None
    init()
    boxes = []
    for raw in fields.get('container_numbers') or []:
        n = re.sub(r'\s', '', str(raw)).upper()
        if re.fullmatch(r'[A-Z]{4}\d{7}', n) and n not in boxes:
            boxes.append(n)
    data = {'customer': _clean(fields.get('consignee')), 'contact_name': _clean(fields.get('consignee_contact'), 80),
            'phone': _phone(fields.get('consignee_phone')), 'email': _clean(fields.get('consignee_email'), 120).lower(),
            'shipper': _clean(fields.get('shipper')), 'goods': _clean(fields.get('goods'), 160),
            'hs_code': _clean(fields.get('hs_code'), 20), 'shipping_line': _clean(fields.get('shipping_line'), 60),
            'vessel': _clean(fields.get('vessel'), 60), 'voyage': _clean(fields.get('voyage'), 20),
            'pol': _clean(fields.get('pol'), 60), 'pod': _clean(fields.get('pod'), 60)}
    eta = _eta(fields.get('eta'))
    now = utcnow()
    with db() as c:
        row = c.execute('SELECT * FROM shipment_files WHERE bill_no=%s', (bill,)).fetchone()
        if row:
            sets = {k: v for k, v in data.items() if v and not row.get(k)}
            old = json.loads(row['containers'] or '[]')
            merged = old + [b for b in boxes if b not in old]
            c.execute('UPDATE shipment_files SET ' + ''.join(f'{k}=%s,' for k in sets) +
                      'containers=%s,eta=COALESCE(eta,%s),history=%s,updated_at=%s WHERE id=%s',
                      tuple(sets.values()) + (json.dumps(merged), eta, _log(row, f'تحديث من {source}'), now, row['id']))
        else:
            c.execute('''INSERT INTO shipment_files(bill_no,customer,contact_name,phone,email,shipper,goods,hs_code,shipping_line,
                vessel,voyage,pol,pod,eta,containers,history,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                      (bill, data['customer'], data['contact_name'], data['phone'], data['email'], data['shipper'],
                       data['goods'], data['hs_code'], data['shipping_line'], data['vessel'], data['voyage'], data['pol'],
                       data['pod'], eta, json.dumps(boxes), _log(None, f'فُتح الملف من {source}'), now, now))
        return c.execute('SELECT * FROM shipment_files WHERE bill_no=%s', (bill,)).fetchone()


def from_tracking(ref, info):
    """Keep the file's ETA / vessel / arrival in step with tracking."""
    if not info:
        return
    init()
    bill = _bill(ref)
    with db() as c:
        row = c.execute('SELECT * FROM shipment_files WHERE bill_no=%s OR containers LIKE %s LIMIT 1', (bill, '%' + bill + '%')).fetchone()
        if not row:
            return
        stage = row['stage']
        if info.get('arrived') and ORDER.index(stage) < ORDER.index('arrived'):
            stage = 'arrived'
        c.execute('''UPDATE shipment_files SET eta=COALESCE(%s,eta), vessel=COALESCE(NULLIF(%s,''),vessel), stage=%s,
            history=%s, updated_at=%s WHERE id=%s''',
                  (info.get('eta'), info.get('vessel') or '', stage,
                   _log(row, 'تتبع: ' + ('وصلت' if info.get('arrived') else 'الوصول ' + (info['eta'].astimezone(RIYADH).strftime('%d/%m %H:%M') if info.get('eta') else '—'))),
                   utcnow(), row['id']))


def find(query):
    init()
    q = str(query or '').strip()
    if not q:
        return []
    bill = _bill(q)
    digits = re.sub(r'\D', '', q)
    with db() as c:
        return c.execute('''SELECT * FROM shipment_files WHERE bill_no=%s OR containers ILIKE %s OR declaration_no=%s
            OR customer ILIKE %s OR contact_name ILIKE %s OR (%s<>'' AND phone LIKE %s) ORDER BY updated_at DESC LIMIT 6''',
                         (bill, '%' + bill + '%', q, '%' + q + '%', '%' + q + '%', digits[-9:] if len(digits) >= 9 else '',
                          '%' + (digits[-9:] if len(digits) >= 9 else '#') + '%')).fetchall()


def card(r):
    label, nxt = STAGE_AR.get(r['stage'], (r['stage'], ''))
    boxes = json.loads(r['containers'] or '[]')
    eta = r['eta'].astimezone(RIYADH).strftime('%d/%m/%Y %H:%M') if r.get('eta') else 'غير معروف'
    contact = '، '.join(x for x in (r.get('contact_name'), ('+' + r['phone']) if r.get('phone') else '', r.get('email')) if x)
    lines = [f"📁 ملف الشحنة — البوليصة {r['bill_no']}",
             f"👤 العميل: {r['customer'] or 'غير مسجل'}" + (f'\n📞 التواصل: {contact}' if contact else '\n📞 التواصل: غير مسجل — أضفه بـ«حدّث ملف الشحنة»'),
             (f"🏭 الشاحن: {r['shipper']}" if r.get('shipper') else ''),
             (f"📦 البضاعة: {r['goods']}" + (f" — البند {r['hs_code']}" if r.get('hs_code') else '') if r.get('goods') else ''),
             f"🚢 {r.get('shipping_line') or ''} {r.get('vessel') or ''} {r.get('voyage') or ''}".strip() +
             (f" — {r['pol']} ← {r['pod']}" if r.get('pol') or r.get('pod') else ''),
             f'🕒 الوصول: {eta}',
             f"🧱 الحاويات ({len(boxes)}): " + ('، '.join(boxes) if boxes else '—'),
             (f"🧾 البيان: {r['declaration_no']}" if r.get('declaration_no') else '🧾 البيان: لم يُسجل بعد'),
             f'📍 المرحلة: {label}', f'➡️ الخطوة التالية: {nxt}',
             (f"📝 ملاحظات: {r['notes']}" if r.get('notes') else '')]
    return '\n'.join(x for x in lines if x)


def lookup_text(query):
    rows = find(query)
    if not rows:
        return (f'ما لقيت ملف شحنة لـ«{query}». الملف ينفتح تلقائيًا من البوليصة أو إشعار الوصول — ارفعها هنا أو أرسلها للوكيل.')
    return '\n\n'.join(card(r) for r in rows[:3])


def update(query, stage='', declaration_no='', phone='', contact_name='', email='', note='', actor=''):
    rows = find(query)
    if not rows:
        return f'ما لقيت ملف شحنة لـ«{query}».'
    r = rows[0]
    sets, changes = {}, []
    if stage:
        key = stage if stage in STAGE_AR else next((k for k, label, _ in STAGES if stage in label), '')
        if key:
            sets['stage'] = key
            changes.append('المرحلة: ' + STAGE_AR[key][0])
    if declaration_no:
        sets['declaration_no'] = _clean(declaration_no, 30)
        changes.append('البيان ' + sets['declaration_no'])
        if ORDER.index(sets.get('stage', r['stage'])) < ORDER.index('declared'):
            sets['stage'] = 'declared'
    if phone and _phone(phone):
        sets['phone'] = _phone(phone)
        changes.append('الجوال')
    if contact_name:
        sets['contact_name'] = _clean(contact_name, 80)
        changes.append('اسم المسؤول')
    if email:
        sets['email'] = _clean(email, 120).lower()
        changes.append('الإيميل')
    if note:
        sets['notes'] = (r['notes'] + ' | ' if r['notes'] else '') + _clean(note, 300)
        changes.append('ملاحظة')
    if not sets:
        return 'ما فيه تغيير واضح. حدد المرحلة أو رقم البيان أو جوال العميل أو ملاحظة.'
    with db() as c:
        c.execute('UPDATE shipment_files SET ' + ''.join(f'{k}=%s,' for k in sets) + 'history=%s,updated_at=%s WHERE id=%s',
                  tuple(sets.values()) + (_log(r, (actor + ': ' if actor else '') + '، '.join(changes)), utcnow(), r['id']))
        r = c.execute('SELECT * FROM shipment_files WHERE id=%s', (r['id'],)).fetchone()
    return '✅ حدّثت الملف.\n\n' + card(r)


def board_text():
    """All open files by stage — the office's live board."""
    init()
    with db() as c:
        rows = c.execute("SELECT * FROM shipment_files WHERE stage NOT IN ('closed') ORDER BY eta NULLS LAST, id").fetchall()
    if not rows:
        return 'لا توجد ملفات شحن مفتوحة.'
    out = ['📋 لوحة الشحنات المفتوحة:']
    for k, label, nxt in STAGES:
        group = [r for r in rows if r['stage'] == k]
        if group:
            out.append(f'\n▪️ {label} ({len(group)}) — {nxt}')
            for r in group:
                eta = r['eta'].astimezone(RIYADH).strftime('%d/%m') if r.get('eta') else '—'
                out.append(f"  • {r['bill_no']} — {r['customer'] or '؟'} — {len(json.loads(r['containers'] or '[]'))} حاوية — وصول {eta}")
    return '\n'.join(out)
