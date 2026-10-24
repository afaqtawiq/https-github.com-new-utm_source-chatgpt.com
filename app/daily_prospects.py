"""Daily prospect list: turns the registered customer roster into a ranked, reviewed call list.

Nothing here sends a message. Approval creates an opportunity, a call follow-up and, for
email contacts, an outbound draft that still goes through the existing send approval.
WhatsApp contact happens by a team member from their own phone via a prefilled link.
"""
import html
import json
import os
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qs, quote, urlencode
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.marketing_content import PHONE, WEBSITE, email_address, whatsapp_number
from app.storage import db, get_session, log, one, rows, utcnow

router = APIRouter()
RIYADH = ZoneInfo('Asia/Riyadh')
OWNER = 'مرشحو اليوم'
STATUSES = {
    'pending': 'بانتظار المراجعة', 'approved': 'معتمد للتواصل', 'contacted': 'تم التواصل',
    'interested': 'مهتم', 'not_interested': 'غير مهتم', 'no_answer': 'لم يرد', 'rejected': 'مستبعد',
}
BLOCKED = {'unsubscribed', 'do_not_contact', 'opted_out', 'محظور', 'إيقاف', 'lost', 'customer_lost'}

SEGMENTS = [
    # key, label, score, patterns, pitch
    ('china', 'استيراد من الصين', 25, r'الصين|صيني|china|chinese|وسيط توريد|sourcing',
     'نخدم المستوردين من الصين في تخليص الشحنات الكاملة والمجمّعة بميناء جدة، مع متابعة المستندات وشهادات المطابقة ونقلها حتى مستودعكم.'),
    ('food', 'مواد غذائية', 20, r'غذا|اغذي|أغذي|food|foods|توابل|spice|تمور|dates|فواكه|fruit|fisher|اسماك',
     'نتابع تخليص المواد الغذائية بميناء جدة بما فيها متطلبات هيئة الغذاء والدواء، مع ترتيب النقل إلى مستودعاتكم.'),
    ('cars', 'سيارات وقطع غيار', 20, r'سيار|قطع غيار|محركات|auto|car|cars|motor|bearing|نيسان',
     'نخدم مستوردي السيارات وقطع الغيار في التخليص الجمركي بميناء جدة ومتابعة متطلبات سابر والنقل إلى معارضكم ومستودعاتكم.'),
    ('industrial', 'مصانع ومعدات', 12, r'مصنع|مصانع|صناع|steel|حديد|المنيوم|ألمنيوم|معدات|cranes|سلامة|سلامه|manufactur',
     'نتابع تخليص المواد الخام والمعدات بميناء جدة والمنافذ البرية، ونرتب النقل والمناولة حتى موقعكم.'),
    ('trade', 'استيراد وتصدير', 15, r'استيراد|مستورد|تصدير|import|export|trading|تجار',
     'نقدم التخليص الجمركي بميناء جدة والمنافذ البرية، واستقبال الشحنات والنقل البري والتخزين، بخدمة واحدة من الميناء إلى مستودعكم.'),
]
DEFAULT_PITCH = ('نقدم التخليص الجمركي بميناء جدة والمنافذ البرية، واستقبال الشحنات والنقل البري والتخزين، '
                 'بخدمة واحدة من الميناء إلى مستودعكم.')
CITY_SCORE = {'جدة': 15, 'جده': 15, 'jeddah': 15, 'الرياض': 8, 'riyadh': 8, 'الدمام': 8, 'dammam': 8, 'الخبر': 6, 'مكة': 6}


