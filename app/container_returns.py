"""Container return tracking — until the EMPTY container is returned, not just delivered (owner request, Nov 2026).

For every container: last free day, delivery date, return place (depot), customer and driver numbers and the
daily cost once confirmed. A container is closed ONLY with return proof (EIR / interchange receipt photo) or a
confirmation from the responsible party recorded by the team — a driver saying «رجعتها» marks it
«أفاد السائق بالإرجاع» and keeps it open.
Alerts to the manager: 2 days before the free period ends, on the last free day, and daily once overdue
(urgent, with the cost so far when the daily cost is confirmed). Each alert carries ready reminders to the
customer and driver that go out only with «نفذ CODE».
"""
import asyncio
import datetime as dt
import html
import json
import re

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.storage import db, utcnow

router = APIRouter()
NUMBER = re.compile(r'(?<![A-Z0-9])([A-Z]{4})\s*-?\s*(\d{6,7})(?![0-9])')
STATUS = {'open': 'لم تُسلَّم بعد', 'delivered': 'سُلّمت للعميل — بانتظار الإرجاع', 'driver_reported': 'أفاد السائق بالإرجاع — بانتظار الإثبات',
          'returned': 'أُرجعت بإثبات ✅', 'closed': 'مغلقة ✅'}
OPEN = ('open', 'delivered', 'driver_reported')
_READY = False


