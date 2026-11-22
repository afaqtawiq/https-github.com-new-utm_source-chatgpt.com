"""Owner (22 Nov 2026): «أكثر من 20 بيان والمحاسبة مسجل بيان واحد — إيش المشكلة بالضبط؟»

Matches every declaration the agent has seen in FASAH this month (fasah_status, filled by every FASAH list read) with
the billing records (billing_declarations), and says for EACH unrecorded one why it is not in the accounts:
- it is not a سلة الرحائب declaration → there is no billing rule for that importer (the automatic billing only covers
  سلة الرحائب: الياسمين / عمران / نصيب سلة);
- its billing read failed or is incomplete (review status);
- it was read but the manager's «نفذ» code was never confirmed (or expired);
- it was never read by the billing runner yet.
Read-only: records nothing.
"""
import datetime as dt
import re

RIYADH = dt.timezone(dt.timedelta(hours=3))
KIND_AR = {'import': 'وارد', 'export': 'صادر'}


def _date(text):
    text = str(text or '').strip()
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', text)
    if m:
        try:
            return dt.date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            return None
    return None


def _party(details):
    t = str(details or '')
    for name in ('سلة', 'ياسمين', 'عمران'):
        if name in t:
            return name
    m = re.search(r'(?:المستورد|المصدر|اسم)[:\s]+([^\n|،,]{3,60})', t)
    return (m.group(1).strip() if m else t[:60].strip()) or 'غير معروف'


def report(month=None):
    from app.storage import db
    month = month or dt.datetime.now(RIYADH).strftime('%Y-%m')
    y, m = int(month[:4]), int(month[5:7])
    with db() as c:
        if not c.execute("SELECT to_regclass('fasah_status') t").fetchone()['t']:
            return 'ما فيه قراءة لقائمة البيانات من فسح بعد؛ اطلب «افتح فسح» أولًا.'
        seen = c.execute('SELECT number, kind, declared_on, details, stage, first_seen FROM fasah_status').fetchall()
        billed = {}
        if c.execute("SELECT to_regclass('billing_declarations') t").fetchone()['t']:
            billed = {(r['number'], r['kind']): r for r in
                      c.execute('SELECT number, kind, status, party, error FROM billing_declarations').fetchall()}
        read = set()
        if c.execute("SELECT to_regclass('fasah_billing_items') t").fetchone()['t']:
            read = {str(r['number']) for r in c.execute('SELECT number FROM fasah_billing_items WHERE ok').fetchall()}
        last = c.execute('SELECT MAX(seen_at) t FROM fasah_status').fetchone()['t']
    rows = []
    for r in seen:
        d = _date(r['declared_on']) or (r['first_seen'].astimezone(RIYADH).date() if r.get('first_seen') else None)
        if d and (d.year, d.month) == (y, m):
            rows.append(r)
    if not rows:
        return f'ما لقيت بيانات لشهر {month} في آخر قراءة لفسح.'
    from app.billing_rules import flat_rate as flat_of, is_salla
    recorded, groups, flat_items = [], {}, []
    for r in sorted(rows, key=lambda x: x['number']):
        key, label = (r['number'], r['kind']), f"{r['number']} ({KIND_AR.get(r['kind'], r['kind'])})"
        b = billed.get(key)
        party = _party(r['details'])
        if b and b['status'] not in ('drafting', 'incomplete', 'recording', 'failed'):
            recorded.append(label)
            continue
        if b:
            why = 'قراءة الفاتورة/الرسوم ناقصة أو فشلت — تحتاج مراجعة' + (f": {str(b['error'])[:60]}" if b.get('error') else '')
        elif flat_of(r['details']):
            why = f"عميل بسعر ثابت ({flat_of(r['details'])[0]}) — جاهز للتسجيل برمز «نفذ» أدناه"
            flat_items.append({'number': r['number'], 'kind': r['kind'], 'party': flat_of(r['details'])[0],
                               'date': str(_date(r['declared_on']) or '') or None})
        elif not is_salla(r['details']):
            why = f'ليس بيان سلة الرحائب ({party}) — الفوترة التلقائية تغطي سلة الرحائب فقط، ولا توجد قاعدة تسعير لهذا المستورد'
        elif r['number'] in read:
            why = 'قُرئت فاتورته من فسح وانتظر رمز «نفذ» للتسجيل، والرمز ما اعتُمد (أو انتهت مدته)'
        else:
            why = 'لم يقرأ جهاز العمل فاتورته ورسومه من فسح بعد'
        groups.setdefault(why, []).append(label)
    stamp = last.astimezone(RIYADH).strftime('%d/%m %H:%M') if last else '—'
    out = [f'🔎 مطابقة فسح مع الحسابات — {month} (آخر قراءة لفسح {stamp})',
           f'• بيانات الشهر في فسح: {len(rows)}', f'• مسجلة في الحسابات: {len(recorded)}',
           f'• غير مسجلة: {len(rows) - len(recorded)}']
    for why, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        out.append(f'\n❗ {why} ({len(items)}):\n  ' + '، '.join(items[:40]) + (' …' if len(items) > 40 else ''))
    if flat_items:
        try:
            from app.agent_runner import prepare_billing
            code = prepare_billing(flat_items, f'{len(flat_items)} بيان لعملاء بسعر ثابت')
        except Exception as exc:
            code = None
            print('BILLING_GAP_FLAT', type(exc).__name__, str(exc)[:120], flush=True)
        out.append(f'\n✅ لتسجيل {len(flat_items)} بيان لعملاء السعر الثابت مسودات في الحسابات اكتب: نفذ {code}' if code
                   else '\n(تعذر تجهيز رمز التسجيل الآن — لا توجد محادثة مدير معروفة.)')
    out.append('\nالعلاج:'
               '\n- بيانات سلة غير المقروءة أو المنتهية رموزها: اكتب لنورة «سجل حسابات سلة من فسح»، وأكّد الرمز الواحد اللي يجيك بـ«نفذ».'
               '\n- بيانات المستوردين الآخرين: تحتاج سعر تخليص لكل مستورد (قاعدة فوترة) قبل ما تُسجل تلقائيًا.'
               '\n- المحتاجة مراجعة: افتحها مع نورة بالرقم.')
    return '\n'.join(out)
