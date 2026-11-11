"""Shipping-line desk: free-time extensions, detention cost and fine audits for containers (owner request, Nov 2026).

Builds ON container_returns (the container list, alerts and proof-based closing) and shipping_agents (the Jeddah
agents and their emails). Nothing existing is removed or replaced.

1. Every container is linked to its shipping agent — from the container prefix (MSKU → Maersk …) or set by the team.
2. The agent's detention tariff (tiers after the free days) gives a running cost estimate when no confirmed daily
   cost exists, and a daily exposure summary per agent.
3. Free-time extension: 3 days before the free period ends the desk prepares ONE extension email per agent and bill
   (to the agent's Extension/Detention/Equipment address) and the manager sends it with «نفذ CODE». A sent request
   with no answer gets a reminder draft after 24 hours; replies that arrive in the official mailbox and mention the
   container or bill are surfaced to the manager. «تم تمديد ...» records the new free date (the original is kept).
4. Fine audit: an agent detention invoice is checked against free days, approved extensions, the proven return
   date and the tariff; an overcharge gets an objection email draft with the evidence, sent only with «نفذ».
Every outgoing email goes from the official mailbox only after «نفذ CODE». No money is posted anywhere.
"""
import asyncio
import datetime as dt
import html
import json
import os
import re

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.storage import db, utcnow

router = APIRouter()
LEAD_DAYS = 3
DEFAULT_EXTENSION_DAYS = 7
REMIND_AFTER = dt.timedelta(hours=24)
TOLERANCE = 1.02
_READY = False

# Container owner prefix (ISO 6346) → agent name as stored in shipping_agents. Leasing prefixes are left out on purpose.
PREFIXES = {
    'Maersk Line': ('MSKU', 'MAEU', 'MRKU', 'MRSU', 'MCRU', 'MNBU', 'SUDU'),
    'MSC': ('MSCU', 'MEDU', 'MSDU', 'MSMU'),
    'CMA CGM': ('CMAU', 'CGMU', 'ECMU', 'APHU', 'APZU'),
    'COSCO Line': ('COSU', 'CBHU', 'CCLU', 'CSNU', 'CSLU'),
    'OOCL Line': ('OOLU', 'OOCU'),
    'Hapag-Lloyd': ('HLXU', 'HLBU', 'HAMU', 'HLCU', 'UACU', 'UASU'),
    'ONE Line': ('ONEU', 'NYKU', 'MOLU', 'KKFU', 'KKLU'),
    'Evergreen': ('EGHU', 'EISU', 'EMCU', 'EITU', 'EGSU'),
    'PIL': ('PCIU', 'PILU'),
    'Emirates Line': ('ESPU',),
}
PREFIX_AGENT = {p: name for name, ps in PREFIXES.items() for p in ps}
CONTACT_ORDER = ('extension', 'detention', 'equipment', 'empty', 'import', 'operations', 'customer', 'general')
REQ_STATUS = {'draft': 'مسودة بانتظار «نفذ»', 'sent': 'أُرسل — بانتظار رد الوكيل', 'approved': 'وافق الوكيل ✅',
              'rejected': 'رفض الوكيل ❌'}


def init():
    global _READY
    if _READY:
        return
    from app import container_returns
    container_returns.init()
    with db() as c:
        for col in ('agent_id BIGINT', 'size TEXT', 'original_free_until DATE', 'returned_on DATE', 'arrived_on DATE',
                    'fasah_number TEXT', 'free_until_estimated BOOLEAN NOT NULL DEFAULT FALSE'):
            c.execute('ALTER TABLE container_returns ADD COLUMN IF NOT EXISTS ' + col)
        c.execute('''CREATE TABLE IF NOT EXISTS line_tariffs(id BIGSERIAL PRIMARY KEY, agent_id BIGINT NOT NULL, size TEXT NOT NULL,
            tiers_json TEXT NOT NULL, note TEXT, created_by TEXT, created_at TIMESTAMPTZ NOT NULL, UNIQUE(agent_id,size))''')
        c.execute('''CREATE TABLE IF NOT EXISTS line_free_days(agent_id BIGINT PRIMARY KEY, days INTEGER NOT NULL, created_by TEXT,
            created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS free_time_requests(id BIGSERIAL PRIMARY KEY, agent_id BIGINT NOT NULL,
            bill TEXT, containers_json TEXT NOT NULL, days INTEGER NOT NULL, recipient TEXT, subject TEXT, body TEXT,
            status TEXT NOT NULL DEFAULT 'draft', new_until DATE, sent_at TIMESTAMPTZ, decided_at TIMESTAMPTZ,
            reminded_at TIMESTAMPTZ, reminders INTEGER NOT NULL DEFAULT 0, last_inbox_id BIGINT, note TEXT,
            created_by TEXT, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS detention_claims(id BIGSERIAL PRIMARY KEY, container_id BIGINT NOT NULL,
            agent_id BIGINT, claimed NUMERIC NOT NULL, expected NUMERIC, days_charged INTEGER, days_expected INTEGER,
            verdict TEXT NOT NULL, recipient TEXT, subject TEXT, body TEXT, status TEXT NOT NULL DEFAULT 'recorded',
            sent_at TIMESTAMPTZ, created_by TEXT, created_at TIMESTAMPTZ NOT NULL)''')
    _READY = True


def _has(c, table):
    return bool(c.execute('SELECT to_regclass(%s) t', (table,)).fetchone()['t'])


# ---------- agents ----------

def agent_by_name(c, text):
    text = str(text or '').strip()
    if not text or not _has(c, 'shipping_agents'):
        return None
    rows = c.execute("SELECT id,name FROM shipping_agents WHERE status='active' ORDER BY length(name)").fetchall()
    low = text.casefold()
    for r in rows:
        if r['name'].casefold() == low:
            return r
    hits = [r for r in rows if low in r['name'].casefold() or r['name'].casefold().split(' ')[0] == low.split(' ')[0]]
    return hits[0] if len(hits) == 1 else None


