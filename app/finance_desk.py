"""Finance desk upgrade (owner, 25 Nov 2026: «قسم المحاسبة عايز تطوير ومهارات ليصبح قسم محترف الأداء»).

Read-only analysis for Noura (المالية والحسابات), built on the existing ledger (finance_documents / finance_entries —
posted entries only for balances) and the existing desks (collections, expenses, billing gap):
- receivables_aging: what each customer owes, split by age (FIFO: payments settle the oldest claims first).
- overview(month): billed, collected, expenses, drafts waiting for the owner's posting, receivables and aging,
  unbilled FASAH declarations — one management message.
- checks(): accounting controls — possible duplicate documents, drafts left unposted, claims without an invoice or
  customs reference, receivables over 90 days, receipts in drafts.
- playbook(topic): the accounting playbooks in app/finance_playbooks (Saudi VAT for clearance & transport, e-invoicing,
  month-end close, collections policy, cash-flow forecast, shipment profitability, controls…).
Nothing here posts, edits or sends anything.
"""
import datetime as dt
import os
import re
from decimal import Decimal

from app.storage import db

RIYADH = dt.timezone(dt.timedelta(hours=3))
BUCKETS = ((30, '0–30 يوم'), (60, '31–60 يوم'), (90, '61–90 يوم'), (None, 'أكثر من 90 يوم'))
ROOT = os.path.join(os.path.dirname(__file__), 'finance_playbooks')


def sar(minor):
    return format(Decimal(minor or 0) / 100, ',.2f')


def _today():
    return dt.datetime.now(RIYADH).date()


# ---------- receivables aging (FIFO) ----------

def _net_documents(c, currency='SAR'):
    """Posted receivable movements per document, net of reversals: [(party_id, party, date, kind, net_minor)]."""
    return c.execute("""SELECT p.id party_id, p.name party, d.id, d.kind, d.document_date, SUM(e.signed_minor) net
        FROM finance_entries e JOIN finance_documents d ON d.id=e.document_id
        JOIN finance_party_display p ON p.id=d.counterparty_id
        WHERE e.side='receivable' AND d.currency=%s AND p.kind='counterparty'
        GROUP BY p.id, p.name, d.id, d.kind, d.document_date HAVING SUM(e.signed_minor)<>0
        ORDER BY p.id, d.document_date, d.id""", (currency,)).fetchall()


def aging(as_of=None, currency='SAR'):
    """{party: {'total': minor, 'buckets': [minor×4], 'oldest_open': date|None}} — payments settle oldest claims first."""
    as_of = as_of or _today()
    with db() as c:
        if not c.execute("SELECT to_regclass('finance_entries') t").fetchone()['t']:
            return {}
        rows = _net_documents(c, currency)
    parties = {}
    for r in rows:
        parties.setdefault((r['party_id'], r['party']), []).append(r)
    out = {}
    for (_, name), docs in parties.items():
        debits = [[d['document_date'] or as_of, int(d['net'])] for d in docs if d['net'] > 0]
        credit = -sum(int(d['net']) for d in docs if d['net'] < 0)
        for item in debits:  # FIFO
            used = min(item[1], credit)
            item[1] -= used
            credit -= used
        buckets = [0, 0, 0, 0]
        oldest = None
        for day, left in debits:
            if left <= 0:
                continue
            age = (as_of - day).days
            idx = 0 if age <= 30 else 1 if age <= 60 else 2 if age <= 90 else 3
            buckets[idx] += left
            oldest = day if oldest is None or day < oldest else oldest
        total = sum(buckets) - credit  # unapplied credit (customer paid in advance) shows as a negative balance
        if total:
            out[name] = {'total': total, 'buckets': buckets, 'oldest_open': oldest, 'advance': credit}
    return out


