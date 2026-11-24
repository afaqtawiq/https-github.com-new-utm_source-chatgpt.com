"""Owner request (21 Nov 2026): «موظفة التسويق والمبيعات لا تقوم بأي مهمة… أبغاها تستخدم الطرق المجانية للمحتوى والنشر،
وترسل لشركات الشحن والنقل وتستقطب عملاء — قسم تسويق ومبيعات فل».

Reem (sales & marketing) now owns the whole funnel:
- find_leads: researches PUBLIC business listings (company sites, chambers, directories) with web search for a segment
  (freight forwarders / shipping agents, transport companies, importers, China forwarders) and adds new companies with
  their public business phone/email to the customer directory — the existing daily list + outreach (approved WhatsApp
  template, 20/day cap, suppressions, one contact per company) then contacts them. Runs once a day by itself.
- marketing_report: one picture of the funnel — posts published per platform, outreach sent, replies, interested,
  new leads found.
- morning: the report goes to the owner every day at 08:30.
Nothing new is sent from here; contact goes through the existing approved, capped pipeline.
"""
import asyncio
import datetime as dt
import json
import os
import re

import httpx

from app.storage import db, utcnow

RIYADH = dt.timezone(dt.timedelta(hours=3))
SEGMENTS = {
    'forwarder': ('شركات الشحن الدولي ووكلاء الشحن (فريت فورودر)', 'freight forwarders and international shipping/logistics companies operating in Saudi Arabia (Jeddah, Riyadh, Dammam)'),
    'transport': ('شركات النقل البري والشاحنات', 'land transport and trucking companies in Saudi Arabia (Jeddah, Riyadh, Dammam)'),
    'importer': ('مستوردون (تجارة جملة ومواد بناء وسيراميك وأغذية)', 'importers and wholesale trading companies in Saudi Arabia that import containers (ceramics, building materials, food, furniture, electronics)'),
    'china': ('وكلاء شحن وموردون في الصين يشحنون للسعودية', 'freight forwarders and sourcing agents in China that ship to Saudi Arabia / GCC'),
    'uae': ('شركات الشحن البري الإماراتية (منفذ البطحاء)', 'UAE land freight / trucking / cargo companies (Dubai, Sharjah, Ajman, Abu Dhabi, Ras Al Khaimah) that truck goods to Saudi Arabia through the Al Batha (Ghuwaifat) border'),
    'gcc': ('شركات خليجية تصدّر أو تعبر إلى السعودية', 'GCC (Kuwait, Bahrain, Oman, Qatar — not UAE) trading and logistics companies that export to or transit through Saudi Arabia'),
}
ROTATION = ('uae', 'china', 'forwarder', 'transport', 'uae', 'china', 'importer')
DAILY_LEADS = int(os.getenv('LEADS_PER_DAY', '15'))
PROMPT = """Find {count} real, currently operating companies: {target}{area}.
Use web search on public sources only (company websites, chamber of commerce / Maroof / Google business listings,
public directories). For each company return its PUBLIC business contact as shown on its own site or listing.
Exclude: Afaq Tuwaiq itself, government entities, individuals, and anything already in this list: {exclude}.
Return ONE JSON array only:
[{{"company": "...", "city": "...", "activity": "short Arabic description", "phone": "+966... or ''", "email": "... or ''",
   "website": "... or ''", "source": "url where the contact appears"}}]
Only include a company if at least a phone or an email was found on a public page{email_rule}. Never invent contacts.
Always give the company's own website when it has one: every contact is checked on that site before it is used.
Keep each field short. Output the JSON array ONLY, with no text before or after it."""


def _digits(phone):
    d = re.sub(r'\D', '', str(phone or ''))
    if d.startswith('00'):
        d = d[2:]
    if d.startswith('05') and len(d) == 10:
        d = '966' + d[1:]
    return d if 9 <= len(d) <= 15 else ''