def agent_from_document(c, line_name='', bill=''):
    """The agent named on a shipping document: by name, by known carrier markers (Mediterranean Shipping → MSC), or by
    the bill prefix (MEDU…). None when nothing matches."""
    found = agent_by_name(c, line_name)
    if found:
        return found
    try:
        from app.shipping_agents import identify_agent
        agent, score, _ = identify_agent(str(line_name or ''))
        if agent and score >= 0.6:
            return {'id': agent['id'], 'name': agent['name']}
    except Exception as exc:
        print('LINE_DESK_IDENTIFY', type(exc).__name__, str(exc)[:120], flush=True)
    name = PREFIX_AGENT.get(re.sub(r'[^A-Z]', '', str(bill or '').upper())[:4])
    return agent_by_name(c, name) if name else None


def agent_for(c, row):
    if row.get('agent_id'):
        found = c.execute('SELECT id,name FROM shipping_agents WHERE id=%s', (row['agent_id'],)).fetchone() if _has(c, 'shipping_agents') else None
        if found:
            return found
    name = PREFIX_AGENT.get(str(row.get('container') or '')[:4])
    return agent_by_name(c, name) if name else None


def autolink(c, row):
    """Set agent_id from the container prefix when not set yet. Returns the agent or None."""
    init()
    if row.get('agent_id'):
        return agent_for(c, row)
    agent = agent_for(c, row)
    if agent:
        c.execute('UPDATE container_returns SET agent_id=%s WHERE id=%s', (agent['id'], row['id']))
    return agent


def contact_for(c, agent_id):
    rows = c.execute("""SELECT purpose,email FROM shipping_agent_contacts WHERE agent_id=%s AND email IS NOT NULL AND email<>''
        AND status='active' ORDER BY id""", (agent_id,)).fetchall()
    for key in CONTACT_ORDER:
        for r in rows:
            if key in r['purpose'].casefold():
                return r
    return rows[0] if rows else None


# ---------- tariff & cost ----------

def parse_tiers(text):
    """«1-5:150، 6-10:300، 11+:450» (days after the free period : SAR per day) → [(from, to|None, rate)]."""
    out = []
    norm = str(text or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩،', '0123456789,'))
    for m in re.finditer(r'(\d+)\s*(?:-\s*(\d+)|(\+))\s*[:=]\s*(\d+(?:\.\d+)?)', norm):
        lo, hi = int(m.group(1)), (int(m.group(2)) if m.group(2) else None)
        if hi is not None and hi < lo:
            raise ValueError('مدى أيام غير صحيح: ' + m.group(0))
        out.append((lo, hi, float(m.group(4))))
    out.sort()
    if not out or out[0][0] != 1:
        raise ValueError('اكتب الشرائح من أول يوم تأخير، مثل: 1-5:150، 6-10:300، 11+:450')
    for (a, b, _), (n, _, _) in zip(out, out[1:]):
        if b is None or n != b + 1:
            raise ValueError('الشرائح يجب أن تكون متصلة بلا فراغ ولا تداخل.')
    if out[-1][1] is not None:
        out.append((out[-1][1] + 1, None, out[-1][2]))
    return out


def tiers_cost(days, tiers):
    total = 0.0
    for lo, hi, rate in tiers:
        if days < lo:
            break
        total += (min(days, hi if hi is not None else days) - lo + 1) * rate
    return total


def size_of(value):
    m = re.search(r'(20|40|45)', str(value or ''))
    return m.group(1) if m else ''


def set_tariff(args, actor=''):
    init()
    with db() as c:
        agent = agent_by_name(c, args.get('agent'))
        if not agent:
            return 'لم أتعرف على الوكيل؛ اكتب اسمه كما في صفحة وكلاء الملاحة (مثل Maersk Line، MSC، ONE Line).'
        free = int(re.sub(r'\D', '', str(args.get('free_days') or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))) or 0)
        note = ''
        if free:
            if not 1 <= free <= 60:
                return 'أيام السماح بين 1 و60.'
            c.execute('''INSERT INTO line_free_days(agent_id,days,created_by,created_at) VALUES(%s,%s,%s,%s)
                ON CONFLICT(agent_id) DO UPDATE SET days=EXCLUDED.days,created_by=EXCLUDED.created_by,created_at=EXCLUDED.created_at''',
                      (agent['id'], free, actor, utcnow()))
            note = f"✅ أيام السماح عند {agent['name']}: {free} يوم من تاريخ الوصول (تُستخدم لتقدير آخر يوم مجاني للحاويات المسحوبة من فسح)."
            if not args.get('tiers'):
                return note
        size = size_of(args.get('size')) or 'any'
        try:
            tiers = parse_tiers(args.get('tiers'))
        except ValueError as exc:
            return (note + '\n' if note else '') + str(exc)
        c.execute('''INSERT INTO line_tariffs(agent_id,size,tiers_json,note,created_by,created_at) VALUES(%s,%s,%s,%s,%s,%s)
            ON CONFLICT(agent_id,size) DO UPDATE SET tiers_json=EXCLUDED.tiers_json,note=EXCLUDED.note,created_by=EXCLUDED.created_by,
            created_at=EXCLUDED.created_at''', (agent['id'], size, json.dumps(tiers), str(args.get('note') or '')[:300], actor, utcnow()))
    shown = '، '.join(f"{lo}-{hi}: {rate:,.0f}" if hi else f"{lo}+: {rate:,.0f}" for lo, hi, rate in tiers)
    return (note + '\n' if note else '') + f"✅ تعرفة تأخير {agent['name']} ({'كل المقاسات' if size == 'any' else size + ' قدم'}) بعد المدة المجانية — ريال/يوم: {shown}"


def free_days_for(c, agent_id):
    if not agent_id:
        return None
    row = c.execute('SELECT days FROM line_free_days WHERE agent_id=%s', (agent_id,)).fetchone()
    return row['days'] if row else None