def aging_text(as_of=None):
    data = aging(as_of)
    if not data:
        return 'لا توجد أرصدة مدينة مرحّلة على العملاء.'
    as_of = as_of or _today()
    rows = sorted(data.items(), key=lambda kv: -kv[1]['total'])
    totals = [sum(v['buckets'][i] for v in data.values()) for i in range(4)]
    lines = [f'📊 أعمار الذمم المدينة (مرحّل فقط) حتى {as_of.strftime("%d/%m/%Y")}:',
             f'الإجمالي: {sar(sum(v["total"] for v in data.values()))} ريال']
    lines += [f'• {label}: {sar(t)}' for (_, label), t in zip(BUCKETS, totals)]
    lines.append('')
    for name, v in rows[:12]:
        parts = '، '.join(f'{label} {sar(m)}' for (_, label), m in zip(BUCKETS, v['buckets']) if m)
        days = (as_of - v['oldest_open']).days if v['oldest_open'] else 0
        lines.append(f'{name}: {sar(v["total"])} ريال' + (f' — أقدم مطالبة مفتوحة منذ {days} يوم' if v['oldest_open'] else '')
                     + (f'\n   {parts}' if parts else '') + (f'\n   دفعة مقدمة غير مخصصة {sar(v["advance"])}' if v['advance'] else ''))
    over90 = [n for n, v in rows if v['buckets'][3] > 0]
    if over90:
        lines.append('\n⚠️ متأخرات فوق 90 يوم: ' + '، '.join(over90[:8]) + ' — أولوية التحصيل (collect_invoice).')
    return '\n'.join(lines)


# ---------- management overview ----------

def _month(value):
    m = re.match(r'(\d{4})-(\d{1,2})$', str(value or '').strip())
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), 1)
    t = _today()
    return dt.date(t.year, t.month, 1)


def overview(month=None):
    start = _month(month)
    end = (start + dt.timedelta(days=32)).replace(day=1)
    with db() as c:
        if not c.execute("SELECT to_regclass('finance_documents') t").fetchone()['t']:
            return 'لا توجد حسابات مسجلة بعد.'
        sums = {r['kind']: r for r in c.execute("""SELECT kind, status, COUNT(*) n, COALESCE(SUM(amount_minor),0) s
            FROM finance_documents WHERE currency='SAR' AND document_date >= %s AND document_date < %s AND status IN ('posted','draft','reviewed')
            GROUP BY kind, status""", (start, end)).fetchall() if r['status'] == 'posted'}
        drafts = c.execute("""SELECT kind, COUNT(*) n, COALESCE(SUM(amount_minor),0) s FROM finance_documents
            WHERE status IN ('draft','reviewed') GROUP BY kind ORDER BY 3 DESC""").fetchall()
        expenses_any = c.execute("""SELECT COUNT(*) n, COALESCE(SUM(amount_minor),0) s FROM finance_documents
            WHERE kind='expense' AND currency='SAR' AND document_date >= %s AND document_date < %s AND status NOT IN ('void','reversed')""",
                                 (start, end)).fetchone()
    billed = sums.get('claim', {}).get('s', 0) if sums.get('claim') else 0
    collected = sums.get('receipt', {}).get('s', 0) if sums.get('receipt') else 0
    data = aging()
    owed = sum(v['total'] for v in data.values())
    over90 = sum(v['buckets'][3] for v in data.values())
    label = start.strftime('%m/%Y')
    lines = [f'💼 ملخص المالية — {label}',
             f'المفوتر (مطالبات مرحّلة): {sar(billed)} ريال',
             f'المحصّل (سندات قبض مرحّلة): {sar(collected)} ريال',
             f'المصروفات المسجلة: {sar(expenses_any["s"])} ريال ({expenses_any["n"]} مصروف، مرحّل وغير مرحّل)',
             f'الذمم المدينة الآن: {sar(owed)} ريال' + (f' — منها فوق 90 يوم {sar(over90)}' if over90 else '')]
    if billed:
        lines.append(f'نسبة التحصيل للشهر: {collected * 100 // billed}% من المفوتر')
    if drafts:
        lines.append('🕒 بانتظار اعتمادك وترحيلك: ' + '، '.join(f"{KIND_AR.get(d['kind'], d['kind'])} {d['n']} ({sar(d['s'])})" for d in drafts))
    try:
        from app import billing_gap
        gap = billing_gap.report(start.strftime('%Y-%m'))
        if gap:
            lines.append('\n' + str(gap).split('\n')[0])
    except Exception:
        pass
    lines.append('للتفاصيل: «أعمار الذمم» — «فحص الحسابات» — «كشف <العميل>».')
    return '\n'.join(lines)


KIND_AR = {'claim': 'مطالبات', 'receipt': 'سندات قبض', 'expense': 'مصروفات', 'payment': 'مدفوعات', 'payable': 'ذمم دائنة',
           'opening_receivable': 'أرصدة افتتاحية', 'opening_payable': 'أرصدة دائنة افتتاحية',
           'receivable_adjustment': 'تسويات مدينة', 'payable_adjustment': 'تسويات دائنة', 'receivable_reconciliation': 'مطابقات'}


