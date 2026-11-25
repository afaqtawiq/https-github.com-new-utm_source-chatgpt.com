"""Customer statement for a period + payment allocation (builds on «تقارير شهرية ← كشف عميل»).

Owner, 25 Nov 2026: «يفصل رصيد الإقفال عن المتبقي للتحصيل اليوم، ويبيّن أي فاتورة سددتها كل دفعة. دفعة نوفمبر ما تغيّر إقفال
أكتوبر؛ تظهر كتحديث لاحق. وأي دفعة ما لها تخصيص مثبت تظهر لحالها، مو على أقدم فاتورة بالتخمين.» — and no posting needed
to get the report.

- Closing balance = the existing monthly statement (posted entries dated ≤ period end). Untouched by later payments.
- Later updates = posted movements dated after the period end up to today, listed apart.
- Drafts (not posted) are shown apart and give a second, provisional balance «شامل غير المرحّل»; never mixed silently.
- Allocation is PROVEN only by (1) an allocation recorded in the ledger, or (2) the receipt's own invoice number equal to
  exactly one claim's invoice number. Anything else stays «دفعة غير مخصصة» — no oldest-first guessing.
Read-only.
"""
import datetime as dt
import re

from app import finance_core as core
from app.storage import db

RIYADH = dt.timezone(dt.timedelta(hours=3))
DEBIT_KINDS = ('claim', 'opening_receivable', 'receivable_reconciliation')
CREDIT_KINDS = ('receipt', 'receivable_adjustment')
KIND_AR = {'claim': 'مطالبة', 'opening_receivable': 'رصيد افتتاحي', 'receivable_reconciliation': 'تصحيح ذمم',
           'receipt': 'سند قبض', 'receivable_adjustment': 'تسوية غير نقدية'}


def _ref(value):
    t = re.sub(r'[^0-9A-Za-z]', '', str(value or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))).upper()
    return t if len(t) >= 3 else ''


def _today():
    return dt.datetime.now(RIYADH).date()


def build(owner_id, counterparty_id, currency, start, end, today=None):
    from app import finance_monthly_service, finance_monthly_core as monthly
    today = today or _today()
    official = finance_monthly_service.statement_data(owner_id, counterparty_id, currency, start, end)
    start, end = monthly.period(start, end)
    cur = official['currency']
    with db() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        docs = [dict(r) for r in c.execute('''SELECT id, kind, status, amount_minor, document_date, invoice_ref, customs_ref,
              source_ref, reversed_at FROM finance_documents
            WHERE owner_id=%s AND counterparty_id=%s AND currency=%s AND kind = ANY(%s) AND status <> 'void' ORDER BY document_date, id''',
            (owner_id, counterparty_id, cur, list(DEBIT_KINDS + CREDIT_KINDS))).fetchall()]
        entries = [dict(r) for r in c.execute('''SELECT e.document_id, e.phase, e.signed_minor, e.created_at, d.document_date
            FROM finance_entries e JOIN finance_documents d ON d.id=e.document_id
            WHERE d.owner_id=%s AND d.counterparty_id=%s AND d.currency=%s AND e.side='receivable' ''',
            (owner_id, counterparty_id, cur)).fetchall()]
        allocs = [dict(r) for r in c.execute('''SELECT a.credit_id, a.document_id, a.amount_minor FROM finance_allocations a
            JOIN finance_documents d ON d.id=a.credit_id WHERE a.reversed_at IS NULL AND d.owner_id=%s AND d.counterparty_id=%s
            AND d.currency=%s ORDER BY a.id''', (owner_id, counterparty_id, cur)).fetchall()]
    by_id = {d['id']: d for d in docs}
    for e in entries:
        e['when'] = monthly.effective_date(e)
    posted_today = sum(e['signed_minor'] for e in entries if e['when'] <= today)
    later = sorted(({'id': e['document_id'], 'when': e['when'], 'signed': e['signed_minor'], 'phase': e['phase'],
                     'kind': by_id.get(e['document_id'], {}).get('kind', ''), 'ref': by_id.get(e['document_id'], {}).get('invoice_ref', '')}
                    for e in entries if end < e['when'] <= today), key=lambda x: (x['when'], x['id']))

    def sign(kind):
        return core.KINDS[kind][1]
    drafts = [d for d in docs if d['status'] in ('draft', 'reviewed')]
    draft_ok = [d for d in drafts if d['amount_minor'] and d['document_date']]
    draft_bad = [d for d in drafts if not (d['amount_minor'] and d['document_date'])]
    closing_incl = official['closing_minor'] + sum(sign(d['kind']) * d['amount_minor'] for d in draft_ok if d['document_date'] <= end)
    today_incl = posted_today + sum(sign(d['kind']) * d['amount_minor'] for d in draft_ok if d['document_date'] <= today)

    # ---- allocation: only what is proven ----
    live = [d for d in docs if (d['status'] == 'posted' or d in draft_ok) and d['document_date'] and d['document_date'] <= today]
    debits = [dict(d, left=d['amount_minor'], paid=[]) for d in live if d['kind'] in DEBIT_KINDS]
    credits = [dict(d, left=d['amount_minor'], uses=[]) for d in live if d['kind'] in CREDIT_KINDS]
    dmap, cmap = {d['id']: d for d in debits}, {d['id']: d for d in credits}
    for a in allocs:
        cr, db_ = cmap.get(a['credit_id']), dmap.get(a['document_id'])
        if not cr or not db_:
            continue
        take = min(a['amount_minor'], cr['left'], db_['left'])
        if take > 0:
            cr['left'] -= take
            db_['left'] -= take
            db_['paid'].append((cr, take, 'تخصيص مسجل'))
            cr['uses'].append((db_, take, 'تخصيص مسجل'))
    for cr in credits:
        ref = _ref(cr['invoice_ref'])
        if not ref or cr['left'] <= 0:
            continue
        hits = [d for d in debits if _ref(d['invoice_ref']) == ref]
        if len(hits) == 1 and hits[0]['left'] > 0:
            take = min(cr['left'], hits[0]['left'])
            cr['left'] -= take
            hits[0]['left'] -= take
            hits[0]['paid'].append((cr, take, 'رقم الفاتورة في سند القبض'))
            cr['uses'].append((hits[0], take, 'رقم الفاتورة في سند القبض'))
    unallocated = [cr for cr in credits if cr['left'] > 0]
    check = sum(d['left'] for d in debits) - sum(cr['left'] for cr in unallocated)
    return dict(official=official, today=today, posted_today=posted_today, later=later, drafts=draft_ok, draft_bad=draft_bad,
                closing_incl=closing_incl, today_incl=today_incl, debits=debits, unallocated=unallocated,
                balanced=(check == today_incl), check=check, currency=cur, end=end, start=start)


