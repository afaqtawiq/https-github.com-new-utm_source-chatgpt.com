"""Exact, pure monthly draft-close proposals; never journal or distribute money.

A close consumes a snapshot of claim/expense documents plus explicit, approved
reporting classifications. It does not derive income from account balances,
receipts, invoice goods values, fee recipes, exchange rates, or customer names.
Actual costs are allocated on expense documents only. A separately approved
fixed Saber cost can be a reporting-only claim deduction without creating an
expense, payable or payment. An expense is evidence of a cost, not a claim that
it has been paid. Missing required values remain unknown, not zero.
"""
from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime
import re

from app import finance_core as core


MONEY_FIELDS = (
    'shared_service_income_minor', 'agency_only_income_minor',
    'saber_revenue_minor', 'tax_reserve_minor', 'pass_through_minor',
    'goods_value_minor', 'shared_actual_cost_minor',
    'agency_only_actual_cost_minor',
)
OPTIONAL_MONEY_FIELDS = ('saber_fixed_cost_minor',)
BILLED_FIELDS = (
    'shared_service_income_minor', 'agency_only_income_minor',
    'saber_revenue_minor', 'tax_reserve_minor', 'pass_through_minor',
)
COST_FIELDS = ('shared_actual_cost_minor', 'agency_only_actual_cost_minor')
COMPLETENESS_FIELDS = ('income_complete', 'expenses_complete', 'mapping_complete')
MONEY_LABELS = {
    'shared_service_income_minor': 'إيراد الخدمات المشترك',
    'agency_only_income_minor': 'الإيراد الخاص بالوكالة',
    'saber_revenue_minor': 'إيراد سابر الخاص بالوكالة',
    'tax_reserve_minor': 'الضريبة المحجوزة',
    'pass_through_minor': 'المبالغ العابرة',
    'goods_value_minor': 'قيمة البضاعة المعلوماتية',
    'shared_actual_cost_minor': 'التكاليف الفعلية المشتركة',
    'agency_only_actual_cost_minor': 'التكاليف الفعلية الخاصة بالوكالة',
    'saber_fixed_cost_minor': 'تكلفة سابر الثابتة المعتمدة للتقرير فقط',
}
ROUNDING_POLICY = 'agency_floor_partner_remainder'
ROUNDING_NOTE = 'حصة الوكالة نصف الربح المشترك مقربًا لأسفل؛ تذهب أصغر وحدة متبقية للشريك'


def _integer(value, label, *, positive=False, optional=False):
    """Never coerce strings, bools, floats or rounded decimal amounts."""
    if value is None and optional:
        return None
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError(f'{label}: يلزم عدد صحيح دقيق من أصغر وحدة دون قيم سالبة')
    return value


def _reference(value, label):
    if value is None:
        return ''
    if not isinstance(value, str) or len(value) > 2000 or '\x00' in value:
        raise ValueError(f'{label}: مرجع غير صالح')
    return value.strip()


def _month(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}', value):
        raise ValueError('الشهر يجب أن يكون بصيغة YYYY-MM')
    try:
        date.fromisoformat(value + '-01')
    except ValueError as exc:
        raise ValueError('شهر التقرير غير صالح') from exc
    return value


def _document_date(value, month):
    if isinstance(value, datetime):
        raise ValueError('يلزم تاريخ مستند دون وقت')
    if isinstance(value, str):
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
            raise ValueError('تاريخ المستند غير صالح')
        try:
            value = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError('تاريخ المستند غير صالح') from exc
    if not isinstance(value, date) or value.isoformat()[:7] != month:
        raise ValueError('تاريخ المستند يجب أن يقع داخل شهر التقرير')
    return value.isoformat()


def _sum_known(values):
    """A missing term makes the total unknown rather than a partial subtotal."""
    values = tuple(values)
    return None if any(value is None for value in values) else sum(values)


