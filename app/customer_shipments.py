"""Customer → shipments projection for the existing follow-up dashboard (owner request, Nov 2026).

Read-only. Links a customer to their declarations (customs_declarations), live FASAH statuses (fasah_status) and
container returns (container_returns): last update, who is responsible, and the next step / date when they are known.
A phone links records only on an EXACT full number (no suffix guessing); unknown values stay «غير معروف».
No sends, no prices, no external services; transport pricing and privacy rules are untouched.
"""
import datetime as dt
import re

DECL_NEXT = {
    'preparing': ('تقديم البيان في فسح', 'المخلص'), 'submitted': ('متابعة التدقيق الجمركي', 'موظف التخليص'),
    'under_review': ('متابعة التدقيق الجمركي', 'موظف التخليص'), 'inspection': ('حضور المعاينة/الكشف', 'موظف التخليص'),
    'duties_due': ('سداد الرسوم الجمركية (العميل)', 'خدمة العملاء'), 'duties_paid': ('متابعة إصدار الفسح', 'موظف التخليص'),
    'released': ('ترتيب الخروج والنقل والتسليم', 'النقل'), 'delivered': ('إرجاع الحاوية الفارغة وإغلاق الملف', 'النقل'),
    'closed': ('', ''),
}
FASAH_NEXT = {
    'draft': ('إكمال المسودة وتقديم البيان', 'المخلص'), 'not_arrived': ('انتظار وصول الشحنة للمنفذ', 'موظف التخليص'),
    'under_review': ('متابعة المعالجة في فسح', 'موظف التخليص'), 'reviewed': ('متابعة الخطوة التالية في فسح', 'موظف التخليص'),
    'inspection': ('حضور المعاينة/الكشف', 'موظف التخليص'), 'duties_due': ('سداد الرسوم الجمركية (العميل)', 'خدمة العملاء'),
    'released': ('ترتيب الخروج والنقل', 'النقل'), 'cancelled': ('', ''), 'unknown': ('مراجعة الحالة في فسح', 'موظف التخليص'),
}


def digits(phone):
    d = re.sub(r'\D', '', str(phone or ''))
    if d.startswith('00'):
        d = d[2:]
    if d.startswith('05') and len(d) == 10:
        d = '966' + d[1:]
    return d if re.fullmatch(r'[1-9]\d{8,14}', d) else ''


def _has(c, table):
    return bool(c.execute('SELECT to_regclass(%s) t', (table,)).fetchone()['t'])


def _q(c, sql, args=()):
    try:
        c.execute('SAVEPOINT cust_ship')
        out = c.execute(sql, args).fetchall()
        c.execute('RELEASE SAVEPOINT cust_ship')
        return out
    except Exception:
        c.execute('ROLLBACK TO SAVEPOINT cust_ship')
        return []


def load(c, limit=500):
    from app.declarations import STAGE_LABELS
    out = []
    if _has(c, 'customs_declarations'):
        for r in _q(c, '''SELECT d.*, u.name AS owner_name,
                (SELECT MAX(e.created_at) FROM customs_declaration_events e WHERE e.declaration_id=d.id) AS last_event
                FROM customs_declarations d LEFT JOIN users u ON u.id=d.created_by
                WHERE d.stage<>'closed' ORDER BY d.updated_at DESC LIMIT %s''', (limit,)):
            step, role = DECL_NEXT.get(r['stage'], ('', ''))
            out.append({'source': 'customs_declarations', 'customer': r['customer_name'], 'phone': digits(r['customer_phone']),
                        'ref': ('بيان ' + r['declaration_number']) if r['declaration_number'] else ('بوليصة ' + r['bill_number']) if r['bill_number'] else f"ملف {r['id']}",
                        'port': r['port'] or '', 'status': STAGE_LABELS.get(r['stage'], r['stage']),
                        'last_update': max([x for x in (r['updated_at'], r['last_event']) if x], default=None),
                        'responsible': r.get('owner_name') or 'غير محدد', 'next_step': step, 'next_role': role, 'next_date': None})
    if _has(c, 'fasah_status'):
        from app import fasah_tracking
        known = {x['ref'].split(' ', 1)[-1] for x in out if x['ref'].startswith('بيان ')}
        for r in _q(c, "SELECT * FROM fasah_status WHERE stage NOT IN ('cancelled') ORDER BY changed_at DESC LIMIT %s", (limit,)):
            if r['number'] in known:
                continue
            name, phone = fasah_tracking.customer_for(c, r['number'], r['details'] or '')
            step, role = FASAH_NEXT.get(r['stage'], ('', ''))
            if r['stage'] == 'released':
                step, role = ('ترتيب الخروج والنقل', 'النقل')
            out.append({'source': 'fasah_status', 'customer': name or 'غير مربوط بعميل', 'phone': digits(phone),
                        'ref': ('بيان ' if r['kind'] == 'import' else 'بيان تصدير ') + r['number'], 'port': '',
                        'status': fasah_tracking.LABELS.get(r['stage'], 'حالة غير مصنفة'), 'last_update': r['changed_at'],
                        'responsible': 'غير محدد', 'next_step': step, 'next_role': role, 'next_date': None})
    if _has(c, 'container_returns'):
        for r in _q(c, "SELECT * FROM container_returns WHERE status<>'returned' AND NOT is_test ORDER BY updated_at DESC LIMIT %s", (limit,)):
            out.append({'source': 'container_returns', 'customer': r['customer'] or 'غير محدد', 'phone': digits(r['customer_phone']),
                        'ref': 'حاوية ' + r['container'] + (f" (بوليصة {r['bill']})" if r['bill'] else ''), 'port': '',
                        'status': 'بانتظار إرجاع الفارغ', 'last_update': r['updated_at'],
                        'responsible': r['created_by'] or 'غير محدد',
                        'next_step': 'إرجاع الحاوية الفارغة' + (f" إلى {r['return_place']}" if r['return_place'] else ''),
                        'next_role': 'النقل', 'next_date': r['free_until']})
    return out


