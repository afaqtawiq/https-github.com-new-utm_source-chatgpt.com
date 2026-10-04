"""Exact, side-effect-free finance validation. No tax, FX or profit inference."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import csv
import io
import re

CURRENCIES = {'SAR': 2, 'AED': 2, 'QAR': 2, 'USD': 2, 'EUR': 2, 'GBP': 2,
              'OMR': 3, 'BHD': 3, 'KWD': 3, 'JPY': 0}
OPENING_KINDS = frozenset(('opening_receivable', 'opening_payable'))
KINDS = {'opening_receivable': ('receivable', 1), 'opening_payable': ('payable', 1),
         'claim': ('receivable', 1), 'payable': ('payable', 1), 'expense': ('payable', 1),
         'receipt': ('receivable', -1), 'payment': ('payable', -1),
         'receivable_adjustment': ('receivable', -1), 'payable_adjustment': ('payable', -1)}
MAX_AMOUNT = Decimal('999999999999.99999999')


def clean(value, limit=500, required=False):
    value = str(value or '').strip()
    if (required and not value) or len(value) > limit or '\x00' in value:
        raise ValueError('قيمة مطلوبة أو طول غير مسموح')
    return value


def decimal_amount(value):
    raw = clean(value, 32, True)
    # No floats, exponent syntax, commas or implicit locale conversions.
    if not re.fullmatch(r'\d{1,12}(?:\.\d{1,8})?', raw):
        raise ValueError('اكتب المبلغ بالأرقام وبنقطة عشرية، حتى 8 منازل، دون فواصل')
    amount = Decimal(raw)
    if not amount.is_finite() or amount <= 0 or amount > MAX_AMOUNT:
        raise ValueError('يجب أن يكون المبلغ موجبًا وضمن الحد المسموح')
    return amount


def currency_code(value, allow_unknown=False):
    value = clean(value, 3).upper()
    if not value and allow_unknown:
        return ''
    if value not in CURRENCIES:
        raise ValueError('العملة غير معروفة أو غير مدعومة؛ يمنع الترحيل دون عملة مؤكدة')
    return value


def minor_units(value, currency):
    scale = CURRENCIES[currency_code(currency)]
    return int((Decimal(value) * (10 ** scale)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def display_minor(value, currency):
    scale = CURRENCIES[currency_code(currency)]
    return f'{Decimal(value) / (10 ** scale):.{scale}f}'


def exact_minor(value, currency):
    amount = decimal_amount(value)
    minor = minor_units(amount, currency)
    if minor <= 0 or Decimal(display_minor(minor, currency)) != amount:
        raise ValueError('مبلغ التخصيص يجب أن يطابق أصغر وحدة للعملة دون تقريب')
    return minor


def owner_balance_totals(balances):
    """Aggregate posted journal balances, never source amounts or allocations.

    Receipts/payments already reduce the signed balances. Allocations merely
    link their evidence and must not be subtracted a second time. Keep every
    owner and currency separate, including zero and credit (negative) balances.
    """
    def integer(value):
        if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
            raise ValueError('Totals require exact integer minor units')
        number = Decimal(value)
        if not number.is_finite() or number != number.to_integral_value():
            raise ValueError('Totals require exact integer minor units')
        return int(number)

    grouped = {}
    for balance in balances:
        owner_id = integer(balance['owner_id'])
        if owner_id <= 0:
            raise ValueError('Totals require a confirmed owner')
        currency = currency_code(balance['currency'])
        key = (owner_id, currency)
        item = grouped.setdefault(key, dict(owner_id=owner_id, owner_name=balance['owner_name'],
            currency=currency, receivable_minor=0, payable_minor=0, payable_document_count=0))
        item['receivable_minor'] += integer(balance['receivable_minor'])
        item['payable_minor'] += integer(balance['payable_minor'])
        count = integer(balance['payable_document_count'])
        if count < 0:
            raise ValueError('Invalid payable document count')
        item['payable_document_count'] += count
    result = sorted(grouped.values(), key=lambda item: (item['owner_name'], item['owner_id'], item['currency']))
    for item in result:
        item['net_minor'] = item['receivable_minor'] - item['payable_minor']
        for name in ('receivable', 'payable', 'net'):
            item[name+'_display'] = display_minor(item[name+'_minor'], item['currency'])
    return result


def parse_document(form):
    kind = clean(form.get('kind'), 30, True)
    if kind not in KINDS:
        raise ValueError('نوع القيد غير مدعوم')
    currency = currency_code(form.get('currency'), allow_unknown=True)
    amount_raw = clean(form.get('amount'), 32, True)
    amount = decimal_amount(amount_raw)
    document_date = clean(form.get('document_date'), 10)
    if document_date:
        document_date = date.fromisoformat(document_date)
    else:
        document_date = None
    cutoff_raw = clean(form.get('opening_cutoff'), 10)
    opening_cutoff = date.fromisoformat(cutoff_raw) if cutoff_raw else None
    opening_confirmation_ref = clean(form.get('opening_confirmation_ref'), 1000)
    if kind not in OPENING_KINDS and (opening_cutoff or opening_confirmation_ref):
        raise ValueError('بيانات الرصيد الافتتاحي مخصصة لنوع الرصيد الافتتاحي فقط')
    basis = clean(form.get('amount_basis'), 10)
    if basis not in ('gross', 'net', 'unknown'):
        raise ValueError('حدد معنى المبلغ في المصدر')
    verification = clean(form.get('source_verification') or 'recorded', 30)
    if verification not in ('recorded', 'independently_verified'):
        raise ValueError('حالة التحقق من المصدر غير صالحة')
    source_role = clean(form.get('source_role'), 10, True)
    if source_role not in ('detail', 'summary'):
        raise ValueError('حدد إن كان المصدر حركة مفردة أو ملخصًا')
    def positive_id(name, optional=False):
        raw = str(form.get(name) or '')
        if optional and not raw:
            return None
        if not raw.isdigit() or int(raw) <= 0:
            raise ValueError('مرجع الجهة أو الشحنة غير صالح')
        return int(raw)
    return dict(owner_id=positive_id('owner_id'), counterparty_id=positive_id('counterparty_id'),
        kind=kind, currency=currency, source_amount=amount, source_amount_raw=clean(form.get('source_amount_raw') or amount_raw, 200, True),
        amount_minor=minor_units(amount, currency) if currency else None, document_date=document_date,
        opening_cutoff=opening_cutoff, opening_confirmation_ref=opening_confirmation_ref,
        source_ref=clean(form.get('source_ref'), 300, True), source_locator=clean(form.get('source_locator'), 300, True),
        economic_ref=clean(form.get('economic_ref'), 200, True), source_role=source_role,
        source_date_raw=clean(form.get('source_date_raw'), 100), source_status_raw=clean(form.get('source_status_raw'), 200),
        source_verification=verification, verification_ref=clean(form.get('verification_ref'), 500), source_cached_external=form.get('source_cached_external') == '1',
        invoice_ref=clean(form.get('invoice_ref'), 200), customs_ref=clean(form.get('customs_ref'), 200),
        shipment_id=positive_id('shipment_id', True), amount_basis=basis, notes=clean(form.get('notes'), 3000))


def validation_issues(document):
    issues = []
    opening = document.get('kind') in OPENING_KINDS
    if not document.get('currency'):
        issues.append('العملة غير مؤكدة')
    if document.get('source_verification') == 'independently_verified' and not document.get('verification_ref'):
        issues.append('مرجع دليل التحقق المستقل غير موثق')
    # An owner-approved net opening balance is a separate recorded decision, not
    # independent verification of the cached workbook or its historical receipts.
    if document.get('source_cached_external') and document.get('source_verification') != 'independently_verified' and not (opening and document.get('opening_confirmation_ref')):
        issues.append('قيم مخبأة تعتمد على روابط خارجية ولم تتحقق مستقلًا')
    if not document.get('document_date'):
        issues.append('تاريخ الحركة غير مؤكد')
    if opening:
        if not document.get('opening_cutoff') or document.get('opening_cutoff') != document.get('document_date'):
            issues.append('يلزم تاريخ قطع مؤكد يطابق تاريخ الرصيد الافتتاحي')
        if not document.get('opening_confirmation_ref'):
            issues.append('يلزم مرجع موافقة صاحب الحساب على صافي الرصيد الافتتاحي وتاريخ القطع')
        if document.get('source_role') != 'summary' or document.get('amount_basis') != 'net':
            issues.append('الرصيد الافتتاحي صافي ملخص تجميعي بعد التسويات التاريخية')
        if any(document.get(k) for k in ('invoice_ref','customs_ref','shipment_id')):
            issues.append('الرصيد الافتتاحي ليس فاتورة أو إيراد شحنة جديدة؛ وثّق التفاصيل في دليل المصدر')
    elif document.get('source_role') != 'detail':
        issues.append('المصدر ملخص تجميعي؛ لا يرحّل مع الحركات التفصيلية')
    if document.get('amount_minor') is not None and document['amount_minor'] <= 0:
        issues.append('المبلغ بعد التقريب أقل من أصغر وحدة للعملة')
    return issues


def csv_bytes(headers, entries):
    """Spreadsheet-safe text for every field, including leading whitespace."""
    def safe(value):
        text = '' if value is None else str(value)
        return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')) else text
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow([safe(v) for v in headers])
    for entry in entries:
        writer.writerow([safe(v) for v in entry])
    return ('\ufeff' + output.getvalue()).encode('utf-8')
