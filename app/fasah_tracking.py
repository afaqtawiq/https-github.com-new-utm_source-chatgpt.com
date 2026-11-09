"""Live FASAH declaration status tracking (owner request, Nov 2026).

The work computer reads the FASAH declaration lists (read-only) every ~2 hours during working hours. Every read is
compared with the last known status of each declaration. When a status changes the manager gets one message, and
for each customer with a known number a ready customer message that is sent ONLY after «نفذ CODE». A declaration
that stays waiting for customs duties more than a day raises an alert. Nothing is sent to customers automatically.
"""
import asyncio
import datetime as dt
import os
import re

from app.storage import db, utcnow

AUTO_ACTOR = 'متابعة تلقائية'
EVERY_HOURS = 2
RIYADH = dt.timezone(dt.timedelta(hours=3))

# (stage, label for the manager/customer, normalized phrases found in the FASAH row text) — first match wins.
STAGES = [
    ('released', 'تم الفسح ✅', ('جاهز لطباعه اشعار الفسح', 'فسح كلي', 'مفسوح', 'تم الفسح', 'اشعار الفسح')),
    ('duties_due', 'بانتظار سداد الرسوم الجمركية', ('انتظار تحصيل الرسوم', 'بانتظار الرسوم', 'سداد الرسوم', 'تحصيل الرسوم')),
    ('inspection', 'تحت الكشف / المعاينة', ('الكشف', 'المعاينه', 'معاينه', 'فحص')),
    ('reviewed', 'انتهت مراجعة مركز العمليات الجمركية', ('انتهاء مراجعه مركز العمليات',)),
    ('under_review', 'تحت المعالجة', ('تحت المعالجه', 'قيد المعالجه', 'قيد المراجعه')),
    ('not_arrived', 'مقدّم — الشحنة لم تصل إلى المنفذ بعد', ('لم يصل الى المنفذ', 'لم تصل الى المنفذ')),
    ('draft', 'مسودة', ('مسوده',)),
    ('cancelled', 'ملغي', ('ملغي', 'الغاء')),
]
LABELS = {s: label for s, label, _ in STAGES}
CLOSED = {'released', 'cancelled'}


def norm(text):
    text = re.sub(r'[ً-ْـ]', '', str(text or ''))
    for a, b in (('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ة', 'ه'), ('ى', 'ي')):
        text = text.replace(a, b)
    return ' '.join(text.split())


