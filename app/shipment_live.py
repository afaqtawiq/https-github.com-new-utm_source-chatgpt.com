"""Live shipment file — PILOT, read-only (owner, 25 Nov 2026: «ملف حي لكل شحنة»).

Built ON the existing records, no second system:
- shipment_files (one file per bill of lading, team stage + history)   — app/shipment_files.py
- fasah_status (+ runner_tasks reads) — live FASAH declaration status    — app/fasah_tracking.py
- shipment_tracks — sea tracking (ETA / arrival)                         — app/shipment_tracking.py
- container_returns — containers, documented last free day, return     — app/container_returns.py, app/line_desk.py
- staff_documents — documents sent on WhatsApp with their read fields   — app/staff_documents.py

card(bill) gives, for each shipment: the latest DOCUMENTED status with its source and time, what is blocking it, who
owns the next step and by when. A FASAH status is shown as current only while it is fresh (seen in a recent FASAH list
read); an old one is shown as «آخر حالة معروفة — قديمة» and never as the current status.

link_document(fields) attaches a WhatsApp document to a shipment ONLY by an exact reference (bill of lading,
declaration number or container number) that points to exactly one shipment; a document with no reference or with
references pointing to more than one shipment goes to the review list — never merged automatically (unlike the party-
name fallback of shipment_workflow.note_document).

free_day_alerts() lists, for the team only, containers whose DOCUMENTED last free day is near (an estimated date never
raises an alert). Nothing here sends WhatsApp, posts finance entries or changes the existing records; the only writes
are to the pilot's own two tables (links and review queue).
"""
import datetime as dt
import html
import json
import re

from app.storage import db, utcnow