def money(minor, cur):
    return core.display_minor(minor, cur) + ' ' + cur


def signed(minor, cur):
    return money(abs(minor), cur) + (' دائن' if minor < 0 else ' مدين')


def summary_text(s):
    o, cur = s['official'], s['currency']
    out = [f"📄 كشف {o['counterparty_name']} — {o['start']} إلى {o['end']} ({cur})",
           f"• رصيد الإقفال في {o['end']} (مرحّل): {money(o['closing_minor'], cur)}"]
    if s['later']:
        out.append(f"• تحديثات بعد الإقفال حتى {s['today']}: {len(s['later'])} حركة صافيها {signed(sum(x['signed'] for x in s['later']), cur)} — لا تغيّر الإقفال")
    out.append(f"• المتبقي للتحصيل اليوم (مرحّل): {money(s['posted_today'], cur)}")
    if s['drafts'] or s['draft_bad']:
        out.append(f"• شامل غير المرحّل ({len(s['drafts'])} مسودة) — مبدئي: إقفال {money(s['closing_incl'], cur)} | اليوم {money(s['today_incl'], cur)}")
    if s['draft_bad']:
        out.append(f"⚠️ {len(s['draft_bad'])} مسودة بدون مبلغ أو تاريخ — غير محسوبة")
    if s['unallocated']:
        out.append(f"💳 دفعات بدون تخصيص مثبت: {len(s['unallocated'])} بمبلغ {money(sum(x['left'] for x in s['unallocated']), cur)} — معروضة لحالها")
    open_ = [d for d in s['debits'] if d['left'] > 0]
    out.append(f"🧾 فواتير مفتوحة اليوم: {len(open_)} بمبلغ {money(sum(d['left'] for d in open_), cur)}")
    out.append('✅ المطابقة: المفتوح − غير المخصص = الرصيد اليوم' if s['balanced']
               else f"⚠️ فرق مطابقة {money(s['today_incl'] - s['check'], cur)} — راجع القيود العكسية في الملف")
    return '\n'.join(out)