def grouped(c, limit=500):
    """One entry per customer (exact phone, else exact name); shipments newest first."""
    groups = {}
    for s in load(c, limit):
        key = ('phone', s['phone']) if s['phone'] else ('name', (s['customer'] or '').strip())
        g = groups.setdefault(key, {'customer': s['customer'], 'phone': s['phone'], 'names': set(), 'shipments': []})
        g['names'].add(s['customer'])
        g['shipments'].append(s)
    far = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    out = []
    for g in groups.values():
        g['shipments'].sort(key=lambda s: s['last_update'] or far, reverse=True)
        dates = [s['next_date'] for s in g['shipments'] if s['next_date']]
        out.append({**g, 'names': sorted(n for n in g['names'] if n), 'identity_review': len(g['names']) > 1,
                    'last_update': g['shipments'][0]['last_update'], 'next_date': min(dates) if dates else None,
                    'next_step': next((s['next_step'] for s in g['shipments'] if s['next_step']), '')})
    return sorted(out, key=lambda g: g['last_update'] or far, reverse=True)


def for_phone(c, phone):
    d = digits(phone)
    return [s for s in load(c) if d and s['phone'] == d] if d else []


def section_html(c):
    from html import escape
    rows = []
    for g in grouped(c)[:300]:
        for i, s in enumerate(g['shipments'][:10]):
            vals = [(' / '.join(g['names']) or 'غير محدد') + (' ⚠️ أسماء مختلفة لنفس الرقم' if g['identity_review'] else '') if i == 0 else '',
                    ('+' + g['phone']) if (g['phone'] and i == 0) else '', s['ref'], s['status'],
                    s['last_update'].astimezone(dt.timezone(dt.timedelta(hours=3))).strftime('%Y-%m-%d %H:%M') if s['last_update'] else 'غير معروف',
                    s['responsible'], s['next_step'] or '—', s['next_role'] or '—', s['next_date'].isoformat() if s['next_date'] else 'غير معروف']
            rows.append('<tr>' + ''.join('<td>' + escape(str(v)) + '</td>' for v in vals) + '</tr>')
    return ('<h2>الشحنات حسب العميل</h2><p>ربط العميل بشحناته من البيانات المسجلة وحالات فسح ومتابعة الحاويات؛ الربط بالرقم الكامل فقط. '
            'الموعد «غير معروف» إذا لم يُسجل.</p><div class="scroll"><table><tr><th>العميل</th><th>الرقم</th><th>الشحنة</th><th>الحالة</th>'
            '<th>آخر تحديث</th><th>المسؤول</th><th>الخطوة التالية</th><th>جهة الخطوة</th><th>الموعد التالي</th></tr>'
            + (''.join(rows) or '<tr><td colspan="9">لا توجد شحنات مفتوحة مسجلة.</td></tr>') + '</table></div>')
