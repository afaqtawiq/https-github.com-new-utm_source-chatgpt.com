"""Owner-requested (20 Nov 2026): «خلي نورة تسجل المنصرفات». Noura records company expenses as finance DRAFTS
(an expense document, plus a payment document when it was already paid). Nothing is posted: the owner reviews and
posts them from the finance page, like receipts.
"""
import datetime as dt
import re
import uuid
from decimal import Decimal, InvalidOperation

from app.storage import db

CURRENCY_WORDS = {'دولار': 'USD', '$': 'USD', 'usd': 'USD', 'ريال': 'SAR', 'sar': 'SAR', 'درهم': 'AED', 'aed': 'AED',
                  'يورو': 'EUR', 'eur': 'EUR'}


def _currency(value):
    v = str(value or 'SAR').strip().lower()
    return CURRENCY_WORDS.get(v, v.upper() if len(v) == 3 else 'SAR')


def _amount(value):
    text = str(value or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩٫٬', '0123456789.,')).replace(',', '')
    m = re.search(r'\d+(?:\.\d+)?', text)
    try:
        return Decimal(m.group(0)) if m else None
    except InvalidOperation:
        return None


def vendor(c, name, actor):
    """The confirmed counterparty for this supplier; created once (identity VENDOR:<name>)."""
    name = ' '.join(str(name or '').split())[:120]
    row = c.execute("SELECT id,name FROM finance_parties WHERE kind='counterparty' AND lower(name)=lower(%s) ORDER BY id LIMIT 1",
                    (name,)).fetchone()
    if row:
        return row['id']
    from app import finance_service as service
    return service.create_party({'name': name, 'kind': 'counterparty', 'identity_ref': 'VENDOR:' + name.upper(), 'confirmed': '1'}, actor)


def record(vendor_name, amount, actor, *, currency='SAR', date=None, description='', ref='', paid=True, method=''):
    vendor_name = ' '.join(str(vendor_name or '').split())
    value = _amount(amount)
    if len(vendor_name) < 2:
        return 'اذكر الجهة المدفوع لها (المورد).'
    if not value or value <= 0:
        return 'المبلغ غير واضح؛ لم يُسجل شيء.'
    cur = _currency(currency)
    date = date or dt.date.today()
    description = ' '.join(str(description or '').split())[:200] or 'مصروف'
    from app import finance_service as service
    with db() as c:
        owner = c.execute("SELECT id FROM finance_party_display WHERE kind='owner' AND confirmed ORDER BY id LIMIT 1").fetchone()
    if not owner:
        return 'لا يوجد حساب مالك مؤكد في المالية؛ لم يُسجل شيء.'
    try:
        with db() as c:
            vid = vendor(c, vendor_name, actor)
    except Exception as exc:
        return 'تعذر إنشاء حساب المورد: ' + str(getattr(exc, 'detail', exc))[:160]
    base = f'{vid}:{date.isoformat()}:{format(value, "f")}:{cur}:{ref or description}'
    common = {'currency': cur, 'amount': format(value, 'f'), 'document_date': date.isoformat(), 'amount_basis': 'gross',
              'source_role': 'detail', 'source_verification': 'recorded', 'owner_id': str(owner['id']),
              'counterparty_id': str(vid), 'source_amount_raw': format(value, 'f') + ' ' + cur,
              'source_locator': 'إفادة المالك لنورة (المكتب الافتراضي)' + (' — ' + ref if ref else '')}
    out = []
    try:
        eid = service.create_document({**common, 'kind': 'expense',
            'source_ref': f'مصروف: {description} — {vendor_name} بتاريخ {date.isoformat()}',
            'economic_ref': 'EXPENSE:' + base,
            'notes': 'مصروف مسجل عن طريق نورة؛ مسودة بانتظار مراجعة المالك وترحيلها.',
            'idempotency_key': str(uuid.uuid5(uuid.NAMESPACE_URL, 'expense:' + base))}, actor)
        out.append(f'مصروف رقم {eid}')
        if paid:
            pid = service.create_document({**common, 'kind': 'payment',
                'source_ref': f'سداد: {description} — {vendor_name} بتاريخ {date.isoformat()}' + (f' ({method})' if method else ''),
                'economic_ref': 'PAYMENT:' + base,
                'notes': 'سداد المصروف ' + str(eid) + (f' — {method}' if method else '') + '؛ مسودة بانتظار مراجعة المالك.',
                'idempotency_key': str(uuid.uuid5(uuid.NAMESPACE_URL, 'expense-payment:' + base))}, actor)
            out.append(f'سداد رقم {pid}')
    except Exception as exc:
        return 'تعذر التسجيل: ' + str(getattr(exc, 'detail', exc))[:200] + ('\nسُجل: ' + '، '.join(out) if out else '')
    return (f'✅ سجلت {description} لـ{vendor_name}: {format(value, ",.2f")} {cur} بتاريخ {date.isoformat()} — '
            + ' + '.join(out) + ' (مسودات). اعتمدها من صفحة المالية لترحيلها.')


def recent_text(days=30):
    with db() as c:
        rows = c.execute('''SELECT d.id,d.kind,d.document_date,d.amount_minor,d.currency,d.status,p.name FROM finance_documents d
            JOIN finance_parties p ON p.id=d.counterparty_id WHERE d.kind='expense' AND d.created_at > now() - (%s || ' days')::interval
            ORDER BY d.document_date DESC, d.id DESC LIMIT 30''', (str(days),)).fetchall()
    if not rows:
        return f'لا توجد مصروفات مسجلة خلال آخر {days} يوم.'
    lines = [f"• {r['document_date']} — {r['name']}: {r['amount_minor'] / 100:,.2f} {r['currency']} ({'مرحّل' if r['status'] == 'posted' else 'مسودة'}) #{r['id']}"
             for r in rows]
    return f'مصروفات آخر {days} يوم:\n' + '\n'.join(lines)