def daily_target():
    try:
        return max(5, min(100, int(os.getenv('DAILY_PROSPECTS', '30'))))
    except ValueError:
        return 30


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS daily_prospects(
            id BIGSERIAL PRIMARY KEY, source_key TEXT UNIQUE NOT NULL, company_name TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT '',
            activity TEXT NOT NULL DEFAULT '', website TEXT NOT NULL DEFAULT '', score INTEGER NOT NULL,
            segment TEXT NOT NULL, reason TEXT NOT NULL, message TEXT NOT NULL, message_source TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', batch_date DATE NOT NULL, opportunity_id BIGINT,
            outcome_note TEXT, decided_by BIGINT, decided_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS daily_prospects_batch_idx ON daily_prospects(batch_date,status)')
    refresh_pending_messages()


def esc(value):
    return html.escape(str(value or ''))


def _norm(text):
    return re.sub(r'[ً-ٟـ]', '', str(text or '')).lower()


def classify(company_name, activity='', notes=''):
    text = _norm(' '.join(str(v or '') for v in (company_name, activity, notes)))
    for key, label, score, pattern, pitch in SEGMENTS:
        if re.search(pattern, text):
            return key, label, score, pitch
    return 'general', 'نشاط تجاري', 0, DEFAULT_PITCH


def city_of(*values):
    for value in values:
        for city in CITY_SCORE:
            if city in _norm(value):
                return {'جده': 'جدة', 'jeddah': 'جدة', 'riyadh': 'الرياض', 'dammam': 'الدمام'}.get(city, city)
    return ''


def score_contact(row):
    phone, email = whatsapp_number(row.get('phone')), email_address(row.get('email'))
    segment, label, segment_score, pitch = classify(row.get('company_name'), row.get('activity'), row.get('notes'))
    city = city_of(row.get('city'), row.get('notes'), row.get('company_name'))
    score = 30 + (15 if phone else 0) + (10 if email else 0) + (5 if row.get('website') else 0)
    score += segment_score + CITY_SCORE.get(city, 3 if city else 0)
    reasons = [label]
    if city:
        reasons.append(city + (' — قريب من ميناء جدة' if city == 'جدة' else ''))
    reasons.append('واتساب متاح' if phone else 'بريد فقط')
    return {'score': min(100, score), 'segment': segment, 'label': label, 'pitch': pitch, 'city': city,
            'phone': phone, 'email': email, 'reason': ' · '.join(reasons)}


TRANSPORT_LICENCE = '11/00098402'


from app.official_mailbox import ADDRESS as OFFICIAL_EMAIL  # noqa: E402


def template_message(company_name, pitch):
    return ('السلام عليكم ورحمة الله،\n'
            f'تحية طيبة لفريق {company_name.strip()}.\n'
            'معكم آفاق طويق للتخليص الجمركي والنقل '
            f'(ترخيص مخلص جمركي رقم 2513 وترخيص نقل رقم {TRANSPORT_LICENCE}). {pitch}\n'
            'عرضنا يشمل التخليص الجمركي والنقل البري المرخّص معًا، من الميناء أو المنفذ حتى مستودعكم، بجهة واحدة مسؤولة عن شحنتكم.\n'
            'هل لديكم شحنات قادمة خلال الفترة القادمة؟ يسعدنا تقديم عرض سعر شامل للتخليص والنقل بعد معرفة '
            'نوع البضاعة والوزن أو عدد الحاويات ومدينة التسليم.\n'
            f'للتواصل: {PHONE}\nالبريد: {OFFICIAL_EMAIL}\n{WEBSITE}')


def _template_v2(company_name, pitch):
    return ('السلام عليكم ورحمة الله،\n'
            f'تحية طيبة لفريق {company_name.strip()}.\n'
            'معكم آفاق طويق للتخليص الجمركي والنقل '
            f'(ترخيص مخلص جمركي رقم 2513 وترخيص نقل رقم {TRANSPORT_LICENCE}). {pitch}\n'
            'عرضنا يشمل التخليص الجمركي والنقل البري المرخّص معًا، من الميناء أو المنفذ حتى مستودعكم، بجهة واحدة مسؤولة عن شحنتكم.\n'
            'هل لديكم شحنات قادمة خلال الفترة القادمة؟ يسعدنا تقديم عرض سعر شامل للتخليص والنقل بعد معرفة '
            'نوع البضاعة والوزن أو عدد الحاويات ومدينة التسليم.\n'
            f'للتواصل: {PHONE}\n{WEBSITE}')


def _previous_template(company_name, pitch):
    return ('السلام عليكم ورحمة الله،\n'
            f'تحية طيبة لفريق {company_name.strip()}.\n'
            f'معكم آفاق طويق للتخليص الجمركي والخدمات اللوجستية (ترخيص مخلص جمركي رقم 2513). {pitch}\n'
            'هل لديكم شحنات قادمة خلال الفترة القادمة؟ يسعدنا تقديم عرض سعر بعد معرفة نوع البضاعة والوزن أو عدد الحاويات.\n'
            f'للتواصل: {PHONE}\n{WEBSITE}')


def _with_opening(text, opening):
    lines = text.split('\n')
    return '\n'.join(lines[:2] + [opening] + lines[2:])


def refresh_pending_messages():
    """Bring unedited pending drafts to the current template. Edited or decided drafts are never touched."""
    pitches = {key: pitch for key, _, _, _, pitch in SEGMENTS}
    changed = 0
    for item in rows("SELECT id,company_name,segment,message,message_source FROM daily_prospects WHERE status='pending'"):
        pitch = pitches.get(item['segment'], DEFAULT_PITCH)
        current = template_message(item['company_name'], pitch)
        lines = item['message'].split('\n')
        updated = None
        for builder in (_previous_template, _template_v2):
            old = builder(item['company_name'], pitch).split('\n')
            if lines == old:
                updated = current
            elif item['message_source'] == 'ai' and len(lines) == len(old) and lines[0] == old[0] and lines[2:] == old[2:]:
                updated = _with_opening(current, lines[1])  # first release replaced the greeting line
            elif item['message_source'] == 'ai' and len(lines) == len(old) + 1 and lines[:2] == old[:2] and lines[3:] == old[2:]:
                updated = _with_opening(current, lines[2])
            if updated:
                break
        if not updated or updated == item['message']:
            continue
        with db() as c:
            changed += c.execute("UPDATE daily_prospects SET message=%s,updated_at=%s WHERE id=%s AND status='pending' AND message=%s",
                                 (updated, utcnow(), item['id'], item['message'])).rowcount
    return changed


AI_SYSTEM = ('You write one short Arabic sentence that goes right after the greeting of a first business message '
             'to a company that imports goods. The sender (a licensed customs broker and transport company) introduces '
             'itself in the next sentence, so do NOT name or describe the sender, and do not use the words آفاق or طويق. '
             'Speak only about the recipient: acknowledge its activity and city and say that its incoming shipments may '
             'benefit from clearance and transport handled together. Use only the company name, city and activity provided. '
             'Do not invent facts, numbers, prices, names, dates, links or claims. Polite Saudi business tone, at most 160 '
             'characters, no greeting. Reply only with JSON: {"opening": "..."}')


def ai_opening(company_name, city, label):
    key = os.getenv('ANTHROPIC_API_KEY', '')
    if not key:
        return None
    body = {'model': os.getenv('PROSPECT_AI_MODEL') or os.getenv('INTAKE_MODEL', 'claude-sonnet-5'),
            'max_tokens': 200, 'system': AI_SYSTEM,
            'messages': [{'role': 'user', 'content': json.dumps(
                {'company': company_name[:150], 'city': city or 'غير محدد', 'activity': label}, ensure_ascii=False)}]}
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post('https://api.anthropic.com/v1/messages', json=body,
                                   headers={'x-api-key': key, 'anthropic-version': '2023-06-01'})
            response.raise_for_status()
        out = ''.join(p.get('text', '') for p in response.json().get('content', []) if p.get('type') == 'text')
        match = re.search(r'\{.*\}', out, re.S)
        opening = str(json.loads(match.group(0)).get('opening', '')).strip() if match else ''
    except (httpx.HTTPError, ValueError, KeyError, AttributeError):
        return None
    return opening if valid_opening(opening) else None


def valid_opening(text):
    # Reject anything that could carry an invented fact: digits, links, emails, prices.
    # The sender is introduced by the template; an opening that introduces it again is redundant.
    return (10 <= len(text) <= 200 and not re.search(r'[0-9٠-٩@]|https?:|www\.|ريال|SAR|\$|%|آفاق|افاق|طويق', text)
            and re.search(r'[؀-ۿ]', text) is not None)


def compose(company_name, info, use_ai=True):
    base = template_message(company_name, info['pitch'])
    opening = ai_opening(company_name, info['city'], info['label']) if use_ai else None
    if not opening:
        return base, 'template'
    return _with_opening(base, opening), 'ai'


def candidates():
    pool = rows('''SELECT 'account:' || a.id::text AS source_key, a.name AS company_name, COALESCE(a.phone,'') phone,
            COALESCE(a.email,'') email, COALESCE(a.country,'') city, '' activity, COALESCE(a.domain,'') website,
            COALESCE(a.notes,'') notes, COALESCE(a.status,'') status FROM accounts a
        UNION ALL
        SELECT 'directory:' || d.id::text, d.company_name, COALESCE(d.phone,''), COALESCE(d.email,''),
            COALESCE(d.city,''), COALESCE(d.activity,''), '', COALESCE(d.notes,''), '' FROM customer_directory d''')
    suppressed = {(r['channel'], r['recipient']) for r in rows('SELECT channel,recipient FROM marketing_suppressions')} \
        if one("SELECT to_regclass('marketing_suppressions') t")['t'] else set()
    queued = {r['source_key'] for r in rows('SELECT source_key FROM daily_prospects')}
    queued_phones = {r['phone'] for r in rows("SELECT phone FROM daily_prospects WHERE phone<>''")}
    out, seen = [], set()
    for row in pool:
        if row['source_key'] in queued or str(row['status']).lower() in BLOCKED or not (row['company_name'] or '').strip():
            continue
        info = score_contact(row)
        if not (info['phone'] or info['email']):
            continue
        if ('whatsapp', info['phone']) in suppressed or ('email', info['email']) in suppressed:
            continue
        contact = info['phone'] or info['email']
        if contact in seen or (info['phone'] and info['phone'] in queued_phones):
            continue
        seen.add(contact)
        out.append((row, info))
    out.sort(key=lambda item: (-item[1]['score'], item[0]['source_key']))
    return out


def today():
    return datetime.now(RIYADH).date()


def repair_openings(use_ai=True):
    """Replace pending AI openings that fail the current rules (e.g. re-introduce the sender)."""
    fixed = 0
    for item in rows("SELECT id,company_name,city,activity,message FROM daily_prospects WHERE status='pending' AND message_source='ai'"):
        lines = item['message'].split('\n')
        if len(lines) < 4 or not lines[3].startswith('معكم') or valid_opening(lines[2]):
            continue
        opening = ai_opening(item['company_name'], item['city'], item['activity']) if use_ai else None
        updated = '\n'.join(lines[:2] + ([opening] if opening else []) + lines[3:])
        with db() as c:
            fixed += c.execute("UPDATE daily_prospects SET message=%s,message_source=%s,updated_at=%s WHERE id=%s AND status='pending' AND message=%s",
                               (updated, 'ai' if opening else 'template', utcnow(), item['id'], item['message'])).rowcount
    return fixed


def build_batch(day=None, limit=None, use_ai=True):
    """Fill today's list up to the daily target. Idempotent per day; safe to call repeatedly."""
    init()
    repair_openings(use_ai)
    day = day or today()
    with db() as c:
        if not c.execute('SELECT pg_try_advisory_xact_lock(73002031) ok').fetchone()['ok']:
            return {'skipped': 'already_running'}
        have = c.execute('SELECT COUNT(*) n FROM daily_prospects WHERE batch_date=%s', (day,)).fetchone()['n']
    need = max(0, (limit or daily_target()) - have)
    added = ai = 0
    for row, info in candidates()[:need]:
        message, source = compose(row['company_name'], info, use_ai)
        now = utcnow()
        with db() as c:
            inserted = c.execute('''INSERT INTO daily_prospects(source_key,company_name,phone,email,city,activity,website,
                score,segment,reason,message,message_source,status,batch_date,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s) ON CONFLICT(source_key) DO NOTHING RETURNING id''',
                (row['source_key'], row['company_name'].strip()[:300], info['phone'], info['email'], info['city'],
                 info['label'], row.get('website') or '', info['score'], info['segment'], info['reason'], message,
                 source, day, now, now)).fetchone()
        if inserted:
            added += 1
            ai += source == 'ai'
    return {'batch_date': str(day), 'added': added, 'ai_messages': ai, 'already': have}


def remaining_pool():
    return len(candidates())


# ---------------------------------------------------------------- web

def session(request):
    s = get_session(request.cookies.get('gla_session'))
    if not s:
        return None
    if s.get('role') not in ('admin', 'sales'):
        raise HTTPException(403, 'قائمة المرشحين متاحة للإدارة والمبيعات')
    return s


async def form(request):
    s = session(request)
    if not s:
        raise HTTPException(401)
    data = parse_qs((await request.body()).decode())
    if (data.get('csrf') or [''])[0] != s['csrf']:
        raise HTTPException(403)
    return s, data


STYLE = '''<style>body{font-family:Arial,sans-serif;background:#07131f;color:#eef6fb;margin:0}*{box-sizing:border-box}
.w{max-width:1200px;margin:auto;padding:20px}.nav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.nav a,.btn{display:inline-block;padding:9px 14px;border-radius:10px;background:#18384d;color:#fff;text-decoration:none;border:0;font-weight:700;cursor:pointer;font-size:14px}
.btn.go{background:#22c55e;color:#04130a}.btn.wa{background:#25d366;color:#04130a}.btn.no{background:#3b2430;color:#fecaca}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}
.kpi{background:#102536;border:1px solid #28475d;border-radius:14px;padding:14px}.kpi b{display:block;font-size:26px;margin-top:4px}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.tab{padding:8px 14px;border-radius:999px;background:#0b1d2b;border:1px solid #28475d;color:#eef6fb;text-decoration:none}
.tab.on{background:#eab308;color:#111;border-color:#eab308}
.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:16px;margin:12px 0}
.head{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:flex-start}
.score{background:#eab308;color:#111;border-radius:999px;padding:4px 12px;font-weight:700}
.muted{color:#9fb4c4;font-size:14px}.ltr{direction:ltr;unicode-bidi:embed}
textarea{width:100%;min-height:150px;padding:10px;border-radius:10px;border:1px solid #36586e;background:#081925;color:#fff;font:inherit;line-height:1.7}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.pill{font-size:12px;padding:3px 10px;border-radius:999px;background:#18384d}
.ai{background:#4c1d95}</style>'''


def page(title, body):
    return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" '
                        'content="width=device-width,initial-scale=1"><title>' + esc(title) + '</title>' + STYLE +
                        '<body><div class="w">' + body + '</div></body></html>')


