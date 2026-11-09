"""Structured fee ledger per clearance case (owner request, Nov 2026).

Each line states WHO charges it (Afaq fees are kept apart from customs, SABER, port, shipping agent and transport),
its source and reference, currency, VAT treatment and what it includes. Duplicates are refused, a line that is
already included in another line is never added twice, and a final total is shown ONLY when every line is confirmed,
in one currency and with a known VAT treatment. Otherwise the ledger says the total is not final. No total is invented.
Internal records only; nothing is sent, paid or posted.
"""
import hashlib
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.storage import db, utcnow

CATEGORIES = {'afaq_fee': 'أتعاب آفاق طويق', 'customs': 'الجمارك (رسوم/ضريبة استيراد)', 'saber': 'سابر',
              'port': 'الميناء', 'agent': 'الوكيل الملاحي', 'transport': 'النقل', 'other': 'جهة أخرى'}
VAT = {'included': 'شامل الضريبة', 'excluded': 'غير شامل الضريبة', 'exempt': 'معفى / لا ضريبة', 'unknown': 'الضريبة غير معروفة'}
SOURCES = {'quote': 'عرض سعر آفاق المعتمد', 'fasah': 'شاشة/فاتورة فسح', 'saber': 'منصة سابر', 'port': 'فاتورة الميناء',
           'agent': 'فاتورة الوكيل الملاحي', 'transport': 'اتفاق النقل', 'document': 'مستند المعاملة', 'manual': 'إدخال الموظف'}
STATUS = {'confirmed': 'مؤكد', 'needs_verification': 'تحتاج تحقق'}
CURRENCIES = {'SAR', 'USD', 'AED', 'EUR', 'CNY'}
_READY = False