RIYADH = dt.timezone(dt.timedelta(hours=3))
FRESH_HOURS = 6          # FASAH is read every 2 h (7:00–23:00); older than this is not «current»
READ_GRACE_MIN = 30      # a declaration missing from a later successful read is stale too
ALERT_DAYS = 2           # team alert from 2 days before the documented last free day


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS shipment_live_links(doc_id BIGINT PRIMARY KEY, bill_no TEXT NOT NULL,
            matched_by TEXT NOT NULL, matched_value TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS shipment_live_review(doc_id BIGINT PRIMARY KEY, reason TEXT NOT NULL,
            refs_json TEXT NOT NULL DEFAULT '{}', candidates_json TEXT NOT NULL DEFAULT '[]', created_at TIMESTAMPTZ NOT NULL)''')


def _has(c, table):
    return bool(c.execute('SELECT to_regclass(%s) t', (table,)).fetchone()['t'])


def _bill(v):
    return re.sub(r'[^A-Za-z0-9]', '', str(v or '')).upper()[:40]


def _when(t):
    if not t:
        return '—'
    if isinstance(t, dt.datetime):
        return t.astimezone(RIYADH).strftime('%d/%m/%Y %H:%M')
    return t.strftime('%d/%m/%Y')


# ---------- evidence ----------

def _declared(value):
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return dt.datetime.strptime(str(value or '').strip(), fmt).date()
        except ValueError:
            pass
    return None


def covering_reads(c, row, after):
    """Successful, COMPLETE FASAH list reads after `after` whose scope includes this declaration: same list (import/
    export), date window reaching its declaration date, and no importer filter other than its own. A read of other
    shipments (another importer's filtered list), a read that stopped at its page limit, or a read with no coverage
    proof (older runner) never counts."""
    if not _has(c, 'runner_tasks'):
        return []
    declared = _declared(row.get('declared_on'))
    party = str(row.get('party') or '')
    out = []
    for t in c.execute("""SELECT id, params_json, result_json, COALESCE(finished_at, created_at) AS at FROM runner_tasks
            WHERE kind='fasah_declarations' AND status='done' AND COALESCE(finished_at, created_at) > %s
            ORDER BY COALESCE(finished_at, created_at) DESC""", (after,)).fetchall():
        try:
            params, res = json.loads(t['params_json'] or '{}'), json.loads(t['result_json'] or '{}')
        except ValueError:
            continue
        cov = res.get('coverage') if isinstance(res, dict) else None
        if not isinstance(cov, dict) or cov.get('complete') is not True:
            continue
        if (cov.get('which') or params.get('which') or 'import') != row['kind']:
            continue
        read_party = str(cov.get('party') or params.get('party') or '')
        if read_party and read_party not in party:
            continue
        since = _declared(cov.get('since') or params.get('since'))
        if since and (declared is None or declared < since):
            continue
        out.append(t['at'])
    return out


def fasah_evidence(c, file, now):
    """The FASAH row for this shipment (by declaration number, else by the bill as its reference) with its state:
    current (seen in a read within FRESH_HOURS), missing (absent from a later complete read covering it) or
    unverified (old, and no later complete read covers it) — the last two are shown only as «آخر حالة معروفة»."""
    if not _has(c, 'fasah_status'):
        return None
    row = None
    if file.get('declaration_no'):
        row = c.execute('SELECT * FROM fasah_status WHERE number=%s ORDER BY seen_at DESC LIMIT 1', (file['declaration_no'],)).fetchone()
    if not row:
        rows = c.execute("SELECT * FROM fasah_status WHERE upper(regexp_replace(ref,'[^A-Za-z0-9]','','g'))=%s", (file['bill_no'],)).fetchall()
        row = rows[0] if len(rows) == 1 else None
    if not row:
        return None
    from app.fasah_tracking import LABELS
    row = dict(row)
    age_h = (now - row['seen_at']).total_seconds() / 3600
    fresh = age_h <= FRESH_HOURS
    proof = covering_reads(c, row, row['seen_at'] + dt.timedelta(minutes=READ_GRACE_MIN)) if not fresh else []
    if fresh:
        why, state = '', 'current'
    elif proof:
        why, state = f'لم يظهر في قراءة كاملة لفسح تشمل نطاقه ({_when(proof[0])})', 'missing'
    else:
        why, state = 'تعذر التحقق: لا توجد قراءة كاملة أحدث تشمل هذا البيان', 'unverified'
    return {'stage': row['stage'], 'label': LABELS.get(row['stage'], row['details'] or row['stage']), 'number': row['number'],
            'seen_at': row['seen_at'], 'changed_at': row['changed_at'], 'duties_since': row.get('duties_since'),
            'fresh': fresh, 'state': state, 'why_stale': why}


def tracking_evidence(c, file):
    if not _has(c, 'shipment_tracks'):
        return None
    row = c.execute("SELECT * FROM shipment_tracks WHERE upper(regexp_replace(ref,'[^A-Za-z0-9]','','g'))=%s", (file['bill_no'],)).fetchone()
    if not row or not (row.get('checked_at') or row.get('eta')):
        return None
    return {'arrived': bool(row['arrived']), 'eta': row.get('eta'), 'checked_at': row.get('checked_at'), 'last_event': row.get('last_event')}


def containers_evidence(c, file):
    if not _has(c, 'container_returns'):
        return []
    boxes = json.loads(file.get('containers') or '[]')
    rows = c.execute('''SELECT * FROM container_returns WHERE NOT COALESCE(is_test,FALSE)
        AND (upper(regexp_replace(COALESCE(bill,''),'[^A-Za-z0-9]','','g'))=%s OR container = ANY(%s)) ORDER BY container''',
                     (file['bill_no'], boxes)).fetchall()
    return [dict(r) for r in rows]


def review_docs(c, file):
    if not _has(c, 'shipment_live_review'):
        return []
    out = []
    for r in c.execute('SELECT * FROM shipment_live_review ORDER BY created_at').fetchall():
        if file['bill_no'] in json.loads(r['candidates_json'] or '[]'):
            out.append(r)
    return out


# ---------- the card ----------

def build(file, now=None):
    """One live card from a shipment_files row (dict). Pure read."""
    now = now or utcnow()
    today = now.astimezone(RIYADH).date()
    with db() as c:
        fasah = fasah_evidence(c, file, now)
        track = tracking_evidence(c, file)
        boxes = containers_evidence(c, file)
        pending = review_docs(c, file)
        linked = c.execute('SELECT COUNT(*) n FROM shipment_live_links WHERE bill_no=%s', (file['bill_no'],)).fetchone()['n'] \
            if _has(c, 'shipment_live_links') else 0
    from app.shipment_files import STAGE_AR
    open_boxes = [b for b in boxes if b.get('status') not in ('returned', 'closed')]
    documented = [b for b in open_boxes if b.get('free_until') and not b.get('free_until_estimated')]
    earliest = min((b['free_until'] for b in documented), default=None)

    # 1) latest documented status: most advanced trustworthy fact, each with its source and time.
    status = source = None
    at = None
    stale = None
    if boxes and not open_boxes:
        status, source, at = 'أُرجعت الحاويات فارغة (بإثبات)', 'سجل إرجاع الحاويات', max(b['updated_at'] for b in boxes)
    elif any(b.get('delivered_on') for b in open_boxes):
        last = max(b['delivered_on'] for b in open_boxes if b.get('delivered_on'))
        status, source, at = 'سُلّمت للعميل — بانتظار إرجاع الفارغ', 'سجل الحاويات', last
    if fasah and not status:
        if fasah['fresh']:
            status, source, at = fasah['label'] + f" (بيان {fasah['number']})", 'فسح — قراءة جهاز العمل', fasah['seen_at']
        else:
            stale = fasah
    if not status and track:
        if track['arrived']:
            status, source, at = 'وصلت الميناء', 'تتبع الخط الملاحي', track['checked_at'] or track['eta']
        elif track['eta']:
            status, source, at = 'في الطريق — الوصول المتوقع ' + _when(track['eta']), 'تتبع الخط الملاحي', track['checked_at']
    if not status:
        label = STAGE_AR.get(file.get('stage'), (file.get('stage'), ''))[0]
        status, source, at = label, 'تحديث الفريق في ملف الشحنة', file.get('updated_at')

    # 2) what blocks it, 3) who owns the next step and by when (only from documented facts).
    blocker, owner, due = None, None, None
    if stale:
        blocker = ('البيان غاب عن قراءة فسح الكاملة — ' if stale['state'] == 'missing' else 'حالة فسح غير مؤكدة — ') + stale['why_stale']
        owner, due = 'فيصل (التخليص)', 'اليوم — قراءة فسح جديدة قبل أي إبلاغ'
    elif fasah and fasah['stage'] == 'duties_due':
        since = fasah.get('duties_since') or fasah['changed_at']
        blocker = 'بانتظار سداد الرسوم الجمركية منذ ' + _when(since)
        owner, due = 'نورة (المالية) / العميل', _when((since + dt.timedelta(days=1)))
    elif fasah and fasah['stage'] == 'inspection':
        blocker, owner, due = 'تحت الكشف / المعاينة', 'فيصل / الميدان', 'اليوم'
    elif fasah and fasah['stage'] == 'not_arrived':
        blocker, owner = 'البيان مقدّم والشحنة لم تصل المنفذ', 'سلطان (الحاويات)'
        due = _when(track['eta']) if track and track.get('eta') else 'عند الوصول'
    elif fasah and fasah['stage'] == 'released' and open_boxes and not any(b.get('delivered_on') for b in open_boxes):
        blocker, owner = None, 'خالد (النقل) — إسناد الشاحنات وسحب الحاويات'
        due = _when(earliest) + ' (آخر يوم مجاني موثّق)' if earliest else 'اليوم'
    elif not fasah and track and track['arrived'] and not file.get('declaration_no'):
        blocker, owner, due = 'وصلت الشحنة ولا يوجد بيان مسجل', 'فيصل (التخليص)', 'اليوم'
    elif open_boxes and any(b.get('delivered_on') for b in open_boxes):
        owner = 'سلطان (الحاويات) — إرجاع الفارغ'
        due = _when(earliest) + ' (آخر يوم مجاني موثّق)' if earliest else 'آخر يوم مجاني غير موثّق — يلزم تأكيده'
    if pending:
        blocker = (blocker + ' + ' if blocker else '') + f'{len(pending)} مستند بانتظار المطابقة'
        owner = owner or 'فيصل (التخليص) — مطابقة المستند'
    if not owner:
        owner, due = STAGE_AR.get(file.get('stage'), ('', '—'))[1] or '—', '—'

    alerts = []
    for b in documented:
        days = (b['free_until'] - today).days
        if days <= ALERT_DAYS:
            alerts.append(f"{b['container']}: آخر يوم مجاني {_when(b['free_until'])} "
                          + ('(اليوم)' if days == 0 else f'(متأخرة {-days} يوم)' if days < 0 else f'(باقي {days} يوم)'))
    estimated = [b['container'] for b in open_boxes if b.get('free_until') and b.get('free_until_estimated')]
    return {'bill_no': file['bill_no'], 'customer': file.get('customer') or '', 'port': file.get('pod') or '',
            'declaration_no': file.get('declaration_no') or (fasah or {}).get('number') or '',
            'status': status, 'source': source, 'at': at, 'stale_fasah': stale,
            'blocker': blocker, 'owner': owner, 'due': due or '—', 'alerts': alerts, 'estimated_free_days': estimated,
            'containers': [b['container'] for b in boxes] or json.loads(file.get('containers') or '[]'),
            'linked_docs': linked, 'review_docs': len(pending)}


def card(bill, now=None):
    from app.shipment_files import init as files_init
    files_init()
    init()
    with db() as c:
        row = c.execute('SELECT * FROM shipment_files WHERE bill_no=%s', (_bill(bill),)).fetchone()
    return build(dict(row), now) if row else None


def card_text(k):
    lines = [f"📁 {k['bill_no']} — {k['customer'] or 'عميل غير مسجل'}" + (f" — بيان {k['declaration_no']}" if k['declaration_no'] else ''),
             f"📍 آخر حالة موثّقة: {k['status']}", f"   المصدر: {k['source']} — {_when(k['at'])}"]
    if k['stale_fasah']:
        s = k['stale_fasah']
        lines.append(f"⚠️ آخر حالة معروفة في فسح: {s['label']} — {_when(s['seen_at'])} (ليست الحالة الحالية: {s['why_stale']})")
    lines.append('⛔ الموقف: ' + (k['blocker'] or 'لا يوجد عائق موثّق'))
    lines.append(f"➡️ الخطوة الجاية: {k['owner']} — الموعد: {k['due']}")
    for a in k['alerts']:
        lines.append('🔔 ' + a)
    if k['estimated_free_days']:
        lines.append('ℹ️ آخر يوم مجاني تقديري (لا تنبيه حتى يتأكد): ' + '، '.join(k['estimated_free_days']))
    return '\n'.join(lines)


# ---------- documents ----------

def refs_of(fields):
    fields = fields or {}
    bills = {_bill(fields.get(k)) for k in ('bill_no', 'bl_number', 'bill_of_lading') if _bill(fields.get(k))}
    decls = {re.sub(r'\D', '', str(fields.get(k) or '')) for k in ('declaration_number', 'declaration_no') if re.sub(r'\D', '', str(fields.get(k) or ''))}
    boxes = set()
    for raw in fields.get('container_numbers') or []:
        n = re.sub(r'\s', '', str(raw)).upper()
        if re.fullmatch(r'[A-Z]{4}\d{7}', n):
            boxes.add(n)
    return {'bill': sorted(bills), 'declaration': sorted(decls), 'container': sorted(boxes)}


NAME_KEYS = ('consignee', 'importer', 'buyer', 'customer', 'party')
REF_AR = {'bill': 'البوليصة', 'declaration': 'رقم البيان', 'container': 'الحاوية'}


def resolve(c, kind, value):
    """The set of shipments one reference points to."""
    out = set()
    if kind == 'bill':
        out |= {r['bill_no'] for r in c.execute('SELECT bill_no FROM shipment_files WHERE bill_no=%s', (value,)).fetchall()}
    elif kind == 'declaration':
        out |= {r['bill_no'] for r in c.execute('SELECT bill_no FROM shipment_files WHERE declaration_no=%s', (value,)).fetchall()}
        if _has(c, 'fasah_status'):
            out |= {r['bill_no'] for r in c.execute("""SELECT f.bill_no FROM fasah_status s JOIN shipment_files f
                ON upper(regexp_replace(s.ref,'[^A-Za-z0-9]','','g'))=f.bill_no WHERE s.number=%s""", (value,)).fetchall()}
    elif kind == 'container':
        out |= {r['bill_no'] for r in c.execute('SELECT bill_no FROM shipment_files WHERE containers LIKE %s', ('%' + value + '%',)).fetchall()}
    return out


def decide(c, refs, fields):
    """(bill, how, [bill]) only when EVERY reference on the document points to the same single shipment;
    else (None, reason, candidates). A customer name alone is never a reference."""
    pairs = [(k, v) for k, vs in refs.items() for v in vs]
    if not pairs:
        named = any(str((fields or {}).get(k) or '').strip() for k in NAME_KEYS)
        return None, ('name_only' if named else 'no_reference'), []
    sets = [(k, v, resolve(c, k, v)) for k, v in pairs]
    every = set().union(*(x for _, _, x in sets))
    if any(not x for _, _, x in sets):
        return None, 'unknown_reference', sorted(every)
    if len(every) != 1:
        return None, 'ambiguous', sorted(every)
    bill = next(iter(every))
    return bill, ' + '.join(sorted({REF_AR[k] for k, _, _ in sets})), [bill]


def link_document(doc_id, fields):
    """All references agree on one shipment → linked; otherwise → review. Returns ('linked', bill) or ('review', reason)."""
    init()
    refs = refs_of(fields)
    with db() as c:
        done = c.execute('SELECT bill_no FROM shipment_live_links WHERE doc_id=%s', (doc_id,)).fetchone()
        if done:
            return 'linked', done['bill_no']
        bill, how, cands = decide(c, refs, fields)
        if bill:
            c.execute("""INSERT INTO shipment_live_links(doc_id,bill_no,matched_by,matched_value,created_at) VALUES(%s,%s,%s,%s,%s)
                ON CONFLICT(doc_id) DO NOTHING""", (doc_id, bill, how, json.dumps(refs, ensure_ascii=False), utcnow()))
            c.execute('DELETE FROM shipment_live_review WHERE doc_id=%s', (doc_id,))
            return 'linked', bill
        c.execute("""INSERT INTO shipment_live_review(doc_id,reason,refs_json,candidates_json,created_at) VALUES(%s,%s,%s,%s,%s)
            ON CONFLICT(doc_id) DO UPDATE SET reason=EXCLUDED.reason, refs_json=EXCLUDED.refs_json, candidates_json=EXCLUDED.candidates_json""",
                  (doc_id, how, json.dumps(refs, ensure_ascii=False), json.dumps(cands), utcnow()))
        return 'review', how


REASON_AR = {'no_reference': 'لا يحمل رقم بوليصة أو بيان أو حاوية', 'ambiguous': 'المراجع تشير لأكثر من شحنة',
             'unknown_reference': 'فيه مرجع لا يطابق أي شحنة مسجلة', 'name_only': 'ما فيه إلا اسم العميل — لا يُربط بالاسم'}


def link_recent(hours=72):
    """Run the linker over the WhatsApp documents still kept (staff_documents, read fields). Read-only on them."""
    init()
    with db() as c:
        if not _has(c, 'staff_documents'):
            return {'linked': 0, 'review': 0}
        rows = c.execute("SELECT id, fields FROM staff_documents WHERE created_at > NOW() - make_interval(hours => %s)", (hours,)).fetchall()
    out = {'linked': 0, 'review': 0}
    for r in rows:
        try:
            state, _ = link_document(r['id'], json.loads(r['fields'] or '{}'))
            out[state] += 1
        except ValueError:
            out['review'] += 1
    return out


def review_text():
    init()
    with db() as c:
        rows = c.execute('''SELECT r.*, d.filename FROM shipment_live_review r LEFT JOIN staff_documents d ON d.id=r.doc_id
            ORDER BY r.created_at DESC LIMIT 20''').fetchall() if _has(c, 'staff_documents') else \
            c.execute('SELECT *, NULL AS filename FROM shipment_live_review ORDER BY created_at DESC LIMIT 20').fetchall()
    if not rows:
        return 'لا توجد مستندات بانتظار المطابقة.'
    out = ['📎 مستندات بانتظار المطابقة (لم تُدمج تلقائيًا):']
    for r in rows:
        refs = json.loads(r['refs_json'] or '{}')
        names = {'bill': 'بوليصة', 'declaration': 'بيان', 'container': 'حاوية'}
        shown = '، '.join(f'{names.get(k, k)} {", ".join(v)}' for k, v in refs.items() if v) or '—'
        cands = json.loads(r['candidates_json'] or '[]')
        out.append(f"• {r['filename'] or 'مستند #' + str(r['doc_id'])} — {REASON_AR.get(r['reason'], r['reason'])}\n   المراجع: {shown}"
                   + (f"\n   الشحنات المحتملة: {'، '.join(cands)}" if cands else ''))
    return '\n'.join(out)


# ---------- internal alerts ----------

def free_day_alerts(now=None):
    """Team-only list: open containers whose DOCUMENTED last free day is within ALERT_DAYS (or passed)."""
    now = now or utcnow()
    today = now.astimezone(RIYADH).date()
    with db() as c:
        if not _has(c, 'container_returns'):
            return []
        cols = {r['column_name'] for r in c.execute("""SELECT column_name FROM information_schema.columns
            WHERE table_name='container_returns' AND table_schema=current_schema()""").fetchall()}
        est = 'COALESCE(free_until_estimated,FALSE)' if 'free_until_estimated' in cols else 'FALSE'
        rows = c.execute(f'''SELECT container, bill, free_until FROM container_returns WHERE NOT COALESCE(is_test,FALSE)
            AND status NOT IN ('returned','closed') AND free_until IS NOT NULL AND NOT {est}
            AND free_until <= %s ORDER BY free_until''', (today + dt.timedelta(days=ALERT_DAYS),)).fetchall()
    return [f"🔔 {r['container']} (بوليصة {r['bill'] or '—'}): آخر يوم مجاني {_when(r['free_until'])} — "
            + ('اليوم' if (r['free_until'] - today).days == 0 else
               f"متأخرة {(today - r['free_until']).days} يوم" if r['free_until'] < today else f"باقي {(r['free_until'] - today).days} يوم")
            for r in rows]


# ---------- preview (staff page) ----------

CSS = '''body{font-family:"Noto Sans Arabic",Tahoma,Arial,sans-serif;background:#0b1a26;color:#eaf2f7;margin:0;direction:rtl}
.w{max-width:1100px;margin:auto;padding:24px}h1{font-size:22px;margin:0 0 4px}.sub{color:#9fb6c6;font-size:13px;margin-bottom:18px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
.card{background:#11283a;border:1px solid #214257;border-radius:14px;padding:16px}.card.warn{border-color:#d9a441}
.top{display:flex;justify-content:space-between;gap:8px;align-items:baseline}.bill{font-weight:700;font-size:15px}
.cust{color:#9fb6c6;font-size:12px}.status{font-size:17px;font-weight:700;margin:10px 0 2px;color:#f3c66b}
.src{font-size:12px;color:#9fb6c6}.row{font-size:13px;margin-top:9px;line-height:1.6}.lbl{color:#9fb6c6}
.stale{background:#3a2a12;border:1px solid #d9a441;border-radius:9px;padding:8px;font-size:12px;margin-top:9px;color:#ffd994}
.alert{background:#3b1717;border:1px solid #e06666;border-radius:9px;padding:7px;font-size:12px;margin-top:8px;color:#ffb3b3}
.pill{display:inline-block;background:#1b3a50;border-radius:20px;padding:2px 9px;font-size:11px;margin:6px 0 0 4px;color:#cfe2ee}
.review{background:#11283a;border:1px dashed #d9a441;border-radius:14px;padding:14px;margin-top:18px;font-size:13px;white-space:pre-line}'''


def page_html(cards, review='', title='ملف حي لكل شحنة — تجربة قراءة فقط', subtitle=''):
    e = html.escape
    parts = []
    for k in cards:
        warn = bool(k['stale_fasah'] or k['alerts'] or k['review_docs'])
        body = [f'<div class="top"><span class="bill">{e(k["bill_no"])}</span><span class="cust">{e(k["customer"])}</span></div>',
                f'<div class="status">{e(k["status"])}</div><div class="src">المصدر: {e(k["source"] or "—")} — {e(_when(k["at"]))}</div>']
        if k['stale_fasah']:
            s = k['stale_fasah']
            body.append(f'<div class="stale">⚠️ آخر حالة معروفة في فسح: {e(s["label"])} — {e(_when(s["seen_at"]))}<br>'
                        f'ليست الحالة الحالية — {e(s["why_stale"])}</div>')
        body.append(f'<div class="row"><span class="lbl">الموقف:</span> {e(k["blocker"] or "لا يوجد عائق موثّق")}</div>')
        body.append(f'<div class="row"><span class="lbl">الخطوة الجاية:</span> {e(k["owner"])}<br><span class="lbl">الموعد:</span> {e(k["due"])}</div>')
        for a in k['alerts']:
            body.append(f'<div class="alert">🔔 {e(a)}</div>')
        pills = [f'بيان {k["declaration_no"]}' if k['declaration_no'] else 'بلا بيان', f'{len(k["containers"])} حاوية',
                 f'{k["linked_docs"]} مستند مربوط'] + ([f'{k["review_docs"]} بانتظار المطابقة'] if k['review_docs'] else []) + \
                ([f'يوم مجاني تقديري: {len(k["estimated_free_days"])}'] if k['estimated_free_days'] else [])
        body.append(''.join(f'<span class="pill">{e(p)}</span>' for p in pills))
        parts.append(f'<div class="card{" warn" if warn else ""}">' + ''.join(body) + '</div>')
    return (f'<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)}</title><style>{CSS}</style><body><div class="w"><h1>{e(title)}</h1><div class="sub">{e(subtitle)}</div>'
            f'<div class="grid">{"".join(parts)}</div>' + (f'<div class="review">{e(review)}</div>' if review else '') + '</div></body></html>')


def board(port_word=None, now=None):
    """Cards for the open shipments (optionally one port), most urgent first."""
    from app.shipment_files import init as files_init
    files_init()
    init()
    with db() as c:
        rows = c.execute("SELECT * FROM shipment_files WHERE stage NOT IN ('closed') ORDER BY updated_at DESC LIMIT 200").fetchall()
    cards = [build(dict(r), now) for r in rows if not port_word or port_word in (r.get('pod') or '')]
    cards.sort(key=lambda k: (not k['alerts'], not k['stale_fasah'], not k['blocker'], k['bill_no']))
    return cards


def register(app):
    """Admin/customs staff page /shipment-live (pilot; read-only). Mounted only when SHIPMENT_LIVE_PILOT=1."""
    import os
    if os.getenv('SHIPMENT_LIVE_PILOT', '0') != '1':
        return
    from fastapi import HTTPException, Request
    from fastapi.responses import HTMLResponse
    from app.storage import get_session

    @app.get('/shipment-live', response_class=HTMLResponse)
    def shipment_live_page(request: Request, port: str = ''):
        s = get_session(request.cookies.get('gla_session'))
        if not s or s.get('role') not in ('admin', 'customs'):
            raise HTTPException(403)
        return HTMLResponse(page_html(board(port or None), review_text(),
                                      subtitle='آخر حالة موثّقة ومصدرها، الموقف، المسؤول والموعد — لا إرسال ولا ترحيل مالي'),
                            headers={'Cache-Control': 'no-store'})