def _normalize_line(source, month):
    if not isinstance(source, Mapping):
        raise ValueError('سطر التقرير غير صالح')
    line = deepcopy(dict(source))
    line['document_id'] = _integer(line.get('document_id'), 'مرجع المستند', positive=True)
    if line.get('kind') not in ('claim', 'expense'):
        raise ValueError('التقرير يقبل المطالبات والمصروفات فقط؛ الأرصدة والتحصيلات ليست أرباحًا')
    line['currency'] = core.currency_code(line.get('currency'))
    line['amount_minor'] = _integer(line.get('amount_minor'), 'مبلغ المستند', positive=True)
    line['document_date'] = _document_date(line.get('document_date'), month)
    raw_mapping = line.get('mapping')
    if raw_mapping is None:
        raw_mapping = {}
    if not isinstance(raw_mapping, Mapping):
        raise ValueError('تصنيف المستند غير صالح')
    mapping = deepcopy(dict(raw_mapping))
    blockers = []
    status = line.get('status')
    if status is not None and status != 'posted':
        blockers.append('المستند غير مرحّل أو غير نشط')
    for key in MONEY_FIELDS:
        mapping[key] = _integer(mapping.get(key), MONEY_LABELS[key], optional=True)
        if mapping[key] is None:
            blockers.append(f'قيمة غير محددة: {MONEY_LABELS[key]}؛ الصفر يحتاج تأكيدًا صريحًا')
    # This later-added optional feature is absent from legacy mappings. Absence
    # means not used (zero); an explicitly unknown supplied value remains None.
    fixed_cost = _integer(mapping.get('saber_fixed_cost_minor', 0),
                          MONEY_LABELS['saber_fixed_cost_minor'], optional=True)
    mapping['saber_fixed_cost_minor'] = fixed_cost
    if fixed_cost is None:
        blockers.append('تكلفة سابر الثابتة غير محددة؛ لا يفترض مبلغها')
    fixed_approved = mapping.get('saber_fixed_cost_approved', False)
    if type(fixed_approved) is not bool:
        raise ValueError('اعتماد تكلفة سابر الثابتة يجب أن يكون صحيحًا أو خطأ صراحة')
    mapping['saber_fixed_cost_approved'] = fixed_approved
    mapping['saber_fixed_cost_ref'] = _reference(mapping.get('saber_fixed_cost_ref'),
                                                'اعتماد المالك لتكلفة سابر الثابتة')
    if fixed_cost is not None and fixed_cost > 0:
        if line['kind'] != 'claim':
            blockers.append('تكلفة سابر الثابتة تخص المطالبة كتخفيض تقريري فقط ولا تسجل على المصروف')
        if mapping['saber_revenue_minor'] is None or mapping['saber_revenue_minor'] <= 0:
            blockers.append('تكلفة سابر الثابتة تتطلب إيراد سابر موجبًا ومحددًا')
        if fixed_approved is not True or not mapping['saber_fixed_cost_ref']:
            blockers.append('تكلفة سابر الثابتة تتطلب اعتمادًا صريحًا من المالك ومرجع إثباته')
    basis_status = mapping.get('basis_status')
    if basis_status not in (None, '', 'confirmed', 'unresolved', 'undefined'):
        raise ValueError('حالة أساس الاحتساب غير صالحة')
    mapping['basis_status'] = basis_status or 'unresolved'
    if basis_status != 'confirmed':
        blockers.append('أساس الإيراد غير محسوم؛ يلزم تسوية الأساس واعتماده صراحة')
    for key, label in (('basis_ref', 'اعتماد أساس الإيراد'), ('allocation_ref', 'اعتماد توزيع البنود')):
        mapping[key] = _reference(mapping.get(key), label)
        if not mapping[key]:
            blockers.append(f'مرجع {label} مفقود')
    costs_complete = mapping.get('costs_complete')
    if costs_complete is not None and type(costs_complete) is not bool:
        raise ValueError('تأكيد اكتمال التكاليف يجب أن يكون صحيحًا أو خطأ صراحة')
    mapping['costs_complete'] = costs_complete
    if costs_complete is not True:
        blockers.append('اكتمال أدلة التكاليف الفعلية غير مؤكد')
    related_id = mapping.get('related_document_id')
    if related_id is not None:
        related_id = _integer(related_id, 'مرجع المستند المرتبط', positive=True)
        if related_id == line['document_id']:
            raise ValueError('لا يمكن ربط المستند بنفسه')
        mapping['related_document_id'] = related_id
    billed = _sum_known(mapping[key] for key in BILLED_FIELDS)
    costs = _sum_known(mapping[key] for key in COST_FIELDS)
    if line['kind'] == 'claim':
        if billed is not None and billed != line['amount_minor']:
            blockers.append('مجموع الإيراد والضريبة والمبالغ العابرة لا يطابق المطالبة؛ قيمة البضاعة مستبعدة')
        if any(mapping[key] not in (None, 0) for key in COST_FIELDS):
            blockers.append('توثق التكاليف على مستند مصروف مستقل لمنع احتسابها مرتين')
    else:
        if any(mapping[key] not in (None, 0) for key in BILLED_FIELDS + ('goods_value_minor',)):
            blockers.append('المصروف يوزع على التكاليف فقط؛ بنود الإيراد والضريبة والبضاعة يجب أن تكون صفرًا صريحًا')
        if costs is not None and costs != line['amount_minor']:
            blockers.append('مجموع التكاليف الفعلية لا يطابق مبلغ المصروف')
    line['mapping'] = mapping
    line['blockers'] = blockers
    line['ready_for_distribution'] = not blockers
    return line


