"""Date-bounded customer statement projections; no ledger mutations or allocation math."""
from datetime import date, datetime
from decimal import Decimal
import re
from zoneinfo import ZoneInfo
from app import finance_core as core

REPORT_TIMEZONE = ZoneInfo('Asia/Riyadh')


def period(start, end):
    def parse(value):
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError('حدد تاريخ بداية ونهاية صحيحين')
        return date.fromisoformat(value)
    start, end = parse(start), parse(end)
    if start > end or (end - start).days > 366:
        raise ValueError('يجب أن تكون الفترة مرتبة ولا تتجاوز سنة')
    return start, end


def effective_date(entry):
    if entry['phase'] == 'posting':
        value = entry['document_date']
        return value if isinstance(value, date) else date.fromisoformat(value)
    if entry['phase'] != 'reversal':
        raise ValueError('مرحلة القيد غير صالحة')
    value = entry['created_at']
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('تاريخ القيد العكسي يجب أن يتضمن المنطقة الزمنية')
    return value.astimezone(REPORT_TIMEZONE).date()


def integer(value):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)) or not Decimal(value).is_finite() or Decimal(value) != Decimal(value).to_integral_value():
        raise ValueError('المبلغ يجب أن يكون بوحدات صحيحة دقيقة')
    return int(value)


def build_statement(owner, party, currency, start, end, entries):
    """Read current recorded ledger by economic date; reversal on its own date.

    Allocations link receipts only and never change this projection. Output is an
    allowlist: no sources, notes, audit, costs, tax bases or internal rules.
    """
    start, end = period(start, end)
    currency = core.currency_code(currency)
    projected, seen = [], set()
    for entry in entries:
        if entry.get('side') != 'receivable' or entry.get('currency') != currency or entry.get('owner_id') != owner['id'] or entry.get('counterparty_id') != party['id']:
            raise ValueError('لا يمكن خلط الأطراف أو العملات أو نوع الذمة')
        eid = integer(entry['id'])
        if eid in seen:
            raise ValueError('قيد مكرر في الكشف')
        seen.add(eid)
        when = effective_date(entry)
        amount = integer(entry['signed_minor'])
        kind = entry['kind']
        if kind not in core.KINDS or core.KINDS[kind][0] != 'receivable':
            raise ValueError('نوع الحركة غير صالح لكشف العميل')
        projected.append((when, eid, amount, entry))
    projected.sort(key=lambda item: (item[0], item[1]))
    opening = sum(amount for when, _, amount, _ in projected if when < start)
    running, movements = opening, []
    totals = dict(claims_minor=0, receipts_minor=0, adjustments_minor=0, opening_movements_minor=0, reversals_minor=0)
    for when, eid, amount, entry in projected:
        if not start <= when <= end:
            continue
        running += amount
        if entry['phase'] == 'reversal':
            totals['reversals_minor'] += amount
        elif entry['kind'] == 'claim':
            totals['claims_minor'] += amount
        elif entry['kind'] == 'receipt':
            totals['receipts_minor'] -= amount
        elif entry['kind'] == 'receivable_adjustment':
            totals['adjustments_minor'] += amount
        else:
            totals['opening_movements_minor'] += amount
        safe = {key: entry.get(key) for key in ('document_id', 'document_date', 'kind', 'phase', 'invoice_ref', 'customs_ref')}
        safe.update(entry_id=eid, effective_date=when.isoformat(), debit_minor=max(amount, 0), credit_minor=max(-amount, 0), running_minor=running)
        detail = entry.get('claim_detail')
        safe['claim_detail'] = ({key: detail.get(key) for key in ('revision', 'goods_amount', 'goods_currency', 'exchange_rate', 'goods_value_display', 'registry_display', 'tax_display')} if isinstance(detail, dict) and entry['kind'] == 'claim' else None)
        movements.append(safe)
    result = dict(owner_id=owner['id'], owner_name=owner['name'], counterparty_id=party['id'], counterparty_name=party['name'],
                  currency=currency, start=start.isoformat(), end=end.isoformat(), opening_minor=opening, closing_minor=running,
                  movements=movements, **totals)
    for key in ('opening', 'closing', 'claims', 'receipts', 'adjustments', 'opening_movements', 'reversals'):
        result[key+'_display'] = core.display_minor(result[key+'_minor'], currency)
    for movement in movements:
        for key in ('debit', 'credit', 'running'):
            movement[key+'_display'] = core.display_minor(movement[key+'_minor'], currency)
    return result