def tiers_for(c, agent_id, size):
    if not agent_id:
        return None
    row = c.execute('''SELECT tiers_json FROM line_tariffs WHERE agent_id=%s AND size IN (%s,'any')
        ORDER BY (size='any') LIMIT 1''', (agent_id, size or 'any')).fetchone()
    return [tuple(t) for t in json.loads(row['tiers_json'])] if row else None


def returned_on(c, row):
    if row.get('returned_on'):
        return row['returned_on']
    if row.get('status') in ('returned', 'closed'):
        ev = c.execute("SELECT created_at FROM container_return_events WHERE container_id=%s AND event='returned' ORDER BY id LIMIT 1",
                       (row['id'],)).fetchone()
        if ev:
            return ev['created_at'].astimezone(dt.timezone(dt.timedelta(hours=3))).date()
    return None


def estimate(c, row, today=None):
    """Days over the free period and cost so far (confirmed daily cost first, then the agent tariff)."""
    if not row.get('free_until'):
        return None
    end = returned_on(c, row) or (today or dt.date.today())
    days = (end - row['free_until']).days
    if row.get('daily_cost'):
        daily = float(row['daily_cost'])
        return {'days': max(days, 0), 'cost': max(days, 0) * daily, 'next': daily, 'basis': 'تكلفة يومية مؤكدة'}
    tiers = tiers_for(c, row.get('agent_id'), row.get('size'))
    if not tiers:
        return {'days': max(days, 0), 'cost': None, 'next': None, 'basis': None}
    d = max(days, 0)
    return {'days': d, 'cost': tiers_cost(d, tiers), 'next': tiers_cost(d + 1, tiers) - tiers_cost(d, tiers),
            'basis': 'تقدير من تعرفة الوكيل المسجلة'}


def card_lines(row):
    """Extra lines for container_returns.card (agent, extension, estimated cost). Never raises."""
    if not _READY:
        return []  # tables are created at startup; never run DDL from inside another open transaction
    try:
        with db() as c:
            agent = agent_for(c, row)
            lines = [f"• وكيل الملاحة: {agent['name']}" if agent else '• وكيل الملاحة: غير محدد — «وكيل الحاوية ... هو ...»']
            if row.get('arrived_on') and row.get('status') == 'open':
                from app import port_terminals
                lines.append('• ' + port_terminals.storage_text(row['arrived_on'], row.get('size')) + ' (تاريخ النزول من فسح — تقديري)')
            if row.get('free_until_estimated'):
                lines.append('• آخر يوم مجاني تقديري (تاريخ الوصول في فسح + أيام السماح للوكيل) — أكده من إشعار الوكيل')
            if row.get('fasah_number'):
                lines.append(f"• من بيان فسح {row['fasah_number']}")
            if row.get('original_free_until') and row.get('free_until') != row['original_free_until']:
                lines.append(f"• مُدّدت المدة المجانية من {row['original_free_until']} إلى {row['free_until']}")
            req = c.execute('''SELECT status FROM free_time_requests WHERE containers_json LIKE %s ORDER BY id DESC LIMIT 1''',
                            ('%"' + row['container'] + '"%',)).fetchone()
            if req:
                lines.append('• طلب التمديد: ' + REQ_STATUS.get(req['status'], req['status']))
            est = estimate(c, row) if not row.get('daily_cost') else None
            if est and est['days'] and est['cost'] is not None:
                lines.append(f"• تأخير تقديري حتى الآن: {est['cost']:,.0f} ريال ({est['basis']})")
        return lines
    except Exception as exc:
        print('LINE_DESK_CARD', type(exc).__name__, str(exc)[:120], flush=True)
        return []


def set_container(args, actor=''):
    """Set the agent (and size) of a container, or of every open container of a bill."""
    from app import container_returns
    init()
    with db() as c:
        agent = agent_by_name(c, args.get('agent')) if args.get('agent') else None
        if args.get('agent') and not agent:
            return 'لم أتعرف على الوكيل؛ اكتب اسمه كما في صفحة وكلاء الملاحة.'
        cno, bill = container_returns.number(args.get('container')), str(args.get('bill') or '').strip()
        if cno:
            rows = c.execute('SELECT * FROM container_returns WHERE container=%s', (cno,)).fetchall()
        elif bill:
            rows = c.execute("SELECT * FROM container_returns WHERE bill=%s AND status IN ('open','delivered','driver_reported')", (bill,)).fetchall()
        else:
            return 'اذكر رقم الحاوية أو البوليصة.'
        if not rows:
            return 'الحاوية غير مسجلة؛ سجلها أولًا («سجل الحاوية ...»).'
        size = size_of(args.get('size'))
        for r in rows:
            c.execute('UPDATE container_returns SET agent_id=COALESCE(%s,agent_id),size=COALESCE(%s,size),updated_at=%s WHERE id=%s',
                      (agent['id'] if agent else None, size or None, utcnow(), r['id']))
            container_returns.event(c, r['id'], 'line_info', f"وكيل: {agent['name'] if agent else '-'} مقاس: {size or '-'}", actor)
    return f"✅ حُدّث {len(rows)} حاوية" + (f" — الوكيل {agent['name']}" if agent else '') + (f' — مقاس {size} قدم' if size else '')


# ---------- free-time extension ----------

def _fmt(d):
    return d.strftime('%d/%m/%Y') if d else '-'