def wa_link(phone, message):
    return 'https://wa.me/' + phone.lstrip('+') + '?text=' + quote(message)


@router.get('/daily-prospects', response_class=HTMLResponse)
def home(request: Request, status: str = 'pending', day: str = ''):
    s = session(request)
    if not s:
        return RedirectResponse('/login', 303)
    init()
    if status not in STATUSES and status != 'all':
        raise HTTPException(400)
    d = today()
    if day:
        try:
            d = datetime.strptime(day, '%Y-%m-%d').date()
        except ValueError:
            raise HTTPException(400)
    counts = {r['status']: r['n'] for r in rows('SELECT status,COUNT(*) n FROM daily_prospects WHERE batch_date=? GROUP BY status', (d,))}
    total = {r['status']: r['n'] for r in rows('SELECT status,COUNT(*) n FROM daily_prospects GROUP BY status')}
    where, args = 'batch_date=?', [d]
    if status != 'all':
        where += ' AND status=?'
        args.append(status)
    items = rows('SELECT * FROM daily_prospects WHERE ' + where + ' ORDER BY score DESC,id', tuple(args))
    csrf = esc(s['csrf'])
    kpis = ''.join('<div class="kpi">' + label + '<b>' + str(value) + '</b></div>' for label, value in (
        ('مرشحو اليوم', sum(counts.values())), ('بانتظار المراجعة', counts.get('pending', 0)),
        ('معتمد للتواصل', counts.get('approved', 0)), ('تم التواصل (الإجمالي)', sum(total.get(k, 0) for k in ('contacted', 'interested', 'not_interested', 'no_answer'))),
        ('مهتمون (الإجمالي)', total.get('interested', 0))))
    tabs = ''.join('<a class="tab' + (' on' if key == status else '') + '" href="/daily-prospects?' +
                   esc(urlencode({'status': key, 'day': str(d)})) + '">' + esc(label) + ' ' + str(counts.get(key, sum(counts.values()) if key == 'all' else 0)) + '</a>'
                   for key, label in list(STATUSES.items()) + [('all', 'الكل')])
    cards = ''
    for x in items:
        contact = ('<span class="ltr">' + esc(x['phone']) + '</span>' if x['phone'] else '') + \
                  (' · <span class="ltr">' + esc(x['email']) + '</span>' if x['email'] else '')
        actions = ''
        if x['status'] == 'pending':
            actions = ('<label class="pill"><input type="checkbox" name="ids" value="' + str(x['id']) + '" form="bulk" style="width:auto"> تحديد</label>'
                       '<button class="btn go" name="action" value="approve">اعتماد للتواصل</button>'
                       '<button class="btn no" name="action" value="reject">استبعاد</button>'
                       '<button class="btn" name="action" value="save">حفظ تعديل الرسالة</button>')
        elif x['status'] == 'approved':
            if x['phone']:
                actions += '<a class="btn wa" target="_blank" rel="noopener" href="' + esc(wa_link(x['phone'], x['message'])) + '">فتح واتساب بالرسالة</a>'
            actions += ('<button class="btn go" name="action" value="contacted">تم التواصل</button>'
                        '<button class="btn" name="action" value="no_answer">لم يرد</button>')
        if x['status'] in ('approved', 'contacted', 'no_answer'):
            actions += ('<button class="btn go" name="action" value="interested">مهتم</button>'
                        '<button class="btn no" name="action" value="not_interested">غير مهتم</button>')
        editable = x['status'] == 'pending'
        cards += ('<div class="card"><form method="post" action="/daily-prospects/' + str(x['id']) + '">'
                  '<input type="hidden" name="csrf" value="' + csrf + '"><div class="head"><div><h3 style="margin:0 0 6px">' +
                  esc(x['company_name']) + '</h3><div class="muted">' + esc(x['reason']) + '</div><div class="muted">' + contact +
                  '</div></div><div><span class="score">' + str(x['score']) + '</span> <span class="pill">' + esc(STATUSES.get(x['status'])) +
                  '</span> <span class="pill' + (' ai' if x['message_source'] == 'ai' else '') + '">' +
                  ('صياغة بالذكاء الاصطناعي' if x['message_source'] == 'ai' else 'قالب') + '</span></div></div>'
                  '<textarea name="message"' + ('' if editable else ' readonly') + '>' + esc(x['message']) + '</textarea>'
                  + ('<p class="muted">' + esc(x['outcome_note']) + '</p>' if x['outcome_note'] else '') +
                  '<div class="row">' + actions + '</div></form></div>')
    if not cards:
        cards = '<div class="card muted">لا يوجد مرشحون في هذا التبويب.</div>'
    bulk = ('<form id="bulk" method="post" action="/daily-prospects/bulk"><input type="hidden" name="csrf" value="' + csrf + '">'
            '<div class="row"><button class="btn go" name="action" value="approve">اعتماد المحدد</button>'
            '<button class="btn no" name="action" value="reject">استبعاد المحدد</button></div></form>') if status == 'pending' and items else ''
    build = ('<form method="post" action="/daily-prospects/build" style="display:inline"><input type="hidden" name="csrf" value="' + csrf + '">'
             '<button class="btn go">تجهيز دفعة اليوم</button></form>')
    body = ('<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/opportunities">الفرص</a><a href="/accounts">العملاء</a>'
            '<a href="/outbound">العروض والرسائل</a><a href="/customer-campaigns">حملات العملاء</a></div>'
            '<div class="head"><div><h1 style="margin:0">مرشحو اليوم</h1><p class="muted">قائمة يومية مرتبة من قاعدة العملاء المسجلين ('
            + esc(str(d)) + '). لا يُرسل شيء تلقائيًا: الاعتماد يحول الجهة إلى فرصة ومهمة اتصال، والتواصل يتم من واتساب الفريق أو بعد موافقة الإرسال.</p></div>'
            + build + '</div><div class="kpis">' + kpis + '</div><div class="tabs">' + tabs + '</div>' + bulk + cards)
    return page('مرشحو اليوم', body)