def init():
    global _READY
    if _READY:
        return
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS container_returns(
            id BIGSERIAL PRIMARY KEY, container TEXT NOT NULL UNIQUE, customer TEXT, customer_phone TEXT, driver_phone TEXT,
            bill TEXT, free_until DATE, delivered_on DATE, return_place TEXT, daily_cost NUMERIC, status TEXT NOT NULL DEFAULT 'open',
            proof TEXT, is_test BOOLEAN NOT NULL DEFAULT FALSE, last_alert TEXT, last_alert_on DATE, notes TEXT,
            created_by TEXT, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS container_return_events(
            id BIGSERIAL PRIMARY KEY, container_id BIGINT NOT NULL REFERENCES container_returns(id), event TEXT NOT NULL,
            note TEXT, actor TEXT, created_at TIMESTAMPTZ NOT NULL)''')
    _READY = True


def number(value):
    m = NUMBER.search(str(value or '').upper())
    return (m.group(1) + m.group(2)) if m else ''


def date(value):
    if not value:
        return None
    text = str(value).strip().translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y'):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    m = re.fullmatch(r'(\d{1,2})[/-](\d{1,2})', text)
    if m:
        today = dt.date.today()
        try:
            return dt.date(today.year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def money(value):
    try:
        return float(re.sub(r'[^\d.]', '', str(value))) if value not in (None, '') else None
    except ValueError:
        return None


def phone(value):
    d = re.sub(r'\D', '', str(value or ''))
    if d.startswith('05') and len(d) == 10:
        d = '966' + d[1:]
    return d


def event(c, cid, kind, note, actor):
    c.execute('INSERT INTO container_return_events(container_id,event,note,actor,created_at) VALUES(%s,%s,%s,%s,%s)',
              (cid, kind, (note or '')[:1000], actor or '', utcnow()))


def track(args, actor=''):
    """Create or update a container (team command)."""
    init()
    cno = number(args.get('container'))
    if not cno:
        return 'رقم الحاوية غير واضح (4 حروف و7 أرقام مثل MSKU1234567).'
    fields = {'customer': args.get('customer'), 'customer_phone': phone(args.get('customer_phone')) or None,
              'driver_phone': phone(args.get('driver_phone')) or None, 'bill': args.get('bill'),
              'free_until': date(args.get('free_until')), 'delivered_on': date(args.get('delivered_on')),
              'return_place': args.get('return_place'), 'daily_cost': money(args.get('daily_cost'))}
    fields = {k: v for k, v in fields.items() if v not in (None, '')}
    test = bool(args.get('test')) or cno.startswith('TEST')
    with db() as c:
        row = c.execute('SELECT * FROM container_returns WHERE container=%s', (cno,)).fetchone()
        if not row:
            row = c.execute('''INSERT INTO container_returns(container,is_test,created_by,created_at,updated_at) VALUES(%s,%s,%s,%s,%s)
                RETURNING *''', (cno, test, actor, utcnow(), utcnow())).fetchone()
            event(c, row['id'], 'created', json.dumps({k: str(v) for k, v in fields.items()}, ensure_ascii=False), actor)
        if fields:
            sets = ','.join(k + '=%s' for k in fields)
            c.execute('UPDATE container_returns SET ' + sets + ',updated_at=%s WHERE id=%s', (*fields.values(), utcnow(), row['id']))
            if fields.get('free_until') and 'free_until_estimated' in row:
                c.execute('UPDATE container_returns SET free_until_estimated=FALSE WHERE id=%s', (row['id'],))  # confirmed by the team
        if fields.get('delivered_on') and row['status'] == 'open':
            c.execute("UPDATE container_returns SET status='delivered' WHERE id=%s", (row['id'],))
            event(c, row['id'], 'delivered', str(fields['delivered_on']), actor)
        row = c.execute('SELECT * FROM container_returns WHERE id=%s', (row['id'],)).fetchone()
        try:
            from app import line_desk
            line_desk.autolink(c, row)
        except Exception as exc:
            print('LINE_DESK_AUTOLINK', type(exc).__name__, str(exc)[:120], flush=True)
    missing = [label for key, label in (('free_until', 'آخر يوم مجاني'), ('return_place', 'مكان الإرجاع'),
                                        ('customer_phone', 'رقم العميل'), ('driver_phone', 'رقم السائق')) if not row.get(key)]
    return card(row) + ('\nناقص: ' + '، '.join(missing) if missing else '')


def card(row):
    days = (row['free_until'] - dt.date.today()).days if row.get('free_until') else None
    when = '' if days is None else (f' — باقي {days} يوم' if days > 0 else ' — اليوم آخر يوم مجاني ⚠️' if days == 0 else f' — متأخرة {-days} يوم 🔴')
    lines = [f"📦 الحاوية {row['container']}{' (تجريبية)' if row['is_test'] else ''}: {STATUS.get(row['status'], row['status'])}"]
    for key, label in (('customer', 'العميل'), ('bill', 'البوليصة'), ('delivered_on', 'التسليم'), ('free_until', 'آخر يوم مجاني'),
                       ('return_place', 'مكان الإرجاع'), ('daily_cost', 'التكلفة اليومية المؤكدة')):
        if row.get(key) not in (None, ''):
            lines.append(f'• {label}: {row[key]}' + (when if key == 'free_until' else ''))
    if row.get('daily_cost') and days is not None and days < 0:
        lines.append(f'• التكلفة حتى الآن: {float(row["daily_cost"]) * -days:,.0f} ريال')
    from app import line_desk
    lines += line_desk.card_lines(row)
    return '\n'.join(lines)


def update(args, actor='', proof=None):
    """Status change. Closing needs proof (photo/EIR ref) or the responsible party's confirmation."""
    init()
    cno = number(args.get('container'))
    kind = args.get('event')
    with db() as c:
        row = c.execute('SELECT * FROM container_returns WHERE container=%s', (cno,)).fetchone() if cno else None
        if not row:
            return 'الحاوية غير مسجلة؛ سجلها أولًا مع آخر يوم مجاني ومكان الإرجاع.'
        note = str(args.get('note') or '')
        if kind == 'delivered':
            c.execute("UPDATE container_returns SET status='delivered',delivered_on=COALESCE(delivered_on,%s),updated_at=%s WHERE id=%s",
                      (date(args.get('date')) or dt.date.today(), utcnow(), row['id']))
        elif kind == 'driver_returned':
            if row['status'] in ('returned', 'closed'):
                return card(row)
            c.execute("UPDATE container_returns SET status='driver_reported',updated_at=%s WHERE id=%s", (utcnow(), row['id']))
        elif kind == 'returned':
            evidence = proof or note
            if not evidence or len(evidence.strip()) < 4:
                return ('لا أغلق الحاوية بدون إثبات: أرسل صورة سند الإرجاع (EIR) مع رقم الحاوية، '
                        'أو اكتب من أكد الإرجاع (مثال: «أكدت محطة الحاويات إرجاع ' + cno + ' برقم سند 12345»).')
            c.execute("UPDATE container_returns SET status='returned',proof=%s,updated_at=%s WHERE id=%s", (evidence[:500], utcnow(), row['id']))
        else:
            return 'نوع التحديث غير معروف.'
        event(c, row['id'], kind, proof or note, actor)
        row = c.execute('SELECT * FROM container_returns WHERE id=%s', (row['id'],)).fetchone()
        extra = ''
        if kind == 'returned' and row.get('customer_phone') and not row.get('is_test'):
            from app import reviews, transport_desk
            text = reviews.after_delivery_text(row.get('customer') or '')
            chat = transport_desk.manager_chat(c) if text else None
            if chat:
                token = transport_desk.pending(c, chat[0], chat[1], {'tool': 'send_whatsapp', 'to': '+' + row['customer_phone'], 'text': text}, 24 * 60)
                extra = f'\n⭐ طلب تقييم قوقل جاهز للعميل. للإرسال اكتب: نفذ {token}'
    return card(row) + extra


def status_text(filter_text=''):
    init()
    with db() as c:
        rows = c.execute("SELECT * FROM container_returns WHERE status IN ('open','delivered','driver_reported') ORDER BY free_until NULLS LAST").fetchall()
    if filter_text:
        rows = [r for r in rows if filter_text in r['container'] or filter_text in str(r.get('customer') or '')]
    if not rows:
        return 'لا توجد حاويات مفتوحة.'
    return '\n\n'.join(card(r) for r in rows[:20])


# ---------- alerts ----------

def reminder_texts(row):
    place = row.get('return_place') or 'مكان الإرجاع المحدد'
    when = row['free_until'].strftime('%d/%m') if row.get('free_until') else ''
    customer = (f"السلام عليكم، تذكير من آفاق طويق: الحاوية {row['container']} آخر يوم مجاني لها {when}. "
                f"نرجو تفريغها وتسليمها للسائق لإرجاعها إلى {place} قبل الموعد لتجنب غرامات التأخير. للاستفسار: 0507665873")
    driver = (f"السلام عليكم، من آفاق طويق: الحاوية {row['container']} لازم ترجع فارغة إلى {place} قبل {when}. "
              'بعد الإرجاع أرسل لنا صورة سند الإرجاع (EIR). شكرًا لك.')
    return customer, driver


def due_alerts(today=None):
    """Returns alert texts (once per container per day per level)."""
    from app import transport_desk
    init()
    today = today or dt.date.today()
    out = []
    with db() as c:
        rows = c.execute("SELECT * FROM container_returns WHERE status IN ('open','delivered','driver_reported') AND free_until IS NOT NULL").fetchall()
        chat = transport_desk.manager_chat(c)
        for row in rows:
            days = (row['free_until'] - today).days
            level = 'overdue' if days < 0 else 'today' if days == 0 else 'soon' if days <= 2 else None
            if not level or (row.get('last_alert') == level and row.get('last_alert_on') == today):
                continue
            head = {'soon': f'⏰ الحاوية {row["container"]}: باقي {days} يوم على انتهاء المدة المجانية',
                    'today': f'⚠️ الحاوية {row["container"]}: اليوم آخر يوم مجاني',
                    'overdue': f'🔴 عاجل — الحاوية {row["container"]} متأخرة {-days} يوم عن المدة المجانية'}[level]
            text = head + '\n' + card(row)
            if chat:
                customer, driver = reminder_texts(row)
                for who, to, msg in (('العميل', row.get('customer_phone'), customer), ('السائق', row.get('driver_phone'), driver)):
                    if to:
                        token = transport_desk.pending(c, chat[0], chat[1], {'tool': 'send_whatsapp', 'to': '+' + to, 'text': msg}, 240)
                        text += f'\nلتذكير {who} اكتب: نفذ {token}'
            c.execute('UPDATE container_returns SET last_alert=%s,last_alert_on=%s WHERE id=%s', (level, today, row['id']))
            out.append(text)
    return out


def register_worker(app):
    async def loop():
        from starlette.concurrency import run_in_threadpool
        from app.owner_briefing import deliver
        await asyncio.sleep(150)
        while True:
            try:
                for text in await run_in_threadpool(due_alerts):
                    await deliver(text)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('CONTAINER_RETURNS_WORKER', type(exc).__name__, str(exc)[:160], flush=True)
            await asyncio.sleep(1800)

    @app.on_event('startup')
    async def start():
        app.state.container_returns_worker = asyncio.create_task(loop())


# ---------- page ----------

@router.get('/containers', response_class=HTMLResponse)
def page(request: Request):
    from app.naqliat_connector import _page, _session
    _session(request)
    init()
    e = lambda v: html.escape(str(v if v is not None else ''))
    with db() as c:
        rows = c.execute("""SELECT * FROM container_returns ORDER BY (status IN ('returned','closed')), free_until NULLS LAST, id DESC LIMIT 200""").fetchall()
    today = dt.date.today()
    trs = ''
    for r in rows:
        days = (r['free_until'] - today).days if r.get('free_until') else None
        color = '' if r['status'] in ('returned', 'closed') or days is None else '#ff5c5c' if days < 0 else '#ffb020' if days <= 2 else ''
        trs += (f'<tr style="color:{color}"><td>{e(r["container"])}{" (تجريبية)" if r["is_test"] else ""}</td><td>{e(r.get("customer"))}</td>'
                f'<td>{e(r.get("delivered_on"))}</td><td>{e(r.get("free_until"))}</td><td>{"" if days is None else e(days)}</td>'
                f'<td>{e(r.get("return_place"))}</td><td>{e(STATUS.get(r["status"], r["status"]))}</td><td>{e(r.get("proof"))}</td></tr>')
    body = ('<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/transport-desk">مكتب النقل</a></div><h1>متابعة إرجاع الحاويات</h1>'
            '<p class="muted">الحاوية لا تُغلق إلا بإثبات الإرجاع. الأحمر متأخرة، والبرتقالي باقي يومان أو أقل. '
            'التسجيل من واتساب: «سجل الحاوية MSKU1234567 العميل ... آخر يوم مجاني 10/11 الإرجاع ساحة ... سائق 05...».</p>'
            '<div class="card scroll"><table><tr><th>الحاوية</th><th>العميل</th><th>التسليم</th><th>آخر يوم مجاني</th><th>الأيام المتبقية</th>'
            '<th>مكان الإرجاع</th><th>الحالة</th><th>الإثبات</th></tr>' + trs + '</table></div>')
    return HTMLResponse(_page('إرجاع الحاويات', body))