def extension_email(agent_name, bill, rows, days, reason):
    lines = '\n'.join(f"- {r['container']}{' (' + r['size'] + 'ft)' if r.get('size') else ''}: free time until {_fmt(r['free_until'])}"
                      for r in rows)
    subject = f"Free Time Extension Request – B/L {bill or '-'} – {', '.join(r['container'] for r in rows)[:120]}"
    body = (f"Dear {agent_name} Team,\n\n"
            f"Kindly approve an extension of the free time (demurrage/detention) by {days} days for the following container(s):\n"
            f"{lines}\nB/L No.: {bill or 'please refer to the container numbers'}\n\n"
            f"Reason: {reason or 'customs clearance procedures are still in progress at Jeddah Islamic Port.'}\n\n"
            'Please confirm the approval and the new free time expiry date for each container.\n\n'
            'السادة المحترمين، نرجو التكرم بالموافقة على تمديد المدة المجانية للحاويات أعلاه '
            f'لمدة {days} أيام وإفادتنا بالتاريخ الجديد.\n\n'
            'Best regards,\nAfaq Tuwaiq Customs Clearance & Logistics\nآفاق طويق للتخليص الجمركي والنقل\n+966 50 766 5873')
    return subject, body


def _open_rows(c, containers=None, bill=None):
    from app import container_returns
    nums = [container_returns.number(x) for x in (containers or []) if container_returns.number(x)]
    if nums:
        return c.execute("SELECT * FROM container_returns WHERE container = ANY(%s) AND status IN ('open','delivered','driver_reported')",
                         (nums,)).fetchall()
    if bill:
        return c.execute("SELECT * FROM container_returns WHERE bill=%s AND status IN ('open','delivered','driver_reported')",
                         (str(bill).strip(),)).fetchall()
    return []


def prepare_extension(c, rows, days, reason, actor):
    """Group containers by agent+bill → draft requests. Returns (list of (request_id, text)), problems."""
    init()
    groups, problems = {}, []
    for r in rows:
        if not r.get('free_until'):
            problems.append(f"{r['container']}: آخر يوم مجاني غير مسجل")
            continue
        agent = autolink(c, r)
        if not agent:
            problems.append(f"{r['container']}: الوكيل غير محدد — اكتب «وكيل الحاوية {r['container']} هو ...»")
            continue
        groups.setdefault((agent['id'], agent['name'], r.get('bill') or ''), []).append(r)
    out = []
    for (agent_id, name, bill), items in groups.items():
        contact = contact_for(c, agent_id)
        if not contact:
            problems.append(f'{name}: لا يوجد بريد للوكيل في صفحة وكلاء الملاحة')
            continue
        subject, body = extension_email(name, bill, items, days, reason)
        rid = c.execute('''INSERT INTO free_time_requests(agent_id,bill,containers_json,days,recipient,subject,body,status,created_by,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,'draft',%s,%s) RETURNING id''',
                        (agent_id, bill or None, json.dumps([r['container'] for r in items]), days, contact['email'], subject, body,
                         actor, utcnow())).fetchone()['id']
        out.append((rid, f"📨 طلب تمديد #{rid} إلى {name} ({contact['email']}) لمدة {days} أيام — الحاويات: "
                         + '، '.join(f"{r['container']} (حتى {_fmt(r['free_until'])})" for r in items)))
    return out, problems


def request_extension(args, actor='', make_token=None):
    """Team command: prepare the extension email(s). make_token(action) → confirmation code (command chat)."""
    init()
    days = int(re.sub(r'\D', '', str(args.get('days') or '')) or DEFAULT_EXTENSION_DAYS)
    if not 1 <= days <= 30:
        return 'مدة التمديد بين 1 و30 يومًا.'
    with db() as c:
        rows = _open_rows(c, args.get('containers') or ([args['container']] if args.get('container') else []), args.get('bill'))
        if not rows:
            return 'لم أجد حاوية مفتوحة بهذا الرقم أو البوليصة. سجلها أولًا («سجل الحاوية ...»).'
        made, problems = prepare_extension(c, rows, days, args.get('reason'), actor)
        lines = []
        for rid, text in made:
            token = make_token({'tool': 'agent_email_send', 'kind': 'extension', 'id': rid}) if make_token else ''
            lines.append(text + (f'\nللإرسال من البريد الرسمي اكتب: نفذ {token}' if token else ''))
    return '\n\n'.join(lines + (['⚠️ ' + p for p in problems] if problems else [])) or 'لم يُجهز شيء.'


def _official_user(c):
    from app import spacemail
    row = c.execute('''SELECT s.user_id FROM spacemail_connections s JOIN users u ON u.id=s.user_id
        WHERE s.enabled AND s.address=%s AND u.role='admin' ORDER BY s.user_id LIMIT 1''', (spacemail.ADDRESS,)).fetchone()
    return row['user_id'] if row else None


def send(kind, item_id, actor=''):
    """Send a prepared extension / reminder / objection email from the official mailbox (after «نفذ»)."""
    from app import spacemail
    init()
    table = {'extension': 'free_time_requests', 'reminder': 'free_time_requests', 'claim': 'detention_claims'}.get(kind)
    if not table:
        return 'نوع غير معروف؛ لم يُرسل شيء.'
    with db() as c:
        row = c.execute('SELECT * FROM ' + table + ' WHERE id=%s', (int(item_id),)).fetchone()
        if not row or not row.get('recipient'):
            return 'الطلب غير موجود؛ لم يُرسل شيء.'
        if kind == 'extension' and row['status'] != 'draft':
            return f"طلب التمديد #{row['id']} حالته «{REQ_STATUS.get(row['status'], row['status'])}»؛ لم أرسله مرة ثانية."
        if kind == 'reminder' and row['status'] != 'sent':
            return 'طلب التمديد لم يعد بانتظار الرد؛ لم يُرسل تذكير.'
        if kind == 'claim' and row['status'] == 'sent':
            return 'الاعتراض أُرسل سابقًا؛ لم أرسله مرة ثانية.'
        uid = _official_user(c)
    if not uid:
        return 'البريد الرسمي غير متصل؛ لم يُرسل شيء.'
    subject, body = row['subject'], row['body']
    if kind == 'reminder':
        subject = 'Reminder: ' + subject
        body = (f"Dear Team,\n\nGentle reminder regarding our free time extension request sent on {_fmt(row['sent_at'].date())}. "
                'The free time is about to expire; kindly confirm the extension at your earliest.\n\n' + body)
    try:
        spacemail.send(uid, row['recipient'], subject, body)
    except Exception as exc:
        return 'تعذر إرسال البريد (' + type(exc).__name__ + '). لم أعد المحاولة.'
    with db() as c:
        if kind == 'extension':
            c.execute("UPDATE free_time_requests SET status='sent',sent_at=%s WHERE id=%s", (utcnow(), row['id']))
        elif kind == 'reminder':
            c.execute('UPDATE free_time_requests SET reminders=reminders+1,reminded_at=%s WHERE id=%s', (utcnow(), row['id']))
        else:
            c.execute("UPDATE detention_claims SET status='sent',sent_at=%s WHERE id=%s", (utcnow(), row['id']))
        c.execute("INSERT INTO activity(user_id,action,entity_type,summary,created_at) VALUES(%s,'line_desk_email','email',%s,NOW())",
                  (uid, f"{kind} #{row['id']} إلى {row['recipient']}"))
    label = {'extension': 'طلب التمديد', 'reminder': 'تذكير الوكيل', 'claim': 'الاعتراض على الغرامة'}[kind]
    return f"✅ أُرسل {label} #{row['id']} إلى {row['recipient']} من {spacemail.ADDRESS}."