def approve(c, item, user_id, now):
    if item['opportunity_id']:
        return item['opportunity_id']
    kind, raw_id = item['source_key'].split(':', 1)
    account_id = int(raw_id) if kind == 'account' else None
    oid = c.execute('''INSERT INTO opportunities(account_id,company_name,source_url,signal,score,stage,estimated_value,currency,owner,created_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,'qualified',0,'SAR',%s,%s,%s) RETURNING id''',
        (account_id, item['company_name'], 'internal://customer/' + ('account' if kind == 'account' else 'directory') + '/' + raw_id,
         item['reason'], item['score'], OWNER, now, now)).fetchone()['id']
    c.execute('''INSERT INTO opportunity_intelligence(opportunity_id,priority,intent,services,evidence,next_action,proposal_draft,follow_up_status,generated_at,updated_at)
        VALUES(%s,%s,'Medium',%s,%s,%s,%s,'draft',%s,%s) ON CONFLICT(opportunity_id) DO NOTHING''',
        (oid, 'P1' if item['score'] >= 80 else 'P2', item['activity'], item['reason'],
         'تواصل تعريفي عبر واتساب' if item['phone'] else 'إرسال بريد تعريفي بعد الموافقة', item['message'], now, now))
    c.execute('''INSERT INTO sales_followups(opportunity_id,kind,due_at,status,notes,created_by,created_at)
        VALUES(%s,'call',%s,'open',%s,%s,%s)''', (oid, now, 'تواصل تعريفي: ' + (item['phone'] or item['email']), user_id, now))
    if item['email']:
        c.execute('''INSERT INTO outbound_messages(opportunity_id,channel,recipient,subject,body,proposal_text,status,provider,created_by,created_at,updated_at)
            VALUES(%s,'email',%s,%s,%s,%s,'draft','pending_channel',%s,%s,%s)''',
            (oid, item['email'], 'آفاق طويق — خدمات التخليص الجمركي والنقل بميناء جدة', item['message'], item['message'], user_id, now, now))
    return oid