async def _research(segment, area, count, exclude):
    key = os.getenv('ANTHROPIC_API_KEY', '')
    if not key:
        raise ValueError('البحث غير مفعّل على الخادم')
    target = SEGMENTS[segment][1]
    prompt = PROMPT.format(count=count, target=target, area=(' — focus on ' + area) if area else '',
                           email_rule=' — for companies in China an EMAIL address is required (they are contacted by email)' if segment == 'china' else '',
                           exclude=', '.join(exclude[:60]) or 'none')
    model = os.getenv('LEADS_MODEL') or os.getenv('TRACKING_RESEARCH_MODEL') or os.getenv('LOAD_VISION_MODEL', 'claude-sonnet-5')
    tools = [{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 8}]
    messages = [{'role': 'user', 'content': prompt}]
    text = ''
    async with httpx.AsyncClient(timeout=240) as client:
        for _ in range(5):
            r = await client.post('https://api.anthropic.com/v1/messages',
                                  headers={'x-api-key': key, 'anthropic-version': '2023-06-01'},
                                  json={'model': model, 'max_tokens': 8000, 'tools': tools, 'messages': messages})
            r.raise_for_status()
            data = r.json()
            text = ''.join(b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text')
            if data.get('stop_reason') != 'pause_turn':
                break
            messages = [messages[0], {'role': 'assistant', 'content': data.get('content', [])}]
    items = parse_items(text)
    if not items and text.strip():
        # Owner, 24 Nov 2026: two UAE searches returned 0 because the answer was not clean JSON. Ask once to reformat.
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post('https://api.anthropic.com/v1/messages',
                                  headers={'x-api-key': key, 'anthropic-version': '2023-06-01'},
                                  json={'model': model, 'max_tokens': 6000, 'messages': [
                                      {'role': 'user', 'content': 'Convert these research notes into the JSON array described (company, city, '
                                       'activity, phone, email, website, source). JSON only, no other text. Never add a contact that is not in '
                                       'the notes.\n\n' + text[:20000]}]})
            if r.status_code == 200:
                items = parse_items(''.join(b.get('text', '') for b in r.json().get('content', []) if b.get('type') == 'text'))
    print('LEAD_FINDER_RESEARCH', segment, 'candidates', len(items), 'chars', len(text or ''), flush=True)
    return items


def parse_items(text):
    """The JSON array of companies, tolerant of text, code fences or citations around it."""
    text = str(text or '')
    for m in sorted(re.finditer(r'\[\s*\{.*?\}\s*\]', text, re.S), key=lambda m: -len(m.group(0))):
        try:
            items = json.loads(m.group(0))
        except ValueError:
            continue
        good = [i for i in items if isinstance(i, dict) and str(i.get('company') or '').strip()]
        if good:
            return good
    return []


PHONE_RE = re.compile(r'(?:\+|00)\s?(?:9[67]\d|86|20)[\s().-]*\d(?:[\s().-]*\d){6,11}')
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
CONTACT_PATHS = ('', '/contact', '/contact-us', '/contact-us/', '/contact/', '/en/contact', '/about')


def _site(url):
    url = str(url or '').strip()
    if not url:
        return ''
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    m = re.match(r'(https?://[^/?#]+)', url)
    return m.group(1) if m else ''


async def verify(items):
    """Owner, 24 Nov 2026 («المهارات دي ليش ما متوفرة عند قسم المبيعات»): open each company's OWN website and keep only
    the phone/email actually printed there, with the page as the source. A model's contact that the site does not show
    is dropped; a company whose site shows none keeps nothing and is skipped by store()."""
    sem = asyncio.Semaphore(6)

    async def one(it):
        site = _site(it.get('website'))
        if not site:
            it['verified'] = False
            return it
        async with sem, httpx.AsyncClient(timeout=12, follow_redirects=True,
                                          headers={'User-Agent': 'Mozilla/5.0 (AfaqTuwaiq lead check)'}) as client:
            phones, emails, page = [], [], ''
            for path in CONTACT_PATHS:
                try:
                    r = await client.get(site + path)
                except (httpx.HTTPError, ValueError):
                    continue
                if r.status_code != 200 or 'html' not in r.headers.get('content-type', ''):
                    continue
                html = r.text[:600000]
                found_e = [e for e in EMAIL_RE.findall(html) if not re.search(r'\.(png|jpe?g|webp|svg|gif)$|sentry|example\.|wixpress', e, re.I)]
                found_p = [_digits(p) for p in PHONE_RE.findall(html)]
                found_p = [p for p in found_p if p]
                if found_e or found_p:
                    emails += found_e
                    phones += found_p
                    page = page or str(r.url)
                if emails and phones:
                    break
        model_phone, model_email = _digits(it.get('phone')), str(it.get('email') or '').strip().lower()
        it['phone'] = model_phone if model_phone and model_phone in phones else (phones[0] if phones else '')
        it['email'] = model_email if model_email and model_email in [e.lower() for e in emails] else (emails[0].lower() if emails else '')
        it['verified'] = bool(it['phone'] or it['email'])
        if page:
            it['source'] = page
        return it

    return list(await asyncio.gather(*(one(dict(i)) for i in items)))


def store(segment, items):
    """Add new companies to customer_directory (source lead_finder:<segment>). Returns (added, skipped)."""
    added, skipped = [], 0
    now = utcnow()
    with db() as c:
        for it in items:
            phone = _digits(it.get('phone'))
            email = str(it.get('email') or '').strip().lower()[:120]
            if email and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[a-z]{2,}', email):
                email = ''
            if not phone and not email:
                skipped += 1
                continue
            name = ' '.join(str(it['company']).split())[:200]
            dup = c.execute('''SELECT 1 FROM customer_directory WHERE (phone<>'' AND phone=%s) OR (email<>'' AND lower(email)=%s)
                OR lower(company_name)=lower(%s) LIMIT 1''', (phone or '-', email or '-', name)).fetchone()
            if dup:
                skipped += 1
                continue
            notes = ('مصدر: ' + str(it.get('source') or '')[:200] + (' — موقع: ' + str(it.get('website'))[:120] if it.get('website') else ''))
            c.execute('''INSERT INTO customer_directory(company_name,phone,email,city,activity,source,contact_consent,notes,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,0,%s,%s,%s)''',
                      (name, phone or None, email or None, str(it.get('city') or '')[:60],
                       (SEGMENTS[segment][0] + ' — ' + str(it.get('activity') or ''))[:200], 'lead_finder:' + segment, notes, now, now))
            added.append(name + (' — +' + phone if phone else '') + (' — ' + email if email else '')
                         + (' — ' + str(it.get('source'))[:120] if it.get('source') else ''))
    return added, skipped


def find_leads(segment='forwarder', area='', count=DAILY_LEADS):
    segment = segment if segment in SEGMENTS else 'forwarder'
    count = max(3, min(int(count or DAILY_LEADS), 25))
    with db() as c:
        exclude = [r['company_name'] for r in c.execute(
            "SELECT company_name FROM customer_directory WHERE source LIKE 'lead_finder:%%' ORDER BY id DESC LIMIT 60").fetchall()]
    from app.transport_desk import run_async
    items = run_async(lambda: _research(segment, str(area or '')[:60], count, exclude), timeout=290)
    try:
        items = run_async(lambda: verify(items), timeout=200)
    except Exception as exc:
        print('LEAD_FINDER_VERIFY', type(exc).__name__, str(exc)[:120], flush=True)
        for it in items:
            it['verified'] = False
    if segment == 'uae':  # UAE carriers are the target; Saudi clearance offices (+966) are competitors, not leads
        items = [i for i in items if not _digits(i.get('phone')).startswith('966') and not re.search(r'\.sa(/|$)', str(i.get('website') or ''))]
    items = [i for i in items if i.get('verified')]
    added, skipped = store(segment, items)
    print('LEAD_FINDER', segment, 'found', len(items), 'added', len(added), flush=True)
    if not added:
        return f'بحثت عن {SEGMENTS[segment][0]} ولم أجد شركات جديدة بأرقام أو إيميلات منشورة (مكرر/بلا تواصل: {skipped}).'
    return (f"✅ أضفت {len(added)} شركة جديدة ({SEGMENTS[segment][0]}) إلى دليل العملاء المحتملين، وتدخل قائمة التواصل اليومية "
            f"تلقائيًا (رسالة التعريف المعتمدة، 20 شركة يوميًا). كل رقم وإيميل تأكدت منه من موقع الشركة نفسها:\n"
            + '\n'.join('• ' + n for n in added[:25])
            + (f'\n(تجاهلت {skipped} مكررة أو بلا تواصل منشور)' if skipped else ''))


def _q(c, sql, args=()):
    try:
        return c.execute(sql, args).fetchone()
    except Exception:
        c.execute('ROLLBACK')
        return None


def report(days=1):
    days = max(1, min(int(days or 1), 30))
    since = utcnow() - dt.timedelta(days=days)
    since_day = (dt.datetime.now(RIYADH) - dt.timedelta(days=days - 1)).date()
    lines = [f"📈 ريم — تقرير التسويق والمبيعات ({'اليوم' if days == 1 else f'آخر {days} يوم'})"]
    with db() as c:
        posts = []
        for table, label in (('afaq_daily_posters', 'عربي'), ('afaq_daily_posters_en', 'إنجليزي')):
            row = _q(c, f'SELECT COUNT(*) n, MAX(results_json) r FROM {table} WHERE day >= %s', (since_day,))
            if row and row['n']:
                try:
                    res = json.loads(row['r'] or '{}')
                except ValueError:
                    res = {}
                ok = [k for k, v in res.items() if v == 'published']
                posts.append(f"{row['n']} بوستر {label}" + (f" (نُشر على: {'، '.join(ok)})" if ok else ''))
        lines.append('🖼️ المحتوى: ' + ('؛ '.join(posts) if posts else 'لا منشورات مسجلة'))
        sent = _q(c, "SELECT COUNT(*) n FROM daily_prospects WHERE updated_at >= %s AND status IN ('contacted','no_answer','interested','not_interested')", (since,))
        interested = _q(c, "SELECT COUNT(*) n FROM daily_prospects WHERE updated_at >= %s AND status='interested'", (since,))
        replies = _q(c, "SELECT COUNT(*) n FROM prospect_replies WHERE created_at >= %s AND body<>''", (since,))
        leads = _q(c, "SELECT COUNT(*) n FROM customer_directory WHERE created_at >= %s AND source LIKE 'lead_finder:%%'", (since,))
        pool = _q(c, "SELECT COUNT(*) n FROM customer_directory WHERE source LIKE 'lead_finder:%%'")
    lines.append(f"📤 التواصل: {(sent or {}).get('n', 0)} شركة تم التواصل معها — ردود {(replies or {}).get('n', 0)} — مهتم {(interested or {}).get('n', 0)}")
    lines.append(f"🔎 عملاء جدد من البحث: {(leads or {}).get('n', 0)} (إجمالي ما أضافه البحث: {(pool or {}).get('n', 0)})")
    lines.append('للتفاصيل: «مين رد من العملاء المحتملين» — ولإضافة عملاء: «ريم ابحثي عن شركات نقل في الدمام».')
    return '\n'.join(lines)


def register_worker(app):
    async def loop():
        from starlette.concurrency import run_in_threadpool
        from app.owner_briefing import deliver
        await asyncio.sleep(200)
        leads_day = report_day = None
        while True:
            try:
                now = dt.datetime.now(RIYADH)
                if os.getenv('LEAD_FINDER', '1') == '1' and now.hour == 7 and leads_day != now.date():
                    leads_day = now.date()
                    segment = ROTATION[now.toordinal() % len(ROTATION)]
                    await run_in_threadpool(find_leads, segment, '', DAILY_LEADS)
                if now.hour == 8 and now.minute >= 30 and report_day != now.date():
                    report_day = now.date()
                    await deliver(await run_in_threadpool(report, 1))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('MARKETING_DESK', type(exc).__name__, str(exc)[:160], flush=True)
            await asyncio.sleep(300)

    @app.on_event('startup')
    async def start():
        app.state.marketing_desk_worker = asyncio.create_task(loop())