def classify(details):
    text = norm(details)
    for stage, label, phrases in STAGES:
        if any(norm(p) in text for p in phrases):
            return stage
    return 'unknown'


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS fasah_status(number TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL DEFAULT '',
            declared_on TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL, first_seen TIMESTAMPTZ NOT NULL,
            seen_at TIMESTAMPTZ NOT NULL, changed_at TIMESTAMPTZ NOT NULL, duties_since TIMESTAMPTZ, duties_alerted_on DATE,
            PRIMARY KEY(number, kind))''')
        c.execute('''CREATE TABLE IF NOT EXISTS fasah_status_events(id BIGSERIAL PRIMARY KEY, number TEXT NOT NULL, kind TEXT NOT NULL,
            old_stage TEXT, new_stage TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('CREATE TABLE IF NOT EXISTS fasah_tracking_state(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        c.execute('''CREATE TABLE IF NOT EXISTS fasah_importer_contacts(name TEXT PRIMARY KEY, phone TEXT NOT NULL, added_by TEXT,
            created_at TIMESTAMPTZ NOT NULL)''')


# ---------- customer number for a declaration ----------

def phone_digits(value):
    d = re.sub(r'\D', '', str(value or ''))
    if d.startswith('05') and len(d) == 10:
        d = '966' + d[1:]
    elif d.startswith('5') and len(d) == 9:
        d = '966' + d
    return d if len(d) >= 11 else ''


def customer_for(c, number, details):
    """(name, phone) of the customer of this declaration, or (None, None). Exact declaration match first, then a saved
    importer name found in the FASAH row, then the customer directory (names of 4+ letters only)."""
    row = c.execute("""SELECT customer_name,customer_phone FROM customs_declarations WHERE declaration_number=%s
        AND customer_phone<>'' ORDER BY id DESC LIMIT 1""", (number,)).fetchone() if _has(c, 'customs_declarations') else None
    if row and phone_digits(row['customer_phone']):
        return row['customer_name'], phone_digits(row['customer_phone'])
    text = norm(details)
    for r in c.execute('SELECT name,phone FROM fasah_importer_contacts ORDER BY length(name) DESC').fetchall():
        if norm(r['name']) and norm(r['name']) in text:
            return r['name'], r['phone']
    if _has(c, 'customer_directory'):
        for r in c.execute("""SELECT company_name,phone FROM customer_directory WHERE phone IS NOT NULL AND phone<>''
                AND length(company_name)>=4 ORDER BY length(company_name) DESC LIMIT 2000""").fetchall():
            if norm(r['company_name']) in text and phone_digits(r['phone']):
                return r['company_name'], phone_digits(r['phone'])
    return None, None


def _has(c, table):
    return bool(c.execute('SELECT to_regclass(%s) t', (table,)).fetchone()['t'])


def customer_text(number, kind, stage):
    what = 'بيانكم الجمركي' + (' للتصدير' if kind == 'export' else '')
    body = {
        'released': f'يسعدنا إبلاغكم أنه تم فسح {what} رقم {number}. سنتواصل معكم لترتيب الاستلام والنقل.',
        'duties_due': f'{what} رقم {number} بانتظار سداد الرسوم الجمركية. نرجو السداد في أقرب وقت لإكمال الفسح وتجنب الأرضيات.',
        'inspection': f'{what} رقم {number} في مرحلة الكشف/المعاينة لدى الجمارك، ونتابع معكم أولًا بأول.',
        'reviewed': f'انتهت مراجعة مركز العمليات الجمركية على {what} رقم {number}، ونتابع الخطوة التالية.',
        'under_review': f'{what} رقم {number} تحت المعالجة لدى الجمارك الآن.',
        'not_arrived': f'تم تقديم {what} رقم {number}، والشحنة لم تصل إلى المنفذ بعد.',
    }.get(stage)
    if not body:
        return None
    review = ''
    if stage == 'released':
        from app.reviews import line
        review = ('\n' + line()) if line() else ''
    return 'عميلنا العزيز،\n' + body + review + '\nآفاق طويق للتخليص الجمركي — 0507665873'


# ---------- reading results ----------

def ingest(rows, kind, now=None):
    """Store one FASAH list read. Returns the declarations whose stage changed (never on the very first sighting)."""
    init()
    now = now or utcnow()
    changes = []
    with db() as c:
        for r in rows:
            number = str(r.get('رقم البيان') or '').strip()
            if not re.fullmatch(r'\d{3,8}', number):
                continue
            details = str(r.get('التفاصيل') or '')[:300]
            stage = classify(details)
            old = c.execute('SELECT stage,duties_since FROM fasah_status WHERE number=%s AND kind=%s FOR UPDATE', (number, kind)).fetchone()
            if not old:
                c.execute('''INSERT INTO fasah_status(number,kind,ref,declared_on,details,stage,first_seen,seen_at,changed_at,duties_since)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''', (number, kind, str(r.get('رقم المرجع') or ''), str(r.get('التاريخ') or ''),
                                                          details, stage, now, now, now, now if stage == 'duties_due' else None))
                continue
            if stage == 'unknown' or stage == old['stage']:
                c.execute('UPDATE fasah_status SET seen_at=%s,details=%s WHERE number=%s AND kind=%s', (now, details, number, kind))
                continue
            c.execute('''UPDATE fasah_status SET stage=%s,details=%s,seen_at=%s,changed_at=%s,
                duties_since=CASE WHEN %s='duties_due' THEN COALESCE(duties_since,%s) ELSE NULL END,
                duties_alerted_on=CASE WHEN %s='duties_due' THEN duties_alerted_on ELSE NULL END WHERE number=%s AND kind=%s''',
                      (stage, details, now, now, stage, now, stage, number, kind))
            c.execute('INSERT INTO fasah_status_events(number,kind,old_stage,new_stage,created_at) VALUES(%s,%s,%s,%s,%s)',
                      (number, kind, old['stage'], stage, now))
            changes.append({'number': number, 'kind': kind, 'old': old['stage'], 'new': stage, 'details': details})
    return changes


def change_message(changes):
    """Manager message for the changes, with a «نفذ» code per customer message. Nothing is sent before the code."""
    if not changes:
        return None
    from app import transport_desk
    lines = [f'🛃 تغيّرت حالة {len(changes)} بيان في فسح:']
    with db() as c:
        chat = transport_desk.manager_chat(c)
        for ch in changes:
            kind = 'تصدير' if ch['kind'] == 'export' else 'استيراد'
            lines.append(f"\n• {ch['number']} ({kind}): {LABELS.get(ch['old'], ch['old'] or '—')} ← {LABELS.get(ch['new'], ch['new'])}")
            name, phone = customer_for(c, ch['number'], ch['details'])
            text = customer_text(ch['number'], ch['kind'], ch['new'])
            if not text:
                continue
            if not phone:
                lines.append('  رقم العميل غير معروف. لحفظه اكتب: رقم المستورد <اسم المستورد كما في فسح> 05xxxxxxxx')
            elif chat:
                token = transport_desk.pending(c, chat[0], chat[1], {'tool': 'send_whatsapp', 'to': '+' + phone, 'text': text}, 240)
                lines.append(f'  رسالة جاهزة للعميل {name} (+{phone}). للإرسال اكتب: نفذ {token}')
    return '\n'.join(lines)


def duties_alerts(now=None):
    """Declarations waiting for duties more than 24 hours: one alert per declaration per day."""
    init()
    from app import transport_desk
    now = now or utcnow()
    today = now.astimezone(RIYADH).date()
    out = []
    with db() as c:
        rows = c.execute('''SELECT * FROM fasah_status WHERE stage='duties_due' AND duties_since < %s
            AND (duties_alerted_on IS NULL OR duties_alerted_on < %s) AND seen_at > %s ORDER BY duties_since''',
                         (now - dt.timedelta(hours=24), today, now - dt.timedelta(days=3))).fetchall()
        chat = transport_desk.manager_chat(c) if rows else None
        for r in rows:
            hours = int((now - r['duties_since']).total_seconds() // 3600)
            text = f"⏳ البيان {r['number']} بانتظار سداد الرسوم منذ {hours // 24} يوم و{hours % 24} ساعة."
            name, phone = customer_for(c, r['number'], r['details'])
            msg = customer_text(r['number'], r['kind'], 'duties_due')
            if phone and chat:
                token = transport_desk.pending(c, chat[0], chat[1], {'tool': 'send_whatsapp', 'to': '+' + phone, 'text': msg}, 240)
                text += f'\nتذكير العميل {name}: نفذ {token}'
            elif not phone:
                text += '\nرقم العميل غير معروف (رقم المستورد <الاسم> 05xxxxxxxx).'
            c.execute('UPDATE fasah_status SET duties_alerted_on=%s WHERE number=%s AND kind=%s', (today, r['number'], r['kind']))
            out.append(text)
    return out


def after_read(task, rows):
    """Called by the runner after every verified FASAH list read (manual or automatic)."""
    import json
    params = json.loads(task['params_json']) if isinstance(task.get('params_json'), str) else (task.get('params_json') or {})
    changes = ingest(rows, params.get('which', 'import'))
    message = change_message(changes)
    try:
        from app import fasah_docs
        if fasah_docs.request_for(changes) and message:
            message += '\n\n📥 أرسلت جهاز العمل يجلب إشعار الفسح ورقم سداد الرسوم للبيانات المتغيرة (قراءة فقط).'
    except Exception as exc:
        print('FASAH_DOCS_REQUEST', type(exc).__name__, str(exc)[:160], flush=True)
    return message


# ---------- manager commands ----------

def save_contact(name, phone, actor=''):
    name, digits = ' '.join(str(name or '').split())[:80], phone_digits(phone)
    if len(name) < 3 or not digits:
        return 'اكتب اسم المستورد كما يظهر في فسح ورقم واتساب صحيح، مثل: رقم المستورد سلة الرحائب 0551234567'
    init()
    with db() as c:
        c.execute('''INSERT INTO fasah_importer_contacts(name,phone,added_by,created_at) VALUES(%s,%s,%s,%s)
            ON CONFLICT(name) DO UPDATE SET phone=EXCLUDED.phone,added_by=EXCLUDED.added_by''', (name, digits, actor, utcnow()))
        n = sum(1 for r in c.execute('SELECT details FROM fasah_status WHERE stage<>ALL(%s)', (list(CLOSED),)).fetchall()
                if norm(name) in norm(r['details']))
    return f'✅ حفظت رقم {name}: +{digits}. بياناته المفتوحة حاليًا في المتابعة: {n}. رسائل الحالة تُجهَّز له وتُرسل بعد «نفذ» فقط.'


def status_text(filter_text=''):
    init()
    with db() as c:
        rows = c.execute('''SELECT * FROM fasah_status WHERE stage<>ALL(%s) AND seen_at > NOW()-INTERVAL '3 days'
            ORDER BY changed_at DESC LIMIT 200''', (list(CLOSED),)).fetchall()
        last = c.execute('SELECT MAX(seen_at) s FROM fasah_status').fetchone()['s']
    f = norm(filter_text)
    rows = [r for r in rows if not f or f in norm(r['details']) or f in r['number']]
    if not rows:
        return 'لا توجد بيانات مفتوحة في متابعة فسح' + (' تطابق «' + filter_text + '»' if filter_text else '') + '.' + (
            '' if last else '\nلم تُقرأ قائمة فسح بعد؛ تبدأ المتابعة عند تشغيل جهاز العمل وتسجيل الدخول في فسح.')
    lines = [f'🛃 البيانات المفتوحة في فسح ({len(rows)}):']
    for r in rows[:40]:
        extra = ''
        if r['stage'] == 'duties_due' and r['duties_since']:
            extra = f" — منذ {int((utcnow() - r['duties_since']).total_seconds() // 3600)} ساعة"
        lines.append(f"• {r['number']} ({'تصدير' if r['kind'] == 'export' else 'استيراد'}): {LABELS.get(r['stage'], 'غير واضح')}{extra}")
    if last:
        lines.append('آخر قراءة: ' + last.astimezone(RIYADH).strftime('%d/%m %H:%M'))
    return '\n'.join(lines)


def customer_lines(sender):
    """Live FASAH status lines for a customer's own WhatsApp number (via saved importer contacts)."""
    digits = phone_digits(sender)
    if not digits:
        return []
    try:
        init()
        with db() as c:
            names = [r['name'] for r in c.execute('SELECT name FROM fasah_importer_contacts WHERE phone=%s', (digits,)).fetchall()]
            if not names:
                return []
            rows = c.execute('''SELECT number,kind,stage,details FROM fasah_status WHERE seen_at > NOW()-INTERVAL '3 days'
                AND (stage<>ALL(%s) OR changed_at > NOW()-INTERVAL '2 days') ORDER BY changed_at DESC LIMIT 50''', (list(CLOSED),)).fetchall()
    except Exception:
        return []
    keys = [norm(n) for n in names]
    return [f"• بيان {r['number']}: {LABELS.get(r['stage'], 'قيد المتابعة')}" for r in rows if any(k in norm(r['details']) for k in keys)][:8]


# ---------- schedule ----------

def due_reads(now=None):
    """Create the 2-hourly read tasks (import + export) when the work computer is online and idle. Returns task ids."""
    from app import agent_runner
    agent_runner.init()
    now = now or utcnow()
    local = now.astimezone(RIYADH)
    if os.getenv('FASAH_TRACKING', '1') == '0' or not 7 <= local.hour < 23:
        return []
    with db() as c:
        seen = c.execute('SELECT MAX(last_seen) s FROM runner_devices WHERE enabled').fetchone()['s']
        if not seen or (now - seen).total_seconds() > 180:
            return []
        busy = c.execute("SELECT 1 FROM runner_tasks WHERE status IN ('queued','running','stopping') LIMIT 1").fetchone()
        last = c.execute('SELECT MAX(created_at) t FROM runner_tasks WHERE created_by=%s', (AUTO_ACTOR,)).fetchone()['t']
    if busy or (last and now - last < dt.timedelta(hours=EVERY_HOURS) - dt.timedelta(minutes=5)):
        return []
    since = (local.date() - dt.timedelta(days=21)).isoformat()
    ids = []
    for which in ('import', 'export'):
        tid, _ = agent_runner.create_task('fasah_declarations', {'which': which, 'since': since, 'pages': 3, 'track': True}, AUTO_ACTOR)
        if tid:
            ids.append(tid)
    return ids


def session_notice():
    """One notice when the last two automatic reads failed (FASAH signed out), then quiet until a read succeeds."""
    init()
    with db() as c:
        # Any finished FASAH list read counts: a manual «افتح فسح» / list read that succeeded proves the session is alive.
        rows = c.execute('''SELECT id,status FROM runner_tasks WHERE kind='fasah_declarations' AND status IN ('done','failed','stopped')
            ORDER BY id DESC LIMIT 2''').fetchall()
        if len(rows) < 2 or any(r['status'] != 'failed' for r in rows):
            return None
        sent = c.execute("SELECT value FROM fasah_tracking_state WHERE key='session_notice'").fetchone()
        if sent and sent['value'] == '1':
            return None
        c.execute("INSERT INTO fasah_tracking_state(key,value) VALUES('session_notice','1') "
                  "ON CONFLICT(key) DO UPDATE SET value='1'")
    return ('⚠️ متابعة فسح متوقفة: آخر قراءتين تلقائيتين لم تكتملا (غالبًا انتهت جلسة فسح).\n'
            'افتح نافذة «جهاز آفاق طويق» وسجّل دخولك في فسح، وتستأنف المتابعة تلقائيًا.')


def read_succeeded():
    with db() as c:
        c.execute("UPDATE fasah_tracking_state SET value='0' WHERE key='session_notice'")


def register_worker(app):
    async def loop():
        from starlette.concurrency import run_in_threadpool
        from app.owner_briefing import deliver
        await asyncio.sleep(200)
        while True:
            try:
                await run_in_threadpool(due_reads)
                for text in await run_in_threadpool(duties_alerts):
                    await deliver(text)
                notice = await run_in_threadpool(session_notice)
                if notice:
                    await deliver(notice)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('FASAH_TRACKING_WORKER', type(exc).__name__, str(exc)[:160], flush=True)
            await asyncio.sleep(600)

    @app.on_event('startup')
    async def start():
        init()
        app.state.fasah_tracking_worker = asyncio.create_task(loop())