def decide(ids, action, user_id, message=None, note=None):
    transitions = {
        'approve': ({'pending'}, 'approved'), 'reject': ({'pending'}, 'rejected'), 'save': ({'pending'}, 'pending'),
        'contacted': ({'approved'}, 'contacted'), 'no_answer': ({'approved', 'contacted'}, 'no_answer'),
        'interested': ({'approved', 'contacted', 'no_answer'}, 'interested'),
        'not_interested': ({'approved', 'contacted', 'no_answer'}, 'not_interested'),
    }
    if action not in transitions:
        raise HTTPException(400)
    allowed, target = transitions[action]
    changed = 0
    now = utcnow()
    for pid in ids:
        with db() as c:
            item = c.execute('SELECT * FROM daily_prospects WHERE id=%s FOR UPDATE', (pid,)).fetchone()
            if not item or item['status'] not in allowed:
                continue
            if message is not None and item['status'] == 'pending':
                text = message.replace('\r\n', '\n').strip()[:2000]
                if len(text) < 20:
                    raise HTTPException(400, 'الرسالة قصيرة جدًا')
                c.execute('UPDATE daily_prospects SET message=%s WHERE id=%s', (text, pid))
                item = dict(item, message=text)
            oid = approve(c, item, user_id, now) if target == 'approved' else item['opportunity_id']
            if oid and target in ('interested', 'not_interested'):
                c.execute("UPDATE opportunities SET stage=%s,updated_at=%s WHERE id=%s",
                          ('proposal' if target == 'interested' else 'lost', now, oid))
            if oid and target in ('contacted', 'interested', 'not_interested', 'no_answer'):
                c.execute("UPDATE sales_followups SET status='done',completed_at=%s WHERE opportunity_id=%s AND kind='call' AND status='open'", (now, oid))
                if target == 'no_answer':
                    c.execute('''INSERT INTO sales_followups(opportunity_id,kind,due_at,status,notes,created_by,created_at)
                        VALUES(%s,'call',%s,'open','إعادة محاولة التواصل',%s,%s)''', (oid, now + timedelta(days=2), user_id, now))
            c.execute('''UPDATE daily_prospects SET status=%s,opportunity_id=%s,decided_by=%s,decided_at=%s,updated_at=%s,
                outcome_note=COALESCE(%s,outcome_note) WHERE id=%s''', (target, oid, user_id, now, now, note, pid))
            changed += 1
    if changed and action != 'save':
        log(user_id, 'daily_prospects_' + action, 'daily_prospect', ids[0] if len(ids) == 1 else None, f'{changed} مرشح: {STATUSES[target]}')
    return changed