# ---------- controls ----------

def checks(today=None):
    today = today or _today()
    out = []
    with db() as c:
        if not c.execute("SELECT to_regclass('finance_documents') t").fetchone()['t']:
            return 'لا توجد حسابات مسجلة بعد.'
        dups = c.execute("""SELECT p.name, d.kind, d.amount_minor, d.document_date, array_agg(d.id ORDER BY d.id) ids
            FROM finance_documents d JOIN finance_party_display p ON p.id=d.counterparty_id
            WHERE d.status NOT IN ('void','reversed') AND d.amount_minor IS NOT NULL AND d.document_date >= %s
            GROUP BY p.name, d.kind, d.amount_minor, d.document_date HAVING COUNT(*)>1 ORDER BY d.document_date DESC LIMIT 10""",
                         (today - dt.timedelta(days=120),)).fetchall()
        stale = c.execute("""SELECT kind, COUNT(*) n, COALESCE(SUM(amount_minor),0) s, MIN(created_at) oldest FROM finance_documents
            WHERE status IN ('draft','reviewed') AND created_at < %s GROUP BY kind""", (today - dt.timedelta(days=7),)).fetchall()
        noref = c.execute("""SELECT COUNT(*) n FROM finance_documents WHERE kind='claim' AND status='posted'
            AND COALESCE(invoice_ref,'')='' AND COALESCE(customs_ref,'')=''""").fetchone()['n']
    if dups:
        out.append('🔁 حركات قد تكون مكررة (نفس الجهة والنوع والمبلغ والتاريخ):')
        out += [f"• {d['name']} — {KIND_AR.get(d['kind'], d['kind'])} {sar(d['amount_minor'])} بتاريخ {d['document_date']} — أرقام {', '.join(map(str, d['ids']))}"
                for d in dups]
    if stale:
        out.append('🕒 مسودات عمرها أكثر من 7 أيام بدون ترحيل:')
        out += [f"• {KIND_AR.get(s['kind'], s['kind'])}: {s['n']} بقيمة {sar(s['s'])} — أقدمها {s['oldest'].astimezone(RIYADH).strftime('%d/%m')}" for s in stale]
    if noref:
        out.append(f'🧾 {noref} مطالبة مرحّلة بدون رقم فاتورة ولا رقم بيان — يصعب مطابقتها مع العميل.')
    over = {n: v for n, v in aging(today).items() if v['buckets'][3] > 0}
    if over:
        out.append('⏰ ذمم فوق 90 يوم: ' + '، '.join(f'{n} {sar(v["buckets"][3])}' for n, v in sorted(over.items(), key=lambda kv: -kv[1]['buckets'][3])[:8]))
    if not out:
        return '✅ فحص الحسابات: لا ملاحظات (لا تكرار، لا مسودات متأخرة، لا متأخرات فوق 90 يوم).'
    return '🔍 فحص الحسابات (للمراجعة — لم يُعدَّل شيء):\n' + '\n'.join(out)


# ---------- playbooks ----------

ARABIC = {
    'saudi-vat-logistics': ('ضريبه', 'ضريبة', 'القيمه المضافه', 'القيمة المضافة', 'vat', 'صفري', 'معفي', 'نقل دولي', 'مدفوعات نيابه', 'نيابة'),
    'e-invoicing-fatoora': ('فاتوره الكترونيه', 'فاتورة إلكترونية', 'فاتورة الكترونية', 'فوتره', 'فوترة', 'فاتوره', 'زاتكا', 'qr', 'الربط', 'fatoora'),
    'chart-of-accounts': ('دليل الحسابات', 'شجره الحسابات', 'شجرة الحسابات', 'قيد', 'قيود', 'ترحيل', 'تصنيف', 'ايراد', 'إيراد'),
    'month-end-close': ('اقفال', 'إقفال', 'نهايه الشهر', 'نهاية الشهر', 'قفل الشهر', 'مطابقه', 'مطابقة'),
    'receivables-collections': ('تحصيل', 'ذمم', 'متاخرات', 'متأخرات', 'اعمار', 'أعمار', 'عميل متعثر', 'ائتمان', 'كشف حساب'),
    'cash-flow-forecast': ('سيوله', 'سيولة', 'تدفق نقدي', 'توقع', 'رسوم مستحقه', 'رسوم مستحقة'),
    'shipment-profitability': ('ربح', 'ربحيه', 'ربحية', 'هامش', 'تكلفه الشحنه', 'تكلفة الشحنة', 'مربح'),
    'expense-controls': ('مصروف', 'مصروفات', 'عهده', 'عهدة', 'نثريات', 'رقابه', 'رقابة', 'تكرار', 'احتيال'),
    'bank-reconciliation': ('بنك', 'كشف البنك', 'حواله', 'حوالة', 'تسويه بنكيه', 'تسوية بنكية'),
    'zakat-basics': ('زكاه', 'زكاة', 'اقرار', 'إقرار', 'قوائم ماليه', 'قوائم مالية'),
    'customer-statements': ('كشف', 'كشوفات', 'رصيد العميل', 'مطابقه رصيد', 'مطابقة رصيد', 'اعتراض'),
}