def _doc(d, cur):
    st = '' if d['status'] == 'posted' else ' (غير مرحّل)'
    return f"#{d['id']} {KIND_AR.get(d['kind'], d['kind'])}{st} {d['document_date']} فاتورة {d['invoice_ref'] or '—'}"


def pdf(s):
    from app.finance_monthly_pdf import Report
    from app import finance_monthly_view as view
    o, cur = s['official'], s['currency']
    r = Report('كشف حساب عميل مع تخصيص الدفعات', f"{o['owner_name']} | {o['counterparty_name']} | {o['start']} - {o['end']} | {cur}")
    r.line('أ) الفترة (القيود المرحّلة)', bold=True, size=13)
    for key, label in (('opening', 'الرصيد قبل بداية الفترة'), ('claims', 'مطالبات الفترة'), ('receipts', 'القبض خلال الفترة'),
                       ('adjustments', 'التسويات غير النقدية'), ('opening_movements', 'أرصدة افتتاحية'), ('reversals', 'صافي القيود العكسية'),
                       ('closing', 'رصيد الإقفال في ' + o['end'])):
        r.line(f"{label}: {o[key + '_display']} {cur}", bold=key == 'closing')
    from app.finance_pdf_table import table
    if o['movements']:
        table(r, ['التاريخ', 'الحركة', 'رقم', 'فاتورة', 'مدين', 'دائن', 'الرصيد', '✓'],
              [[m['effective_date'], ('عكس ' if m['phase'] == 'reversal' else '') + view.LABELS.get(m['kind'], m['kind']), '#' + str(m['document_id']),
                m.get('invoice_ref') or '—', m['debit_display'], m['credit_display'], m['running_display'], '☐'] for m in o['movements']],
              [.13, .16, .08, .14, .13, .13, .16, .07])
    r.rule()
    r.line(f"ب) تحديثات بعد الإقفال حتى {s['today']} (لا تغيّر رصيد الإقفال)", bold=True, size=13)
    if not s['later']:
        r.line('لا توجد حركات مرحّلة بعد نهاية الفترة.')
    if s['later']:
        table(r, ['التاريخ', 'الحركة', 'رقم', 'فاتورة', 'المبلغ', '✓'],
              [[str(x['when']), ('عكس ' if x['phase'] == 'reversal' else '') + KIND_AR.get(x['kind'], x['kind']), '#' + str(x['id']),
                x['ref'] or '—', signed(x['signed'], cur), '☐'] for x in s['later']], [.15, .2, .1, .2, .25, .1])
    r.line(f"المتبقي للتحصيل اليوم (مرحّل): {money(s['posted_today'], cur)}", bold=True)
    r.rule()
    r.line('ج) قيود غير مرحّلة (مسودات) — مبدئي', bold=True, size=13)
    if not s['drafts'] and not s['draft_bad']:
        r.line('لا توجد مسودات لهذا العميل بهذه العملة.')
    if s['drafts']:
        table(r, ['التاريخ', 'الحركة', 'رقم', 'فاتورة', 'المبلغ', 'المصدر', '✓'],
              [[str(d['document_date']), KIND_AR.get(d['kind'], d['kind']) + (' (مراجعة)' if d['status'] == 'reviewed' else ''), '#' + str(d['id']),
                d['invoice_ref'] or '—', signed(core.KINDS[d['kind']][1] * d['amount_minor'], cur), d['source_ref'] or '—', '☐'] for d in s['drafts']],
              [.13, .17, .08, .15, .17, .23, .07])
    for d in s['draft_bad']:
        r.line(f"#{d['id']} {KIND_AR.get(d['kind'], d['kind'])}: المبلغ أو التاريخ غير مكتمل — غير محسوب", size=9)
    r.line(f"رصيد الإقفال شامل غير المرحّل: {money(s['closing_incl'], cur)} | المتبقي اليوم شامل غير المرحّل: {money(s['today_incl'], cur)}", bold=True)
    r.rule()
    r.line('د) الفواتير وما سددها (تخصيص مثبت فقط)', bold=True, size=13)
    rows = []
    for d in s['debits']:
        state = 'مسددة' if d['left'] == 0 else ('مسددة جزئيًا' if d['paid'] else 'غير مسددة')
        by = '؛ '.join(f"#{cr['id']} {cr['document_date']} {money(amt, cur)} ({how}){' بعد الإقفال' if cr['document_date'] > s['end'] else ''}"
                      for cr, amt, how in d['paid']) or '—'
        rows.append([str(d['document_date']), '#' + str(d['id']) + ('' if d['status'] == 'posted' else ' غير مرحّل'), d['invoice_ref'] or '—',
                     money(d['amount_minor'], cur), by, state, money(d['left'], cur), '☐'])
    if rows:
        table(r, ['التاريخ', 'المطالبة', 'فاتورة', 'المبلغ', 'سددها (الدفعة، التاريخ، المبلغ، الإثبات)', 'الحالة', 'المتبقي اليوم', '✓'], rows,
              [.13, .11, .09, .12, .27, .09, .13, .06])
    else:
        r.line('لا توجد مطالبات.')
    r.rule()
    r.line('هـ) دفعات بدون تخصيص مثبت (لم تُنسب لأي فاتورة)', bold=True, size=13)
    if not s['unallocated']:
        r.line('لا توجد.')
    if s['unallocated']:
        table(r, ['التاريخ', 'الدفعة', 'فاتورة مذكورة', 'مبلغ الدفعة', 'غير مخصص', 'ملاحظة', '✓'],
              [[str(cr['document_date']), '#' + str(cr['id']) + ('' if cr['status'] == 'posted' else ' غير مرحّل'), cr['invoice_ref'] or '—',
                money(cr['amount_minor'], cur), money(cr['left'], cur), 'بعد الإقفال' if cr['document_date'] > s['end'] else 'ضمن الفترة', '☐']
               for cr in s['unallocated']], [.13, .15, .15, .16, .16, .17, .08])
    r.rule()
    r.line(('مطابقة: مجموع المتبقي على الفواتير − الدفعات غير المخصصة = المتبقي اليوم شامل غير المرحّل ✓') if s['balanced'] else
           f"تنبيه مطابقة: المتبقي على الفواتير − غير المخصص = {money(s['check'], cur)} مقابل {money(s['today_incl'], cur)}", bold=True)
    r.line('التخصيص المثبت = تخصيص مسجل في الحسابات، أو رقم فاتورة مكتوب في سند القبض يطابق فاتورة واحدة. لا يُنسب أي سداد لأقدم فاتورة بالتخمين. الكشف للمراجعة وليس فاتورة ضريبية.', size=9)
    return r.finish()


