"""Operator-verified tracking evidence -> the existing Afaaq WhatsApp request.

No carrier website scraping. Uploads prepare a draft; only a reviewed draft sends.
"""
import datetime as dt
import hashlib
import html
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from app.storage import db, get_session

router = APIRouter()
STATES = {'departed': 'غادرت السفينة', 'transit': 'الشحنة في الطريق',
          'planned': 'وصول السفينة مخطط', 'arrived': 'وصلت السفينة',
          'discharged': 'تم تفريغ الحاوية', 'unknown': 'الحالة غير مؤكدة'}
DELIVERY = {'draft': 'جاهز للمراجعة', 'sending': 'بدأ الإرسال؛ لا تعِد الإرسال قبل التحقق',
            'accepted': 'قبل مزود واتساب الرسالة؛ هذا لا يؤكد قراءتها أو تسليمها',
            'rejected': 'رفض مزود واتساب الرسالة؛ تحقق من نافذة المحادثة وإعدادات الربط',
            'uncertain': 'لم يتأكد الإرسال؛ راجع محادثة واتساب قبل أي محاولة أخرى'}
MAX_FILE = 10 * 1024 * 1024


def ensure_tables():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS afaaq_tracking_updates(
            id BIGSERIAL PRIMARY KEY, request_id BIGINT NOT NULL REFERENCES zernio_requests(id),
            file_hash TEXT NOT NULL, media_type TEXT NOT NULL, content BYTEA NOT NULL,
            evidence TEXT NOT NULL, containers JSONB NOT NULL, details JSONB NOT NULL,
            state TEXT NOT NULL DEFAULT 'draft', message TEXT, provider_code INTEGER,
            created_by BIGINT NOT NULL, confirmed_by BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), confirmed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(request_id,file_hash))''')


def admin(request, csrf=None):
    current = get_session(request.cookies.get('gla_session'))
    if not current:
        raise HTTPException(401, 'سجّل الدخول إلى البرنامج أولًا')
    if current.get('role') != 'admin' or (csrf is not None and csrf != current.get('csrf')):
        raise HTTPException(403, 'غير مصرح')
    return current


def request_row(c, request_id):
    row = c.execute("SELECT * FROM zernio_requests WHERE id=%s AND agent='afaaq'", (request_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'طلب آفاق غير موجود')
    return row


def containers(text):
    return sorted(set(re.sub(r'\s+', '', x) for x in re.findall(r'\b[A-Z]{4}\s?\d{7}\b', text.upper())))


def media_type(content):
    if content.startswith(b'%PDF-'): return 'application/pdf', '.pdf'
    if content.startswith(b'\xff\xd8\xff'): return 'image/jpeg', '.jpg'
    if content.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png', '.png'
    if content[:4] == b'RIFF' and content[8:12] == b'WEBP': return 'image/webp', '.webp'
    raise ValueError('ارفع PDF أو صورة JPG أو PNG أو WEBP واضحة')


def extract(content):
    mime, suffix = media_type(content)
    with tempfile.TemporaryDirectory(prefix='tracking-') as folder:
        path = Path(folder) / ('document' + suffix)
        path.write_bytes(content)
        if mime == 'application/pdf':
            result = subprocess.run(['pdftotext', '-f', '1', '-l', '10', '-layout', str(path), '-'],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and containers(result.stdout):
                return result.stdout[:50000]
        from app.shipping_agents import extract_document_text
        return extract_document_text(path, mime)[:50000]


def suggestions(text):
    upper = text.upper()
    result = {'carrier': 'CMA CGM' if 'CMA CGM' in upper else '', 'port': '',
              'eta': '', 'status': 'unknown', 'source_url': ''}
    if result['carrier']:
        result['source_url'] = 'https://www.cma-cgm.com/ebusiness/tracking'
    # Only a labeled planned-arrival event can propose an ETA; never a bill date.
    events = re.findall(r'(\d{1,2}-[A-Z]{3}-\d{4})\s+(\d{1,2}:\d{2}\s*[AP]M)\s+PLANNED VESSEL ARRIVAL', upper)
    if len(events) == 1:
        try:
            result['eta'] = dt.datetime.strptime(' '.join(events[0]), '%d-%b-%Y %I:%M %p').strftime('%Y-%m-%dT%H:%M')
        except ValueError:
            pass
    if 'VESSEL DEPARTURE' in upper:
        result['status'] = 'departed'
    elif events:
        result['status'] = 'planned'
    return result


def validate(details, allowed):
    data = {k: str(details.get(k) or '').strip() for k in
            ('container', 'carrier', 'port', 'eta', 'status', 'source_url')}
    if data['container'] not in allowed:
        raise ValueError('رقم الحاوية لا يطابق البوليصة ونتيجة التتبع')
    if not data['carrier'] or not data['port'] or any(len(data[k]) > 150 for k in ('carrier', 'port')):
        raise ValueError('أدخل شركة الملاحة وميناء الوصول كما يظهران في النتيجة')
    if data['status'] not in STATES:
        raise ValueError('اختر حالة الشحنة')
    if data['eta']:
        try:
            parsed = dt.datetime.strptime(data['eta'], '%Y-%m-%dT%H:%M')
        except ValueError:
            raise ValueError('موعد الوصول غير صالح') from None
        data['eta'] = parsed.strftime('%Y-%m-%dT%H:%M')
    url = urlsplit(data['source_url'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or len(data['source_url']) > 600:
        raise ValueError('أدخل رابط صفحة التتبع الرسمي بصيغة https')
    if any('\n' in data[k] or '\r' in data[k] for k in data):
        raise ValueError('استخدم سطرًا واحدًا لكل حقل')
    return data


def message_for(request_id, data, verified_at):
    eta = data['eta'].replace('T', ' ') if data['eta'] else 'غير متاح في نتيجة التتبع'
    return (f"آفاق طويق — تحديث الشحنة AF-{request_id}\n"
            f"شركة الملاحة: {data['carrier']}\nالحاوية: {data['container']}\n"
            f"ميناء الوصول: {data['port']}\nالحالة: {STATES[data['status']]}\n"
            f"موعد الوصول المتوقع: {eta}" + (' — بالتوقيت المحلي للميناء' if data['eta'] else '') +
            f"\nتمت مراجعة نتيجة التتبع يدويًا بتاريخ {verified_at}.\nالمصدر: {data['source_url']}\n"
            'الموعد المتوقع قابل للتغيير، ولا يعني تأكيد تفريغ الحاوية أو جاهزيتها للاستلام.')


def page(title, body):
    return HTMLResponse('''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width"><title>''' + html.escape(title) + '''</title>
        <style>body{font:17px Tahoma;line-height:1.8;background:#0b2031;color:#fff;max-width:900px;margin:auto;padding:24px}
        a{color:#ffd978}section{padding:20px;border:1px solid #496071;border-radius:14px;margin:18px 0}
        input,select,button{font:inherit;padding:10px;max-width:100%;margin:8px 0}label{display:block}pre{white-space:pre-wrap;overflow-wrap:anywhere}
        button{background:#ffd978;border:0;border-radius:8px;cursor:pointer}</style>
        <a href="/whatsapp-requests?agent=afaaq">طلبات آفاق على واتساب</a><h1>''' + html.escape(title) + '</h1>' + body + '</html>',
        headers={'Cache-Control': 'no-store'})


@router.get('/whatsapp-requests/{request_id}/tracking')
def upload_page(request_id: int, request: Request):
    current = admin(request)
    ensure_tables()
    with db() as c:
        row = request_row(c, request_id)
        updates = c.execute('SELECT id,state,created_at FROM afaaq_tracking_updates WHERE request_id=%s ORDER BY id DESC', (request_id,)).fetchall()
    csrf = html.escape(current['csrf'])
    history = ''.join(f"<p><a href='/tracking-updates/{x['id']}'>نتيجة {x['id']}</a> — {DELIVERY[x['state']]}</p>" for x in updates)
    return page(f'تحديث تتبع الطلب AF-{request_id}',
        f"<p>المحادثة المرتبطة بالطلب: <b dir=ltr>{html.escape(row['conversation_id'])}</b></p>" +
        f'''<section><p>ارفع نتيجة التتبع التي تحققت منها والبوليصة الخاصة بهذا العميل. سنطابق الحاوية ونجهز الرد للمراجعة.</p>
        <form method="post" enctype="multipart/form-data"><input type="hidden" name="csrf" value="{csrf}">
        <label>نتيجة التتبع من موقع شركة الملاحة</label><input type="file" name="tracking" accept="application/pdf,image/jpeg,image/png,image/webp" required>
        <label>بوليصة العميل لمطابقة الحاوية</label><input type="file" name="bill" accept="application/pdf,image/jpeg,image/png,image/webp" required>
        <p>حتى 10 ميجابايت لكل ملف. لا تُرسل الرسالة قبل مراجعتها.</p><button>رفع ومطابقة الحاوية</button></form></section>''' + history)


@router.post('/whatsapp-requests/{request_id}/tracking')
async def upload(request_id: int, request: Request, csrf: str = Form(...),
                 tracking: UploadFile = File(...), bill: UploadFile = File(...)):
    current = admin(request, csrf)
    ensure_tables()
    with db() as c:
        request_row(c, request_id)
    raw, bill_raw = await tracking.read(MAX_FILE + 1), await bill.read(MAX_FILE + 1)
    if not raw or not bill_raw or max(len(raw), len(bill_raw)) > MAX_FILE:
        raise HTTPException(400, 'ارفع الملفين بحجم لا يتجاوز 10 ميجابايت لكل منهما')
    try:
        mime, _ = media_type(raw)
        text = await run_in_threadpool(extract, raw)
        bill_text = await run_in_threadpool(extract, bill_raw)
    except (ValueError, RuntimeError, subprocess.TimeoutExpired):
        raise HTTPException(422, 'تعذرت قراءة الملفات؛ ارفع PDF أصليًا أو صورة أوضح') from None
    matching = sorted(set(containers(text)) & set(containers(bill_text)))
    if not matching:
        raise HTTPException(422, 'لم نجد حاوية مشتركة بين البوليصة ونتيجة التتبع؛ لم تُرسل أي رسالة')
    digest = hashlib.sha256(raw).hexdigest()
    details = suggestions(text)
    details['container'] = matching[0]
    with db() as c:
        request_row(c, request_id)
        row = c.execute('''INSERT INTO afaaq_tracking_updates(request_id,file_hash,media_type,content,evidence,containers,details,created_by)
            VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s) ON CONFLICT(request_id,file_hash) DO NOTHING RETURNING id''',
            (request_id,digest,mime,raw,text,json.dumps(matching),json.dumps(details),current['user_id'])).fetchone()
        if not row:
            row = c.execute('SELECT id FROM afaaq_tracking_updates WHERE request_id=%s AND file_hash=%s', (request_id,digest)).fetchone()
    return RedirectResponse(f"/tracking-updates/{row['id']}", 303)


def update_row(c, update_id):
    row = c.execute('SELECT * FROM afaaq_tracking_updates WHERE id=%s', (update_id,)).fetchone()
    if not row: raise HTTPException(404)
    request_row(c, row['request_id'])
    return row


@router.get('/tracking-updates/{update_id}/source')
def source(update_id: int, request: Request):
    admin(request)
    with db() as c: row = update_row(c, update_id)
    return Response(bytes(row['content']), media_type=row['media_type'],
                    headers={'Cache-Control': 'no-store', 'Content-Disposition': 'inline', 'X-Content-Type-Options': 'nosniff'})


@router.get('/tracking-updates/{update_id}')
def review(update_id: int, request: Request):
    current = admin(request)
    with db() as c:
        row = update_row(c, update_id)
        customer = request_row(c, row['request_id'])
    esc = html.escape
    data = row['details']
    body = f"<p>طلب AF-{row['request_id']} · المحادثة: <b dir=ltr>{esc(customer['conversation_id'])}</b></p>"
    body += f"<p>{DELIVERY[row['state']]}</p><a href='/tracking-updates/{update_id}/source' target='_blank'>فتح نتيجة التتبع الأصلية</a>"
    if row['state'] != 'draft':
        return page('نتيجة إرسال تحديث الشحنة', body + '<pre>' + esc(row['message'] or '') + '</pre>')
    body += f"<section><form method=post action='/tracking-updates/{update_id}/send'><input type=hidden name=csrf value='{esc(current['csrf'])}'>"
    body += '<label>الحاوية المطابقة</label><select name=container>' + ''.join(f"<option>{esc(x)}</option>" for x in row['containers']) + '</select>'
    for key, label, kind in [('carrier','شركة الملاحة','text'), ('port','ميناء الوصول','text'),
                             ('eta','موعد الوصول المتوقع بالتوقيت المحلي للميناء — اتركه فارغًا إن لم يظهر','datetime-local'),
                             ('source_url','رابط صفحة التتبع الرسمي','url')]:
        body += f"<label>{label}</label><input name='{key}' type='{kind}' value='{esc(data.get(key, ''))}' {'required' if key != 'eta' else ''}>"
    body += '<label>حالة الشحنة كما تظهر في التتبع</label><select name=status>' + ''.join(
        f"<option value='{k}' {'selected' if k == data.get('status') else ''}>{v}</option>" for k,v in STATES.items()) + '</select>'
    body += '''<label><input type=checkbox name=verified value=yes required> راجعت نتيجة التتبع ووقت الوصول، والبوليصة تخص عميل هذا الطلب.</label>
        <p>سيُرسل التحديث إلى محادثة العميل المرتبطة بهذا الطلب، مع المصدر وتاريخ المراجعة وتوضيح أن الموعد قابل للتغيير.</p>
        <button>اعتماد النتيجة وإرسالها إلى العميل</button></form></section>'''
    body += '<details><summary>النص المستخرج من نتيجة التتبع</summary><pre>' + esc(row['evidence']) + '</pre></details>'
    return page('مراجعة نتيجة التتبع وإرسالها', body)


@router.post('/tracking-updates/{update_id}/send')
async def send(update_id: int, request: Request):
    form = dict(await request.form())
    current = admin(request, str(form.get('csrf') or ''))
    if form.get('verified') != 'yes': raise HTTPException(400, 'راجع النتيجة والمستلم أولًا')
    if os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') != '1':
        raise HTTPException(403, 'الإرسال الخارجي متوقف في إعدادات البرنامج')
    key = os.getenv('ZERNIO_API_KEY', '')
    if not key: raise HTTPException(503, 'ربط واتساب غير جاهز')
    with db() as c:
        row = update_row(c, update_id)
        customer = request_row(c, row['request_id'])
        try:
            data = validate(form, row['containers'])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        account = (customer['fields'] or {}).get('_whatsapp_account_id') or os.getenv('WHATSAPP_COMMAND_ACCOUNT_ID', '')
        if not account: raise HTTPException(503, 'يحتاج ربط حساب واتساب الخاص بالطلب')
        verified_at = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        message = message_for(row['request_id'], data, verified_at)
        claimed = c.execute('''UPDATE afaaq_tracking_updates SET state='sending', details=%s::jsonb,
            message=%s,confirmed_by=%s,confirmed_at=NOW(),updated_at=NOW()
            WHERE id=%s AND state='draft' RETURNING id''', (json.dumps(data),message,current['user_id'],update_id)).fetchone()
        if not claimed:
            return RedirectResponse(f'/tracking-updates/{update_id}', 303)
    # Claim is committed before networking: concurrent clicks and uncertain sends never retry.
    state, code = 'uncertain', None
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            result = await client.post('https://zernio.com/api/v1/inbox/conversations/' + quote(customer['conversation_id'], safe='') + '/messages',
                headers={'Authorization': 'Bearer ' + key, 'Idempotency-Key': f'afaaq-tracking-{update_id}'},
                json={'accountId': account, 'message': message})
        code = result.status_code
        state = 'accepted' if result.is_success else ('uncertain' if code >= 500 else 'rejected')
    except httpx.HTTPError:
        pass
    with db() as c:
        c.execute('UPDATE afaaq_tracking_updates SET state=%s,provider_code=%s,updated_at=NOW() WHERE id=%s', (state,code,update_id))
        c.execute('''INSERT INTO zernio_request_messages(event_id,request_id,body,reply)
            VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
            (f'afaaq-tracking-{update_id}',row['request_id'],'نتيجة تتبع راجعها المسؤول — ' + DELIVERY[state],message))
    return RedirectResponse(f'/tracking-updates/{update_id}', 303)