def record_result(args, actor=''):
    """«تم تمديد MSKU1234567 حتى 20/11» / «رفض الوكيل تمديد ...»."""
    from app import container_returns
    init()
    approved = str(args.get('result') or 'approved') != 'rejected'
    until = container_returns.date(args.get('until'))
    if approved and not until:
        return 'اكتب التاريخ الجديد الذي أكده الوكيل، مثل: تم تمديد MSKU1234567 حتى 20/11.'
    with db() as c:
        rows = _open_rows(c, args.get('containers') or ([args['container']] if args.get('container') else []), args.get('bill'))
        if not rows:
            return 'لم أجد حاوية مفتوحة بهذا الرقم أو البوليصة.'
        done = []
        for r in rows:
            if approved:
                if r.get('free_until') and until <= r['free_until']:
                    done.append(f"{r['container']}: التاريخ {_fmt(until)} ليس بعد المدة الحالية ({_fmt(r['free_until'])}) — لم يُغيّر")
                    continue
                c.execute('''UPDATE container_returns SET original_free_until=COALESCE(original_free_until,free_until),free_until=%s,
                    last_alert=NULL,last_alert_on=NULL,updated_at=%s WHERE id=%s''', (until, utcnow(), r['id']))
                container_returns.event(c, r['id'], 'free_time_extended', f"{_fmt(r.get('free_until'))} → {_fmt(until)} {args.get('note') or ''}", actor)
                done.append(f"{r['container']}: آخر يوم مجاني أصبح {_fmt(until)} ✅")
            else:
                container_returns.event(c, r['id'], 'free_time_rejected', str(args.get('note') or ''), actor)
                done.append(f"{r['container']}: رفض الوكيل التمديد — يبقى آخر يوم {_fmt(r.get('free_until'))} ❌")
            for req in c.execute("""SELECT id FROM free_time_requests WHERE status IN ('draft','sent') AND containers_json LIKE %s""",
                                 ('%"' + r['container'] + '"%',)).fetchall():
                c.execute('UPDATE free_time_requests SET status=%s,new_until=%s,decided_at=%s,note=%s WHERE id=%s',
                          ('approved' if approved else 'rejected', until if approved else None, utcnow(), str(args.get('note') or '')[:300], req['id']))
    tail = '' if approved else '\nأسرّع الإرجاع: ذكّر العميل والسائق من «حالة الحاويات».'
    return '\n'.join(done) + tail


# ---------- fine audit ----------

