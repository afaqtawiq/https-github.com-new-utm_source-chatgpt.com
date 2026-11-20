"""Isolated staging app for the group request inbox (owner: «اختبر على نسخة تجريبية، ولا تنشر على الإنتاج قبل اعتمادي»).

Runs ONLY the group request worker against its own empty database: it reads the WhatsApp group conversations through
the provider (read-only polling — webhooks stay on production) and alerts the backup. No other platform worker,
no customer messaging, no outreach, no posting. Start: uvicorn app.staging_requests:app

Page: /staging/requests?token=<STAGING_VIEW_TOKEN>
"""
import hmac
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app import group_requests

app = FastAPI(title='Afaq group requests — staging')


@app.on_event('startup')
def seed_alert_test():
    """STAGING_TEST_REQUEST=<label>: one clearly-labelled test request, 16 minutes old, so the real alert chain runs
    (WhatsApp to the backup → delivery receipt → e-mail fallback). Created once per label; nothing goes to any group."""
    import datetime as dt
    import json
    label = os.getenv('STAGING_TEST_REQUEST', '').strip()[:40]
    if not label:
        return
    from app.storage import db, utcnow
    group_requests.init()
    name = 'اختبار التنبيه — ' + label
    now = utcnow()
    with db() as c:
        if c.execute('SELECT 1 FROM group_requests WHERE group_name=%s', (name,)).fetchone():
            return
        rid = c.execute('''INSERT INTO group_requests(account_id,conversation_id,group_name,sender,sender_name,text,files,topic,
            owner_key,received_at,last_message_at,last_action,last_action_at,created_at)
            VALUES('staging','staging-test',%s,'','نسخة الاختبار',%s,%s,'clearance','clearance',%s,%s,%s,%s,%s) RETURNING id''',
                        (name, 'طلب اختبار (ليس من عميل): فحص البند والموافقات لمنتج تجريبي. هذا تنبيه تجريبي من نسخة الاختبار.',
                         json.dumps(['ملف اختبار 1.pdf', 'ملف اختبار 2.pdf'], ensure_ascii=False), now - dt.timedelta(minutes=16),
                         now - dt.timedelta(minutes=16), 'طلب اختبار أُنشئ في نسخة الاختبار', now, now)).fetchone()['id']
    print('STAGING_TEST_REQUEST_CREATED', rid, label, flush=True)


group_requests.register_worker(app)


def _token(request):
    expected = os.getenv('STAGING_VIEW_TOKEN', '')
    got = request.query_params.get('token', '')
    if len(expected) < 24 or not hmac.compare_digest(got, expected):
        raise HTTPException(404)
    return got


@app.get('/health')
def health():
    h = group_requests.health()
    return JSONResponse({'ok': True, 'intake_last_ok': h['last_ok'].isoformat() if h['last_ok'] else None,
                         'intake_stale': h['stale'], 'enabled': group_requests.enabled()})


@app.get('/staging/requests', response_class=HTMLResponse)
def page(request: Request):
    token = _token(request)
    return HTMLResponse(group_requests.page_html(group_requests.cards(), group_requests.health(),
                                                 lambda rid, act: f'/staging/requests/{rid}/{act}?token={token}'))


@app.post('/staging/requests/{rid}/{action}')
def act(rid: int, action: str, request: Request):
    token = _token(request)
    if action == 'ack':
        group_requests.acknowledge(rid, 'محمد (صفحة التجربة)')
    elif action == 'close':
        group_requests.close(rid, 'محمد (صفحة التجربة)')
    else:
        raise HTTPException(404)
    return RedirectResponse(f'/staging/requests?token={token}', 303)