def _fold(text):
    text = re.sub(r'[ً-ٰٟـ]', '', str(text or '')).lower()
    return text.translate(str.maketrans('أإآىة', 'ااايه'))


def index():
    found = {}
    if not os.path.isdir(ROOT):
        return found
    for name in sorted(os.listdir(ROOT)):
        path = os.path.join(ROOT, name, 'GUIDE.md')
        if os.path.exists(path):
            head = open(path, encoding='utf-8').read(600)
            m = re.search(r'^description:\s*"?(.+?)"?\s*$', head, re.M)
            found[name] = m.group(1) if m else name
    return found


def choose(topic, limit=3):
    text = ' ' + _fold(topic) + ' '
    scores = {}
    for name, use in index().items():
        score = 10 if name in text or name.replace('-', ' ') in text else 0
        score += sum(4 for w in ARABIC.get(name, ()) if _fold(w) in text)
        score += sum(1 for w in re.findall(r'[a-z]{4,}', use.lower()) if w in text)
        if score:
            scores[name] = score
    return [n for n, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:limit]]


def playbook(topic='', name=''):
    names = [name] if name and name in index() else choose(topic)
    if not names:
        return 'أدلة المحاسبة المتاحة:\n' + '\n'.join(f'• {n}: {d}' for n, d in index().items())
    text = open(os.path.join(ROOT, names[0], 'GUIDE.md'), encoding='utf-8').read()[:14000]
    others = [n for n in names[1:]]
    return (f'📘 دليل «{names[0]}»\n' + text + ('\n\nأدلة قريبة: ' + '، '.join(others) if others else '')
            + '\n\nطبّق الدليل على بيانات آفاق الفعلية من أدوات المالية؛ لا تخترع أرقامًا، وأي حكم ضريبي/زكوي يُراجع مع المحاسب القانوني.')


# ---------- posting (Noura prepares, the manager approves with «نفذ») ----------

SPECIAL_KINDS = ('opening_receivable', 'opening_payable', 'receivable_reconciliation')  # need extra acknowledgements in the workspace


def _postable(c):
    """Open drafts/reviewed documents, split into clean ones and ones held back (possible duplicates, special kinds)."""
    rows_ = c.execute("""SELECT d.id, d.kind, d.amount_minor, d.document_date, d.counterparty_id, p.name
        FROM finance_documents d JOIN finance_party_display p ON p.id=d.counterparty_id
        WHERE d.status IN ('draft','reviewed') ORDER BY d.document_date, d.id""").fetchall()
    dup_ids = {r['id'] for r in c.execute("""SELECT d.id FROM finance_documents d WHERE d.status IN ('draft','reviewed') AND EXISTS(
        SELECT 1 FROM finance_documents o WHERE o.id<>d.id AND o.status NOT IN ('void','reversed')
        AND o.counterparty_id=d.counterparty_id AND o.kind=d.kind AND o.amount_minor=d.amount_minor AND o.document_date=d.document_date)""").fetchall()}
    clean, held = [], []
    for r in rows_:
        if r['kind'] in SPECIAL_KINDS:
            held.append((r, 'رصيد افتتاحي/مطابقة — يُرحّل من شاشة الحسابات'))
        elif r['id'] in dup_ids:
            held.append((r, 'قد يكون مكرر'))
        else:
            clean.append(r)
    return clean, held