def init():
    global _READY
    if _READY:
        return
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS clearance_fee_items(id BIGSERIAL PRIMARY KEY, case_id BIGINT NOT NULL,
            category TEXT NOT NULL, description TEXT NOT NULL, amount NUMERIC, currency TEXT NOT NULL, vat TEXT NOT NULL,
            vat_rate NUMERIC, source_kind TEXT NOT NULL, source_ref TEXT NOT NULL DEFAULT '', includes TEXT NOT NULL DEFAULT '',
            included_in BIGINT, status TEXT NOT NULL, dedup_key TEXT NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by TEXT, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE UNIQUE INDEX IF NOT EXISTS clearance_fee_items_dedup ON clearance_fee_items(case_id, dedup_key)
            WHERE active''')
    _READY = True


def amount_of(value):
    """Explicit number only (Arabic digits allowed); None when unknown/blank. Never parses words or ranges."""
    text = str(value or '').strip().translate(str.maketrans('٠١٢٣٤٥٦٧٨٩٫٬', '0123456789.,'))
    if not text:
        return None
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?', text):
        raise ValueError('المبلغ غير واضح: اكتب رقمًا فقط (مثل 1500 أو 1,500.50)، أو اتركه فارغًا إن لم يُعرف.')
    return Decimal(text.replace(',', ''))


def norm(text):
    return re.sub(r'[\s\-_/.,:#]+', '', str(text or '')).casefold()


def dedup_key(category, description, amount, currency, source_ref):
    basis = [category, norm(source_ref) or norm(description), str(amount) if amount is not None else 'unknown', currency]
    return hashlib.sha256('|'.join(basis).encode()).hexdigest()[:32]


def add(case_id, data, actor=''):
    """Add one line. Returns (id, message). Raises ValueError with an Arabic reason when refused."""
    init()
    category = data.get('category')
    if category not in CATEGORIES:
        raise ValueError('اختر الجهة التي تتقاضى المبلغ.')
    description = re.sub(r'\s+', ' ', str(data.get('description') or '')).strip()[:200]
    if not description:
        raise ValueError('اكتب وصف البند (مثل: أتعاب التخليص للحاوية).')
    amount = amount_of(data.get('amount'))
    currency = str(data.get('currency') or 'SAR').upper().strip()
    if currency not in CURRENCIES:
        raise ValueError('العملة غير مدعومة؛ اختر SAR أو USD أو AED أو EUR أو CNY.')
    vat = data.get('vat') if data.get('vat') in VAT else 'unknown'
    rate = amount_of(data.get('vat_rate')) if str(data.get('vat_rate') or '').strip() else None
    if rate is not None and not (0 <= rate <= 100):
        raise ValueError('نسبة الضريبة يجب أن تكون بين 0 و100.')
    source_kind = data.get('source_kind') if data.get('source_kind') in SOURCES else 'manual'
    source_ref = re.sub(r'\s+', ' ', str(data.get('source_ref') or '')).strip()[:160]
    includes = re.sub(r'\s+', ' ', str(data.get('includes') or '')).strip()[:300]
    status = data.get('status') if data.get('status') in STATUS else 'needs_verification'
    # A line cannot be "confirmed" without an amount, a known VAT treatment and a source reference.
    if status == 'confirmed' and (amount is None or vat == 'unknown' or not source_ref or source_kind == 'manual'):
        status = 'needs_verification'
    included_in = None
    with db() as c:
        if str(data.get('included_in') or '').strip():
            try:
                parent = int(str(data['included_in']).strip())
            except ValueError:
                raise ValueError('رقم البند الشامل غير صالح.') from None
            row = c.execute('SELECT id FROM clearance_fee_items WHERE id=%s AND case_id=%s AND active', (parent, case_id)).fetchone()
            if not row:
                raise ValueError('البند الشامل غير موجود في هذه المعاملة.')
            included_in = parent
        key = dedup_key(category, description, amount, currency, source_ref)
        dup = c.execute('SELECT id FROM clearance_fee_items WHERE case_id=%s AND dedup_key=%s AND active', (case_id, key)).fetchone()
        if dup:
            raise ValueError(f"البند مسجل مسبقًا (رقم {dup['id']}) بنفس الجهة والمرجع والمبلغ؛ لم يُضف مرة ثانية.")
        now = utcnow()
        rid = c.execute('''INSERT INTO clearance_fee_items(case_id,category,description,amount,currency,vat,vat_rate,source_kind,
            source_ref,includes,included_in,status,dedup_key,created_by,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                        (case_id, category, description, amount, currency, vat, rate, source_kind, source_ref, includes,
                         included_in, status, key, actor, now, now)).fetchone()['id']
    return rid, ('أُضيف البند' + (' ويحتاج تحقق' if status != 'confirmed' else ''))


def deactivate(case_id, item_id, actor=''):
    """Soft removal (kept for audit); a line that others are included in cannot be removed first."""
    init()
    with db() as c:
        if c.execute('SELECT 1 FROM clearance_fee_items WHERE case_id=%s AND included_in=%s AND active', (case_id, item_id)).fetchone():
            raise ValueError('بنود أخرى مسجلة ضمن هذا البند؛ عدّلها أولًا.')
        row = c.execute('''UPDATE clearance_fee_items SET active=FALSE,updated_at=%s,created_by=COALESCE(created_by,'')||%s
            WHERE id=%s AND case_id=%s AND active RETURNING id''', (utcnow(), ' | أُلغي: ' + str(actor)[:60], item_id, case_id)).fetchone()
    if not row:
        raise ValueError('البند غير موجود.')


def items(case_id):
    init()
    with db() as c:
        return c.execute('SELECT * FROM clearance_fee_items WHERE case_id=%s AND active ORDER BY category, id', (case_id,)).fetchall()


def q2(value):
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def summary(case_id):
    """Per-provider confirmed subtotals; the final total only when nothing is unresolved."""
    rows = items(case_id)
    groups, unresolved, counted = {}, [], []
    for r in rows:
        line = dict(r)
        if r['included_in']:
            line['counted'] = False
            line['why'] = f"ضمن البند {r['included_in']}؛ لا يُجمع مرة أخرى"
        else:
            line['counted'] = True
        if r['status'] != 'confirmed' or r['amount'] is None or r['vat'] == 'unknown':
            unresolved.append(line)
        groups.setdefault(r['category'], []).append(line)
        if line['counted'] and r['status'] == 'confirmed' and r['amount'] is not None:
            counted.append(line)
    subtotals = {}
    for line in counted:
        subtotals.setdefault((line['category'], line['currency']), Decimal('0'))
        subtotals[(line['category'], line['currency'])] += Decimal(line['amount'])
    currencies = {line['currency'] for line in rows if not line['included_in']}
    vat_lines = []
    for line in counted:
        if line['vat'] == 'excluded' and line['vat_rate'] is not None:
            vat_lines.append((line, q2(Decimal(line['amount']) * Decimal(line['vat_rate']) / 100)))
    reasons = []
    if not rows:
        reasons.append('لا توجد بنود رسوم مسجلة.')
    if unresolved:
        reasons.append(f'{len(unresolved)} بند يحتاج تحقق (مبلغ أو ضريبة أو مصدر غير مؤكد).')
    if len(currencies) > 1:
        reasons.append('البنود بأكثر من عملة؛ لا تُجمع دون سعر صرف معتمد.')
    if any(line['vat'] == 'excluded' and line['vat_rate'] is None for line in counted):
        reasons.append('بند غير شامل الضريبة بدون نسبة ضريبة مؤكدة.')
    final = None
    if not reasons:
        final = q2(sum((Decimal(line['amount']) for line in counted), Decimal('0')) + sum((v for _, v in vat_lines), Decimal('0')))
    return {'groups': groups, 'subtotals': {f'{k[0]}|{k[1]}': q2(v) for k, v in subtotals.items()},
            'vat_lines': [{'id': line['id'], 'vat': v} for line, v in vat_lines], 'unresolved': unresolved,
            'final_total': final, 'final_currency': next(iter(currencies)) if final is not None else None,
            'not_final_reasons': reasons}


def text(case_id):
    """Plain Arabic rendering (used by the card and by tests)."""
    s = summary(case_id)
    out = []
    for cat, label in CATEGORIES.items():
        lines = s['groups'].get(cat)
        if not lines:
            continue
        out.append(f'— {label}:')
        for line in lines:
            amount = f"{Decimal(line['amount']):,.2f} {line['currency']}" if line['amount'] is not None else 'المبلغ غير معروف'
            extra = [VAT[line['vat']] + (f" {line['vat_rate']}%" if line['vat_rate'] is not None else ''),
                     'المصدر: ' + SOURCES[line['source_kind']] + (f" ({line['source_ref']})" if line['source_ref'] else '')]
            if line['includes']:
                extra.append('يشمل: ' + line['includes'])
            if not line['counted']:
                extra.append(line['why'])
            out.append(f"  #{line['id']} {line['description']}: {amount} — {STATUS[line['status']] if line['status'] == 'confirmed' and line['amount'] is not None and line['vat'] != 'unknown' else 'تحتاج تحقق'} · " + ' · '.join(extra))
    for key, value in s['subtotals'].items():
        cat, cur = key.split('|')
        out.append(f'مجموع المؤكد — {CATEGORIES[cat]}: {value:,.2f} {cur}')
    if s['final_total'] is not None:
        out.append(f"الإجمالي النهائي المؤكد: {s['final_total']:,.2f} {s['final_currency']}")
    else:
        out.append('لا يوجد إجمالي نهائي: ' + ' '.join(s['not_final_reasons']))
    return '\n'.join(out)