def find(name, currency='SAR', owner=None):
    """→ (owner_id, counterparty_id, label) or an Arabic question when ambiguous."""
    with db() as c:
        parties = c.execute("""SELECT id, name FROM finance_party_display WHERE kind='counterparty' AND name ILIKE %s ORDER BY name LIMIT 8""",
                            ('%' + name.strip() + '%',)).fetchall()
        if not parties:
            return None, f'ما لقيت عميل اسمه «{name}» في الحسابات.'
        exact = [p for p in parties if p['name'].strip() == name.strip()]
        if len(parties) > 1 and len(exact) != 1:
            return None, 'أي عميل تقصد؟ ' + '، '.join(p['name'] for p in parties)
        party = exact[0] if exact else parties[0]
        owners = c.execute("""SELECT DISTINCT d.owner_id, o.name FROM finance_documents d JOIN finance_party_display o ON o.id=d.owner_id
            WHERE d.counterparty_id=%s AND d.currency=%s AND d.status<>'void'""", (party['id'], currency)).fetchall()
    if owner:
        owners = [o for o in owners if owner.strip() in o['name']]
    if not owners:
        return None, f"لا توجد حركات بالريال/{currency} للعميل {party['name']}."
    if len(owners) > 1:
        return None, 'العميل له حسابات عند أكثر من جهة؛ حدد: ' + '، '.join(o['name'] for o in owners)
    return (owners[0]['owner_id'], party['id'], party['name']), ''


def run(name, start, end, currency='SAR', owner=None, chat=None):
    found, msg = find(name, currency, owner)
    if not found:
        return msg
    try:
        s = build(found[0], found[1], currency, start, end)
    except ValueError as exc:
        return str(exc)
    text = summary_text(s)
    if chat and chat[0] and chat[1] and chat[0] != 'office':
        from app.advance_reconcile import send_pdf
        from app.transport_desk import run_async
        sent = run_async(lambda: send_pdf(chat, pdf(s), f'Afaq-Statement-{found[1]}-{s["official"]["end"]}.pdf',
                                          f'كشف {found[2]} مع تخصيص الدفعات'), timeout=90)
        text += '\n📎 أرسلت الكشف بندًا بندًا ملف PDF.' if sent else '\n⚠️ تعذر إرسال ملف PDF الآن.'
    return text