def calculate_monthly_close(month, lines, *, completeness=None):
    """Build an immutable-input draft profit proposal, grouped by currency.

    ``month`` is YYYY-MM. Each line identifies one dated claim or expense with
    ``document_id``, ``kind``, ``currency``, ``amount_minor`` and ``mapping``.
    Mapping money fields are listed in MONEY_FIELDS and must all be explicit
    nonnegative integers; missing/None values produce blockers. Claims' five
    BILLED_FIELDS reconcile their document amount. Goods values never enter
    income or reconciliation. Claim costs must be zero; expense costs reconcile
    their document and every billed/informational expense field must be zero.

    Optional ``saber_fixed_cost_minor`` defaults to zero when absent. A positive
    claim-only amount requires positive Saber revenue, the strict boolean
    ``saber_fixed_cost_approved=True`` and a nonblank ``saber_fixed_cost_ref``.
    This owner-approved reporting assumption reduces only agency margin; it
    does not assert that an actual expense, payable or payment exists. An
    explicitly supplied None remains unknown. An expense linked to a claim
    using this fixed cost cannot also deduct agency-only actual cost until the
    possible double count is reconciled; both linked lines are blocked.

    Mappings require ``basis_status='confirmed'``, nonblank ``basis_ref`` and
    ``allocation_ref``, and ``costs_complete=True``. An optional
    ``related_document_id`` records evidence linkage, not payment or inference.
    Completeness requires explicit True for each COMPLETENESS_FIELDS item and
    a nonblank ``confirmation_ref``. The caller must ensure the snapshot covers
    the owner and all relevant documents; this pure function cannot discover
    omitted records or verify approval provenance.

    Invalid types/identities/dates/currencies raise ValueError. Incomplete or
    unreconciled classifications return blockers and unknown profit/shares.
    Every proposal remains draft, even when ready_for_distribution is True.
    All margins are currency-isolated and no 30% manager share is inferred.
    """
    month = _month(month)
    if isinstance(lines, (str, bytes, Mapping)):
        raise ValueError('قائمة مستندات التقرير غير صالحة')
    try:
        normalized = [_normalize_line(line, month) for line in lines]
    except TypeError as exc:
        raise ValueError('قائمة مستندات التقرير غير صالحة') from exc
    document_ids = [line['document_id'] for line in normalized]
    if len(document_ids) != len(set(document_ids)):
        raise ValueError('تكرر المستند في التقرير؛ يمنع احتساب الإيراد أو المصروف مرتين')
    by_document = {line['document_id']: line for line in normalized}
    for line in normalized:
        actual_cost = line['mapping']['agency_only_actual_cost_minor']
        related = by_document.get(line['mapping'].get('related_document_id'))
        if (line['kind'] == 'expense' and actual_cost is not None and actual_cost > 0
                and related and related['kind'] == 'claim'
                and (related['mapping']['saber_fixed_cost_minor'] or 0) > 0):
            issue = (f"تكلفة سابر الثابتة في المطالبة {related['document_id']} ومصروف فعلي مرتبط "
                     f"{line['document_id']} قد يتكرران؛ يلزم تسوية التكلفة قبل اقتراح الربح")
            for affected in (line, related):
                affected['blockers'].append(issue)
                affected['ready_for_distribution'] = False
    if completeness is None:
        completeness = {}
    if not isinstance(completeness, Mapping):
        raise ValueError('بيانات اكتمال الشهر غير صالحة')
    completeness = deepcopy(dict(completeness))
    global_blockers = []
    labels = {
        'income_complete': 'حصر جميع إيرادات الشهر غير مؤكد',
        'expenses_complete': 'حصر جميع المصروفات والتكاليف الفعلية للشهر غير مؤكد',
        'mapping_complete': 'اكتمال تصنيف جميع مستندات الشهر غير مؤكد',
    }
    for key in COMPLETENESS_FIELDS:
        value = completeness.get(key)
        if value is not None and type(value) is not bool:
            raise ValueError('تأكيدات اكتمال الشهر يجب أن تكون صحيحًا أو خطأ صراحة')
        completeness[key] = value
        if value is not True:
            global_blockers.append(labels[key])
    completeness['confirmation_ref'] = _reference(completeness.get('confirmation_ref'), 'اعتماد اكتمال الشهر')
    if not completeness['confirmation_ref']:
        global_blockers.append('مرجع اعتماد اكتمال الشهر مفقود')
    if not normalized:
        global_blockers.append('لا توجد مستندات شهرية للمراجعة')

    grouped = {}
    for line in normalized:
        grouped.setdefault(line['currency'], []).append(line)
    currencies = []
    report_blockers = list(global_blockers)
    for currency, group in sorted(grouped.items()):
        local_blockers = []
        for line in group:
            local_blockers.extend(f"مستند {line['document_id']}: {issue}" for issue in line['blockers'])
        result = {'currency': currency, 'document_count': len(group)}
        for key in MONEY_FIELDS + OPTIONAL_MONEY_FIELDS:
            result[key] = _sum_known(line['mapping'][key] for line in group)
        result['billed_total_minor'] = sum(line['amount_minor'] for line in group if line['kind'] == 'claim')
        result['expense_total_minor'] = sum(line['amount_minor'] for line in group if line['kind'] == 'expense')
        result['blockers'] = list(global_blockers) + local_blockers
        for key in ('shared_profit_minor', 'agency_only_profit_minor', 'profit_minor',
                    'agency_share_minor', 'partner_share_minor', 'rounding_minor'):
            result[key] = None
        result['rounding_policy'] = ROUNDING_POLICY
        result['rounding_note'] = ROUNDING_NOTE
        if not result['blockers']:
            shared = result['shared_service_income_minor'] - result['shared_actual_cost_minor']
            agency_only = (result['agency_only_income_minor'] + result['saber_revenue_minor']
                           - result['agency_only_actual_cost_minor'] - result['saber_fixed_cost_minor'])
            # Known losses may be displayed; a distribution/loss allocation is
            # not invented for either pool, even if another pool is profitable.
            result['shared_profit_minor'] = shared
            result['agency_only_profit_minor'] = agency_only
            result['profit_minor'] = shared + agency_only
            if shared < 0 or agency_only < 0:
                issue = 'توجد خسارة في أحد وعائي الربح؛ توزيع الخسارة يحتاج قرارًا صريحًا'
                result['blockers'].append(issue)
                local_blockers.append(issue)
            else:
                result['agency_share_minor'] = agency_only + shared // 2
                result['partner_share_minor'] = shared - shared // 2
                result['rounding_minor'] = shared % 2
        result['ready_for_distribution'] = not result['blockers']
        currencies.append(result)
        report_blockers.extend(f'{currency}: {issue}' for issue in local_blockers)
    return {
        'status': 'draft', 'month': month,
        'ready_for_distribution': bool(normalized) and not report_blockers,
        'blockers': report_blockers, 'currencies': currencies,
        'lines': normalized, 'completeness': completeness,
        'manager_allocation_active': False,
        'distribution_note': 'مسودة اقتراح للمراجعة فقط؛ لا ترحيل ولا صرف ولا توزيع فعلي',
        'rounding_policy': ROUNDING_POLICY,
    }