def audit_claim(args, actor='', make_token=None):
    """Check an agent detention invoice against free days, extensions, proven return date and tariff."""
    from app import container_returns
    init()
    cno = container_returns.number(args.get('container'))
    try:
        claimed = float(str(args.get('amount') or '').replace(',', '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')))
    except ValueError:
        claimed = 0
    if not cno or claimed <= 0:
        return 'اذكر رقم الحاوية ومبلغ الغرامة في فاتورة الوكيل، مثل: غرامة الحاوية MSKU1234567 مبلغ 4500.'
    with db() as c:
        row = c.execute('SELECT * FROM container_returns WHERE container=%s', (cno,)).fetchone()
        if not row:
            return 'الحاوية غير مسجلة؛ لا أستطيع تدقيق الغرامة بدون آخر يوم مجاني وتاريخ الإرجاع.'
        agent = autolink(c, row)
        ret = container_returns.date(args.get('returned_on')) or returned_on(c, row)
        if not row.get('free_until') or not ret:
            return 'أحتاج آخر يوم مجاني وتاريخ إرجاع مثبت للحاوية قبل تدقيق الغرامة.'
        days_expected = max((ret - row['free_until']).days, 0)
        charged = int(re.sub(r'\D', '', str(args.get('days') or '')) or 0) or None
        est = estimate(c, row)
        expected = est['cost'] if est else None
        facts = [f"آخر يوم مجاني: {_fmt(row['free_until'])}" + (f" (بعد التمديد من {_fmt(row['original_free_until'])})" if row.get('original_free_until') else ''),
                 f"تاريخ الإرجاع المثبت: {_fmt(ret)}" + (f" — الإثبات: {row['proof']}" if row.get('proof') else ''),
                 f'أيام التأخير المستحقة: {days_expected}' + (f' (الوكيل احتسب {charged})' if charged else '')]
        if expected is None:
            verdict = 'unknown'
            facts.append('لا توجد تكلفة يومية مؤكدة ولا تعرفة مسجلة لهذا الوكيل؛ سجّل التعرفة لأحسب المبلغ المتوقع.')
        else:
            facts.append(f"المبلغ المتوقع: {expected:,.0f} ريال ({est['basis']}) — المطالَب: {claimed:,.0f} ريال")
            verdict = 'over' if claimed > expected * TOLERANCE + 1 or (charged and charged > days_expected) else 'ok'
        subject = body = recipient = None
        if verdict == 'over' and agent:
            contact = contact_for(c, agent['id'])
            recipient = contact['email'] if contact else None
            subject = f"Objection to Detention Invoice – Container {cno} – B/L {row.get('bill') or '-'}"
            body = (f"Dear {agent['name']} Team,\n\nWe object to the detention charges invoiced for container {cno} "
                    f"(SAR {claimed:,.2f}).\n\n"
                    f"- Free time valid until: {_fmt(row['free_until'])}"
                    + (f" (extension approved; original {_fmt(row['original_free_until'])})" if row.get('original_free_until') else '') + '\n'
                    f"- Empty container returned on: {_fmt(ret)}" + (f" (EIR / proof: {row['proof']})" if row.get('proof') else '') + '\n'
                    f'- Chargeable days: {days_expected}' + (f' (invoice shows {charged})' if charged else '') + '\n'
                    + (f'- Amount per your tariff: SAR {expected:,.2f}\n' if expected is not None else '')
                    + '\nKindly review and issue a corrected invoice.\n\nBest regards,\n'
                    'Afaq Tuwaiq Customs Clearance & Logistics\n+966 50 766 5873')
        cid = c.execute('''INSERT INTO detention_claims(container_id,agent_id,claimed,expected,days_charged,days_expected,verdict,
            recipient,subject,body,status,created_by,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                        (row['id'], agent['id'] if agent else None, claimed, expected, charged, days_expected, verdict, recipient,
                         subject, body, 'draft' if recipient else 'recorded', actor, utcnow())).fetchone()['id']
        container_returns.event(c, row['id'], 'detention_claim', f'#{cid} {claimed:,.0f} {verdict}', actor)
    head = {'over': f'🔴 غرامة الحاوية {cno} أعلى من المستحق', 'ok': f'✅ غرامة الحاوية {cno} مطابقة للحساب',
            'unknown': f'⚠️ غرامة الحاوية {cno} — لا أستطيع الحكم بعد'}[verdict]
    out = head + ':\n' + '\n'.join('• ' + f for f in facts)
    if verdict == 'over':
        if recipient and make_token:
            token = make_token({'tool': 'agent_email_send', 'kind': 'claim', 'id': cid})
            out += f'\n📨 اعتراض جاهز إلى {recipient} مع التواريخ والإثبات. للإرسال اكتب: نفذ {token}'
        elif not recipient:
            out += '\nلا يوجد بريد للوكيل أو الوكيل غير محدد؛ الاعتراض محفوظ في صفحة مكتب الحاويات.'
    return out


# ---------- overview ----------

def exposure_text(today=None):
    init()
    today = today or dt.date.today()
    with db() as c:
        rows = c.execute("SELECT * FROM container_returns WHERE status IN ('open','delivered','driver_reported') AND NOT is_test").fetchall()
        groups = {}
        for r in rows:
            agent = agent_for(c, r)
            g = groups.setdefault(agent['name'] if agent else 'وكيل غير محدد',
                                  {'n': 0, 'over': 0, 'soon': 0, 'cost': 0.0, 'next': 0.0, 'unknown': 0})
            g['n'] += 1
            if r.get('free_until'):
                left = (r['free_until'] - today).days
                g['soon'] += 0 <= left <= LEAD_DAYS
                if left < 0:
                    g['over'] += 1
                    est = estimate(c, r, today)
                    if est and est['cost'] is not None:
                        g['cost'] += est['cost']
                        g['next'] += est['next'] or 0
                    else:
                        g['unknown'] += 1
        pend = c.execute("SELECT status,COUNT(*) n FROM free_time_requests GROUP BY status").fetchall()
    if not rows:
        return 'لا توجد حاويات مفتوحة.'
    lines = ['🚢 مكتب الحاويات — التعرض لغرامات التأخير']
    total = sum(g['cost'] for g in groups.values())
    for name, g in sorted(groups.items(), key=lambda kv: -kv[1]['cost']):
        lines.append(f"• {name}: {g['n']} حاوية — متأخرة {g['over']}، تنتهي خلال {LEAD_DAYS} أيام {g['soon']}"
                     + (f" — تقديري {g['cost']:,.0f} ريال ويزيد {g['next']:,.0f} غدًا" if g['cost'] else '')
                     + (f" — {g['unknown']} بلا تعرفة" if g['unknown'] else ''))
    lines.append(f'الإجمالي التقديري حتى اليوم: {total:,.0f} ريال')
    if pend:
        lines.append('طلبات التمديد: ' + '، '.join(f"{REQ_STATUS.get(p['status'], p['status'])} {p['n']}" for p in pend))
    return '\n'.join(lines)


def scorecard(c):
    return c.execute('''SELECT a.name, COUNT(r.id) total, COUNT(*) FILTER (WHERE r.status='approved') approved,
        COUNT(*) FILTER (WHERE r.status='rejected') rejected, COUNT(*) FILTER (WHERE r.status='sent') waiting,
        AVG(EXTRACT(EPOCH FROM (r.decided_at-r.sent_at))/3600) FILTER (WHERE r.decided_at IS NOT NULL AND r.sent_at IS NOT NULL) hours
        FROM free_time_requests r JOIN shipping_agents a ON a.id=r.agent_id GROUP BY a.name ORDER BY total DESC''').fetchall()


# ---------- daily automation ----------

def tick(today=None, now=None):
    """Returns manager messages: new extension drafts, reminders for unanswered requests, agent replies seen."""
    from app import transport_desk
    init()
    today = today or dt.date.today()
    now = now or utcnow()
    out = []
    with db() as c:
        chat = transport_desk.manager_chat(c)
        token = (lambda action: transport_desk.pending(c, chat[0], chat[1], action, 12 * 60)) if chat else None
        # 1) Containers ending within LEAD_DAYS without any request → draft one per agent/bill.
        rows = c.execute("""SELECT * FROM container_returns WHERE status IN ('open','delivered','driver_reported') AND NOT is_test
            AND free_until BETWEEN %s AND %s""", (today, today + dt.timedelta(days=LEAD_DAYS))).fetchall()
        fresh = [r for r in rows if not c.execute('''SELECT 1 FROM free_time_requests WHERE containers_json LIKE %s
            AND (status IN ('draft','sent') OR created_at>%s)''', ('%"' + r['container'] + '"%', now - dt.timedelta(days=LEAD_DAYS + 1))).fetchone()]
        if fresh:
            made, problems = prepare_extension(c, fresh, DEFAULT_EXTENSION_DAYS, '', 'مكتب الحاويات')
            for rid, text in made:
                code = token({'tool': 'agent_email_send', 'kind': 'extension', 'id': rid}) if token else ''
                est = any(r.get('free_until_estimated') and r['container'] in text for r in fresh)
                out.append('⏳ المدة المجانية تنتهي قريبًا — جهزت طلب تمديد للوكيل.\n' + text
                           + ('\n⚠️ آخر يوم مجاني تقديري من فسح؛ تأكد منه قبل الإرسال.' if est else '')
                           + (f'\nللإرسال اكتب: نفذ {code}' if code else '\nأرسله من صفحة مكتب الحاويات.'))
            unknown = [p for p in problems if 'الوكيل غير محدد' in p or 'بريد' in p]
            if unknown:
                key = 'unknown:' + ','.join(sorted(unknown))
                if not c.execute("SELECT 1 FROM container_return_events WHERE event='line_desk_notice' AND note=%s AND created_at>%s",
                                 (key[:1000], now - dt.timedelta(days=1))).fetchone():
                    out.append('⚠️ لا أستطيع تجهيز طلب تمديد:\n' + '\n'.join('• ' + p for p in unknown))
                    first = fresh[0]['id']
                    c.execute("""INSERT INTO container_return_events(container_id,event,note,actor,created_at)
                        VALUES(%s,'line_desk_notice',%s,'مكتب الحاويات',%s)""", (first, key[:1000], now))
        # 1b) Port storage: last free day at the terminal (3 days from discharge) for containers still in the port.
        from app import port_terminals
        for r in c.execute("""SELECT * FROM container_returns WHERE status='open' AND NOT is_test AND arrived_on=%s""",
                           (today - dt.timedelta(days=port_terminals.FREE_DAYS - 1),)).fetchall():
            if c.execute("SELECT 1 FROM container_return_events WHERE container_id=%s AND event='port_storage_notice'", (r['id'],)).fetchone():
                continue
            c.execute("""INSERT INTO container_return_events(container_id,event,note,actor,created_at)
                VALUES(%s,'port_storage_notice','',%s,%s)""", (r['id'], 'مكتب الحاويات', now))
            rate = port_terminals.IMPORT_TIERS[0][2 if port_terminals.size_key(r.get('size')) == 20 else 3]
            out.append(f"⚓ الحاوية {r['container']}{' — ' + r['customer'] if r.get('customer') else ''}: اليوم آخر يوم مجاني من أرضيات الميناء "
                       f"(نزلت {_fmt(r['arrived_on'])} حسب فسح). من الغد {rate} ريال/يوم للمشغل، غير غرامة الوكيل الملاحي. "
                       'إذا خرجت من الميناء اكتب: «سلمت الحاوية ...».')
        # 2) Sent requests with no answer for 24h → reminder draft (once a day, at most 3).
        for req in c.execute("""SELECT r.*,a.name agent FROM free_time_requests r JOIN shipping_agents a ON a.id=r.agent_id
                WHERE r.status='sent' AND r.sent_at<%s AND r.reminders<3 AND (r.reminded_at IS NULL OR r.reminded_at<%s)""",
                             (now - REMIND_AFTER, now - REMIND_AFTER)).fetchall():
            c.execute('UPDATE free_time_requests SET reminded_at=%s WHERE id=%s', (now, req['id']))
            code = token({'tool': 'agent_email_send', 'kind': 'reminder', 'id': req['id']}) if token else ''
            out.append(f"⏰ {req['agent']} لم يرد على طلب التمديد #{req['id']} منذ {_fmt(req['sent_at'].date())} "
                       f"({', '.join(json.loads(req['containers_json']))})." + (f'\nلإرسال تذكير اكتب: نفذ {code}' if code else ''))
        # 3) Agent replies in the official mailbox that mention the container or bill.
        if _has(c, 'spacemail_inbox'):
            for req in c.execute("SELECT * FROM free_time_requests WHERE status='sent'").fetchall():
                keys = json.loads(req['containers_json']) + ([req['bill']] if req.get('bill') else [])
                mail = c.execute('''SELECT id,sender,subject,body FROM spacemail_inbox WHERE id>%s AND imported_at>=%s
                    AND (''' + ' OR '.join(['(subject ILIKE %s OR body ILIKE %s)'] * len(keys)) + ') ORDER BY id DESC LIMIT 1',
                                 (req.get('last_inbox_id') or 0, req['sent_at'], *[p for k in keys for p in ('%' + k + '%',) * 2])).fetchone()
                if mail:
                    c.execute('UPDATE free_time_requests SET last_inbox_id=%s WHERE id=%s', (mail['id'], req['id']))
                    snippet = re.sub(r'\s+', ' ', str(mail['body'] or ''))[:400]
                    out.append(f"📩 رد على طلب التمديد #{req['id']} من {mail['sender']}:\n«{mail['subject']}»\n{snippet}\n"
                               f"لتسجيل النتيجة: «تم تمديد {json.loads(req['containers_json'])[0]} حتى dd/mm» أو «رفض الوكيل تمديد ...».")
    return out


def register_worker(app):
    async def loop():
        from starlette.concurrency import run_in_threadpool
        from app.owner_briefing import deliver
        await asyncio.sleep(240)
        while True:
            try:
                for text in await run_in_threadpool(tick):
                    await deliver(text)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('LINE_DESK_WORKER', type(exc).__name__, str(exc)[:160], flush=True)
            await asyncio.sleep(1800)

    @app.on_event('startup')
    async def start():
        init()
        if os.getenv('LINE_DESK_ENABLED', '1') != '0':
            app.state.line_desk_worker = asyncio.create_task(loop())


# ---------- page ----------

def _money(v):
    return '' if v is None else f'{float(v):,.0f}'


@router.get('/containers/desk', response_class=HTMLResponse)
def page(request: Request):
    from app.naqliat_connector import _page, _session
    _session(request)
    init()
    e = lambda v: html.escape(str(v if v is not None else ''))
    today = dt.date.today()
    with db() as c:
        rows = c.execute("""SELECT * FROM container_returns WHERE status IN ('open','delivered','driver_reported')
            ORDER BY free_until NULLS LAST LIMIT 200""").fetchall()
        trs = ''
        for r in rows:
            agent = agent_for(c, r)
            est = estimate(c, r, today)
            left = (r['free_until'] - today).days if r.get('free_until') else None
            color = '' if left is None else '#ff5c5c' if left < 0 else '#ffb020' if left <= LEAD_DAYS else ''
            cost = '' if not est or est['cost'] is None or not est['days'] else f"{est['cost']:,.0f}"
            trs += (f'<tr style="color:{color}"><td>{e(r["container"])}</td><td>{e(agent["name"] if agent else "غير محدد")}</td>'
                    f'<td>{e(r.get("size"))}</td><td>{e(r.get("bill"))}</td><td>{e(r.get("free_until"))}</td>'
                    f'<td>{"" if left is None else e(left)}</td><td>{e(cost)}</td></tr>')
        reqs = c.execute('''SELECT r.*,a.name agent FROM free_time_requests r JOIN shipping_agents a ON a.id=r.agent_id
            ORDER BY r.id DESC LIMIT 100''').fetchall()
        claims = c.execute('''SELECT d.*,x.container,a.name agent FROM detention_claims d JOIN container_returns x ON x.id=d.container_id
            LEFT JOIN shipping_agents a ON a.id=d.agent_id ORDER BY d.id DESC LIMIT 100''').fetchall()
        score = scorecard(c)
    req_rows = ''.join(f"<tr><td>#{r['id']}</td><td>{e(r['agent'])}</td><td>{e(', '.join(json.loads(r['containers_json'])))}</td>"
                       f"<td>{e(r['days'])}</td><td>{e(REQ_STATUS.get(r['status'], r['status']))}</td><td>{e(r.get('new_until'))}</td>"
                       f"<td>{e(r['sent_at'].date() if r.get('sent_at') else '')}</td></tr>" for r in reqs)
    claim_rows = ''.join(f"<tr><td>{e(r['container'])}</td><td>{e(r.get('agent'))}</td><td>{float(r['claimed']):,.0f}</td>"
                         f"<td>{_money(r.get('expected'))}</td>"
                         f"<td>{e({'over': 'أعلى من المستحق', 'ok': 'مطابقة', 'unknown': 'بلا تعرفة'}.get(r['verdict'], r['verdict']))}</td>"
                         f"<td>{e(r['status'])}</td></tr>" for r in claims)
    score_rows = ''.join(f"<tr><td>{e(s['name'])}</td><td>{s['total']}</td><td>{s['approved']}</td><td>{s['rejected']}</td>"
                         f"<td>{s['waiting']}</td><td>{_money(s['hours'])}</td></tr>"
                         for s in score)
    body = ('<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/containers">إرجاع الحاويات</a>'
            '<a href="/shipping-agents">وكلاء الملاحة</a></div><h1>مكتب الحاويات ووكلاء الملاحة</h1>'
            f'<p class="muted">قبل انتهاء المدة المجانية بـ{LEAD_DAYS} أيام يُجهز طلب تمديد لكل وكيل ويُرسل من البريد الرسمي بعد «نفذ». '
            'الأوامر من واتساب: «وكيل الحاوية ... هو MSC مقاس 40»، «تعرفة MSC 40: 1-5:150، 6-10:300، 11+:450»، '
            '«اطلب تمديد الحاوية ... 7 أيام»، «تم تمديد ... حتى 20/11»، «غرامة الحاوية ... مبلغ 4500»، «تعرض الغرامات».</p>'
            '<div class="card scroll"><h2>الحاويات المفتوحة</h2><table><tr><th>الحاوية</th><th>الوكيل</th><th>المقاس</th><th>البوليصة</th>'
            '<th>آخر يوم مجاني</th><th>الأيام المتبقية</th><th>تأخير تقديري (ريال)</th></tr>' + trs + '</table></div>'
            '<div class="card scroll"><h2>طلبات التمديد</h2><table><tr><th>#</th><th>الوكيل</th><th>الحاويات</th><th>أيام</th><th>الحالة</th>'
            '<th>التاريخ الجديد</th><th>أُرسل</th></tr>' + (req_rows or '<tr><td colspan=7>لا توجد طلبات بعد.</td></tr>') + '</table></div>'
            '<div class="card scroll"><h2>تدقيق فواتير الغرامات</h2><table><tr><th>الحاوية</th><th>الوكيل</th><th>المطالَب</th><th>المتوقع</th>'
            '<th>النتيجة</th><th>الحالة</th></tr>' + (claim_rows or '<tr><td colspan=6>لا توجد فواتير مدققة.</td></tr>') + '</table></div>'
            '<div class="card scroll"><h2>تقييم الوكلاء في التمديد</h2><table><tr><th>الوكيل</th><th>طلبات</th><th>وافق</th><th>رفض</th>'
            '<th>بلا رد</th><th>متوسط الرد (ساعة)</th></tr>' + (score_rows or '<tr><td colspan=6>لا توجد بيانات بعد.</td></tr>') + '</table></div>')
    return HTMLResponse(_page('مكتب الحاويات', body))
