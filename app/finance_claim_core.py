"""Explicit claim presentation values. Never infer fees, tax or exchange rates."""
from decimal import Decimal, localcontext
from app import finance_core as core


COMPONENTS = (
    ('customs_duty', 'جمارك'), ('customs_other', 'رسوم جمركية أخرى'),
    ('clearance', 'تخليص'), ('saber', 'سابر'), ('zakat', 'زكاة'),
    ('registry', 'سجل تجاري'), ('tax', 'ضريبة'),
)


def parse_details(form, document):
    allowed = {'csrf', 'idempotency_key', 'expected_revision', 'confirmation',
               'goods_amount', 'goods_currency', 'exchange_rate', 'source_ref', 'reason'}
    allowed.update(key for key, _ in COMPONENTS)
    if set(form) - allowed:
        raise ValueError('حقول تفصيل المطالبة غير معروفة')
    if document['kind'] != 'claim' or document['status'] not in ('draft', 'reviewed', 'posted'):
        raise ValueError('التفصيل متاح لمطالبة مالية نشطة فقط')
    currency = core.currency_code(document['currency'])
    if not document.get('amount_minor'):
        raise ValueError('يلزم مبلغ مطالبة مؤكد قبل إضافة التفصيل')
    if form.get('confirmation') != '1':
        raise ValueError('أكد مطابقة التفصيل للمصدر وإجمالي المطالبة دون قيمة البضاعة')
    revision = core.clean(form.get('expected_revision'), 19, True)
    if not revision.isascii() or not revision.isdigit() or int(revision) > 9223372036854775807:
        raise ValueError('نسخة التفصيل غير صالحة؛ حدّث الصفحة')
    goods_currency = core.currency_code(form.get('goods_currency'))
    goods_amount = core.decimal_amount(form.get('goods_amount'))
    if Decimal(core.display_minor(core.minor_units(goods_amount, goods_currency), goods_currency)) != goods_amount:
        raise ValueError('قيمة فاتورة البضاعة يجب أن تطابق دقة عملتها')
    rate = core.decimal_amount(form.get('exchange_rate'))
    if goods_currency == currency and rate != 1:
        raise ValueError('سعر التحويل لنفس العملة يجب أن يكون 1')
    with localcontext() as context:
        context.prec = 48
        converted = goods_amount * rate
        if converted > core.MAX_AMOUNT:
            raise ValueError('قيمة البضاعة المحولة تتجاوز الحد المسموح')
        goods_value_minor = core.minor_units(converted, currency)
    if goods_value_minor <= 0:
        raise ValueError('قيمة البضاعة المحولة أقل من أصغر وحدة للعملة')
    components = {}
    for key, _ in COMPONENTS:
        raw = core.clean(form.get(key), 32, True)
        # Every field is explicit, including zero; no silently missing charges.
        if raw in ('0', '0.0', '0.00', '0.000'):
            value = 0
        else:
            value = core.exact_minor(raw, currency)
        components[key] = value
    total = sum(components.values())
    if total != document['amount_minor']:
        raise ValueError('مجموع بنود المطالبة يجب أن يساوي مبلغ المستند تمامًا دون إضافة قيمة البضاعة')
    return dict(previous_revision=int(revision), goods_amount=str(goods_amount),
                goods_currency=goods_currency, exchange_rate=str(rate),
                goods_value_minor=goods_value_minor, currency=currency,
                components=components, claim_total_minor=total,
                source_ref=core.clean(form.get('source_ref'), 1000, True),
                reason=core.clean(form.get('reason'), 1000, True))


def present_details(row):
    if not row:
        return None
    item = dict(row)
    currency = item['currency']
    item['goods_amount'] = core.display_minor(core.minor_units(Decimal(item['goods_amount']), item['goods_currency']), item['goods_currency'])
    rate = format(Decimal(item['exchange_rate']), 'f')
    item['exchange_rate'] = rate.rstrip('0').rstrip('.') if '.' in rate else rate
    item['goods_value_display'] = core.display_minor(item['goods_value_minor'], currency)
    item['claim_total_display'] = core.display_minor(item['claim_total_minor'], currency)
    item['component_display'] = {key: core.display_minor(value, currency) for key, value in item['components'].items()}
    item['customs_total_display'] = core.display_minor(item['components']['customs_duty'] + item['components']['customs_other'], currency)
    return item