def _line(r):
    return f"#{r['id']} {r['name']} — {KIND_AR.get(r['kind'], r['kind'])} {sar(r['amount_minor'] or 0)} بتاريخ {r['document_date']}"


def post_preview(ids=None):
    """Return (snapshot, text). snapshot = [(id, amount_minor)] to post; explicit ids may include held duplicates (manager's call)."""
    ids = {int(i) for i in (ids or [])}
    with db() as c:
        if not c.execute("SELECT to_regclass('finance_documents') t").fetchone()['t']:
            return [], 'لا توجد حسابات مسجلة بعد.'
        clean, held = _postable(c)
    if ids:
        pool = {r['id']: r for r in clean} | {r['id']: r for r, why in held if r['kind'] not in SPECIAL_KINDS}
        chosen = [pool[i] for i in sorted(ids) if i in pool]
        missing = sorted(ids - set(pool))
        held_out = []
    else:
        chosen, missing, held_out = clean, [], held
    if not chosen:
        return [], ('لا توجد مسودات جاهزة للترحيل.' + (f" الأرقام غير موجودة أو مرحّلة: {', '.join(map(str, missing))}" if missing else ''))
    by_kind = {}
    for r in chosen:
        n, s = by_kind.get(r['kind'], (0, 0))
        by_kind[r['kind']] = (n + 1, s + (r['amount_minor'] or 0))
    out = [f'📒 جاهز للترحيل ({len(chosen)} قيد):']
    out += [f'• {n} قيد {KIND_AR.get(k, k)} = {sar(s)}' for k, (n, s) in by_kind.items()]
    if len(chosen) <= 15:
        out += ['', *(_line(r) for r in chosen)]
    if held_out:
        out += ['', f'⛔ مستثنى من الترحيل ({len(held_out)}):'] + [f'• {_line(r)} — {why}' for r, why in held_out[:20]]
        out.append('لترحيل قيد منها بعد التأكد اكتب: «نورة رحّلي القيد رقم …».')
    if missing:
        out.append(f"⚠️ أرقام غير موجودة أو ليست مسودة: {', '.join(map(str, missing))}")
    out.append('الترحيل يثبت القيود في الذمم والكشوف، والتصحيح بعده يكون بقيد عكسي.')
    return [(r['id'], r['amount_minor']) for r in chosen], '\n'.join(out)


def _actor():
    with db() as c:
        active = c.execute("""SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='is_active'
            AND table_schema=current_schema()""").fetchone()
        row = c.execute("SELECT id FROM users WHERE role='admin'" + (" AND is_active::text IN ('1','true','t')" if active else '')
                        + ' ORDER BY id LIMIT 1').fetchone()
    return row['id'] if row else None


def post_execute(snapshot, approver):
    """Review + post each document still matching its preview amount. Each one alone: a failure never blocks the rest."""
    from app import finance_service as ledger
    actor = _actor()
    if not actor:
        return 'تعذر الترحيل: لا يوجد مستخدم مدير نشط في المنصة.'
    reason = f'ترحيل بأمر المدير عبر واتساب — نورة ({approver})'
    done, skipped = [], []
    for doc_id, amount in snapshot:
        with db() as c:
            row = c.execute('SELECT status, amount_minor FROM finance_documents WHERE id=%s', (doc_id,)).fetchone()
        if not row or row['status'] not in ('draft', 'reviewed') or row['amount_minor'] != amount:
            skipped.append(f'#{doc_id}: تغيّر أو رُحّل بعد التجهيز')
            continue
        try:
            ledger.review_document(doc_id, actor, {'confirmation': '1', 'reason': reason})
            ledger.post_document(doc_id, actor, {'confirmation': '1', 'reason': reason})
            done.append((doc_id, amount))
        except Exception as e:  # HTTPException from finance_service.fail, or a DB conflict
            skipped.append(f"#{doc_id}: {getattr(e, 'detail', None) or e}")
    out = [f'✅ رُحّل {len(done)} قيد بقيمة {sar(sum(a or 0 for _, a in done))}.']
    if skipped:
        out += [f'⚠️ لم يُرحّل {len(skipped)}:'] + [f'• {s}' for s in skipped[:20]]
    out.append('اكتب «نورة: فحص الحسابات» للتأكد بعد الترحيل.')
    return '\n'.join(out)
