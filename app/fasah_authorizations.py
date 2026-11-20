"""Owner-requested (Nov 2026): «فيصل شيك لي تفويض شركة بروميت متى ينتهي».

The work computer reads the broker authorizations list in FASAH (read-only task «fasah_authorizations»), the
text is split here into rows (importer, number, start, end, status) and kept in fasah_authorizations.
Faisal answers from that table; when it is older than a day he asks the work computer for a fresh read.
Expiring authorizations (≤ 30 days) are reported after every read.
"""
import datetime as dt
import json
import os
import re

from app.storage import db, utcnow

FRESH_HOURS = 24
SOON_DAYS = 30
PROMPT = """Below is the text of the customs-broker AUTHORIZATIONS list read from the Saudi FASAH portal (Arabic).
Extract every authorization row. Answer with a JSON array only:
[{"importer": "company name as written", "number": "authorization number or ''", "start": "YYYY-MM-DD or ''",
  "end": "YYYY-MM-DD or ''", "status": "status as written (e.g. ساري/منتهي/ملغي) or ''"}]
Dates may be dd/mm/yyyy (Gregorian) — convert. If a date is Hijri, convert to Gregorian. Do not invent rows."""
_READY = False


def init():
    global _READY
    if _READY:
        return
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS fasah_authorizations(
            key TEXT PRIMARY KEY, importer TEXT NOT NULL, number TEXT, start_date DATE, end_date DATE, status TEXT,
            task_id BIGINT, updated_at TIMESTAMPTZ NOT NULL)''')
    _READY = True


def _date(value):
    value = str(value or '').strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d'):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


async def parse(text):
    import httpx
    key = os.getenv('ANTHROPIC_API_KEY', '')
    if not key:
        raise ValueError('قراءة التفاويض غير مفعّلة على الخادم')
    body = {'model': os.getenv('LOAD_VISION_MODEL', 'claude-sonnet-5'), 'max_tokens': 6000,
            'messages': [{'role': 'user', 'content': PROMPT + '\n\n---\n' + text[:60000]}]}
    async with httpx.AsyncClient(timeout=150) as client:
        r = await client.post('https://api.anthropic.com/v1/messages', json=body,
                              headers={'x-api-key': key, 'anthropic-version': '2023-06-01'})
        r.raise_for_status()
    out = ''.join(p.get('text', '') for p in r.json().get('content', []) if p.get('type') == 'text')
    m = re.search(r'\[.*\]', out, re.S)
    items = json.loads(m.group(0)) if m else []
    return [i for i in items if isinstance(i, dict) and str(i.get('importer') or '').strip()]


def store(rows, task_id=None):
    init()
    now = utcnow()
    with db() as c:
        for r in rows:
            importer = ' '.join(str(r.get('importer')).split())[:200]
            number = str(r.get('number') or '').strip()[:60]
            key = number or importer
            c.execute('''INSERT INTO fasah_authorizations(key,importer,number,start_date,end_date,status,task_id,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(key) DO UPDATE SET importer=EXCLUDED.importer,number=EXCLUDED.number,
                start_date=EXCLUDED.start_date,end_date=EXCLUDED.end_date,status=EXCLUDED.status,task_id=EXCLUDED.task_id,
                updated_at=EXCLUDED.updated_at''',
                      (key, importer, number, _date(r.get('start')), _date(r.get('end')), str(r.get('status') or '')[:40], task_id, now))
    return len(rows)


def _line(r, today):
    end = r.get('end_date')
    left = (end - today).days if end else None
    when = (f"ينتهي {end.isoformat()}" + (f' (باقي {left} يوم)' if left is not None and left >= 0 else ' (منتهٍ)')) if end else 'تاريخ الانتهاء غير ظاهر'
    flag = '🔴' if left is not None and left < 0 else '🟠' if left is not None and left <= SOON_DAYS else '🟢'
    return f"{flag} {r['importer']}" + (f" — تفويض {r['number']}" if r.get('number') else '') + f' — {when}' + \
        (f" — {r['status']}" if r.get('status') else '')


def expiring_text(today=None):
    init()
    today = today or dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).date()
    with db() as c:
        rows = c.execute('SELECT * FROM fasah_authorizations WHERE end_date IS NOT NULL AND end_date <= %s ORDER BY end_date',
                         (today + dt.timedelta(days=SOON_DAYS),)).fetchall()
    if not rows:
        return ''
    return '🛃 تفاويض فسح المنتهية أو القريبة من الانتهاء (30 يوم):\n' + '\n'.join(_line(r, today) for r in rows)


def after_read(task_id, text, name=''):
    """Called from the runner when the read finished. Returns the owner notice."""
    import asyncio
    rows = asyncio.run(parse(text))
    n = store(rows, task_id)
    out = [f'🛃 قرأت {n} تفويض من فسح.']
    if name:
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).date()
        with db() as c:
            all_rows = c.execute('SELECT * FROM fasah_authorizations ORDER BY end_date NULLS LAST').fetchall()
        hits = [r for r in all_rows if _norm(name) and (_norm(name) in _norm(r['importer']) or _norm(r['importer']) in _norm(name))]
        out += [_line(r, today) for r in hits] or [f'ما لقيت تفويضًا باسم «{name}» في قائمة فسح.']
    soon = expiring_text()
    out.append(soon or 'لا يوجد تفويض ينتهي خلال 30 يوم.')
    return '\n'.join(out)


def _norm(text):
    text = re.sub(r'[إأآ]', 'ا', str(text or ''))
    text = text.replace('ة', 'ه').replace('ى', 'ي')
    return re.sub(r'\s+', ' ', re.sub(r'\b(شركة|شركه|مؤسسة|مؤسسه|ال)', ' ', text)).strip().lower()


def answer(name='', actor=''):
    """Faisal: when does the authorization of <company> end? Uses the stored read; refreshes when stale."""
    init()
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).date()
    with db() as c:
        rows = c.execute('SELECT * FROM fasah_authorizations ORDER BY end_date NULLS LAST').fetchall()
        last = c.execute('SELECT MAX(updated_at) t FROM fasah_authorizations').fetchone()['t']
        busy = c.execute("SELECT id FROM runner_tasks WHERE kind='fasah_authorizations' AND status IN ('queued','running') LIMIT 1").fetchone()
    stale = not last or (dt.datetime.now(dt.timezone.utc) - last).total_seconds() > FRESH_HOURS * 3600
    want = _norm(name)
    hits = [r for r in rows if want and (want in _norm(r['importer']) or _norm(r['importer']) in want)] if want else rows
    out = []
    if hits:
        stamp = last.astimezone(dt.timezone(dt.timedelta(hours=3))).strftime('%Y-%m-%d %H:%M') if last else ''
        out.append(f'آخر قراءة لتفاويض فسح: {stamp}')
        out += [_line(r, today) for r in hits[:25]]
    elif rows and want:
        out.append(f'ما لقيت تفويضًا باسم «{name}» في آخر قراءة لفسح ({len(rows)} تفويض).')
    if stale or (want and not hits):
        if busy:
            out.append(f"⏳ جهاز العمل يقرأ قائمة التفاويض الآن (المهمة #{busy['id']})، وأرسل لك النتيجة أول ما تخلص.")
        else:
            from app import agent_runner
            _, msg = agent_runner.create_task('fasah_authorizations', {'pages': 10, 'name': name[:60]}, actor or 'فيصل')
            out.append(msg + '\nأرسل لك تواريخ الانتهاء أول ما تخلص القراءة.')
    return '\n'.join(out)