@router.post('/daily-prospects/build')
async def build_now(request: Request):
    s, _ = await form(request)
    result = build_batch()
    log(s['user_id'], 'daily_prospects_build', 'daily_prospect', None, json.dumps(result, ensure_ascii=False))
    return RedirectResponse('/daily-prospects', 303)


@router.post('/daily-prospects/bulk')
async def bulk(request: Request):
    s, data = await form(request)
    ids = [int(x) for x in data.get('ids', []) if x.isdigit()][:200]
    action = (data.get('action') or [''])[0]
    if action not in ('approve', 'reject'):
        raise HTTPException(400)
    decide(ids, action, s['user_id'])
    return RedirectResponse('/daily-prospects', 303)


@router.post('/daily-prospects/{pid}')
async def single(pid: int, request: Request):
    s, data = await form(request)
    action = (data.get('action') or [''])[0]
    message = (data.get('message') or [None])[0]
    decide([pid], action, s['user_id'], message=message)
    item = one('SELECT status,batch_date FROM daily_prospects WHERE id=?', (pid,))
    tab = 'pending' if action in ('save', 'approve', 'reject') else (item['status'] if item else 'all')
    return RedirectResponse('/daily-prospects?' + urlencode({'status': tab, 'day': str(item['batch_date']) if item else ''}), 303)


@router.get('/api/v7/daily-prospects/summary')
def summary(request: Request):
    if not session(request):
        raise HTTPException(401)
    init()
    d = today()
    return {'date': str(d), 'today': {r['status']: r['n'] for r in rows('SELECT status,COUNT(*) n FROM daily_prospects WHERE batch_date=? GROUP BY status', (d,))},
            'all_time': {r['status']: r['n'] for r in rows('SELECT status,COUNT(*) n FROM daily_prospects GROUP BY status')},
            'remaining_pool': remaining_pool()}
