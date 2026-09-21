"""Bounded receipt acknowledgements, never instructions or financial commitments."""
import asyncio
import datetime as dt
import os
import re
from contextlib import suppress
from email.utils import getaddresses, parsedate_to_datetime
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from app.storage import db, one, rows, utcnow
from app import spacemail
from app.social_content import page, e
from app.social_publishing import hidden_csrf
from app.mfa_stepup import recent_stepup

router = APIRouter()
BODY = ('شكرًا لتواصلك مع آفاق طويق. هذه رسالة تأكيد استلام تلقائية.\n\n'
        'لمساعدتنا في دراسة طلبك، يرجى تزويدنا بالخدمة المطلوبة، ونوع البضاعة ووزنها أو حجمها، '
        'ومدينة أو منفذ الانطلاق والوجهة والموعد المطلوب ورقم التواصل، إن لم تذكرها في رسالتك.\n\n'
        'هذا الرد لا يُعد عرض سعر أو تأكيد حجز أو قبولًا لالتزام مالي.\n'
        'آفاق طويق — التخليص الجمركي والنقل والشحن والتخزين وخدمات الباب إلى الباب.')
with db() as c:
    c.execute('ALTER TABLE spacemail_inbox ADD COLUMN IF NOT EXISTS reply_address TEXT')
    c.execute('''CREATE TABLE IF NOT EXISTS official_reply_settings(
        user_id BIGINT PRIMARY KEY, enabled BOOLEAN NOT NULL, enabled_at TIMESTAMPTZ NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS official_reply_log(
        inbox_id BIGINT PRIMARY KEY REFERENCES spacemail_inbox(id), user_id BIGINT NOT NULL,
        recipient TEXT NOT NULL,status TEXT NOT NULL,message_id TEXT,created_at TIMESTAMPTZ NOT NULL)''')


def eligible_message(msg):
    # Reject auto-mail, lists, bounces, stale mail and conflicting reply addresses.
    if str(msg.get('Auto-Submitted','no')).lower() != 'no' or msg.get('List-Id') or msg.get('List-Unsubscribe') or msg.get('X-Auto-Response-Suppress'):
        return None
    if str(msg.get('Precedence','')).lower() in ('bulk','list','junk'):
        return None
    if str(msg.get('Return-Path','')).strip() == '<>':
        return None
    addresses = getaddresses(msg.get_all('From',[]))
    if len(addresses)!=1:
        return None
    address=addresses[0][1].lower()
    if not re.fullmatch(r'[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}',address):
        return None
    if address==spacemail.ADDRESS or any(x in address.split('@')[0] for x in ('noreply','no-reply','mailer-daemon','postmaster','notification')):
        return None
    if msg.get('Reply-To') and getaddresses(msg.get_all('Reply-To',[])) != addresses:
        return None
    recipients = [a.lower() for _,a in getaddresses(msg.get_all('To',[]))]
    if spacemail.ADDRESS not in recipients:
        return None
    try:
        date=parsedate_to_datetime(str(msg.get('Date','')))
        if date.tzinfo is None or not utcnow()-dt.timedelta(hours=24) <= date <= utcnow()+dt.timedelta(minutes=10):
            return None
    except (TypeError,ValueError,OverflowError):
        return None
    mid=str(msg.get('Message-ID',''))
    if not re.fullmatch(r'<[^\s<>]{1,450}>',mid):
        return None
    part=msg.get_body(preferencelist=('plain',)) if msg.is_multipart() else msg
    if not part or part.get_content_type()!='text/plain':
        return None
    text=(str(msg.get('Subject',''))+' '+str(part.get_content())[:32000]).lower()
    if not any(k in text for k in ('شحن','تخليص','نقل','تخزين','حاوية','بضاعة','shipment','freight','customs','shipping','warehouse','cargo')):
        return None
    return address


def deliver(inbox_id):
    if os.getenv('ENABLE_EXTERNAL_ACTIONS') != '1':
        return
    with db() as c:
        item=c.execute('SELECT * FROM spacemail_inbox WHERE id=%s',(inbox_id,)).fetchone()
        if not item or not item['reply_address'] or item['imported_at'] < utcnow()-dt.timedelta(hours=24):
            return
        settings=c.execute('SELECT * FROM official_reply_settings WHERE user_id=%s FOR UPDATE',(item['user_id'],)).fetchone()
        if not settings or not settings['enabled'] or item['imported_at'] <= settings['enabled_at']:
            return
        from app.production_monitor import sender_ready
        if not sender_ready(item['user_id'],spacemail.ADDRESS):
            return
        prior=c.execute('SELECT COUNT(*) n FROM official_reply_log WHERE user_id=%s AND created_at>%s',
                        (item['user_id'],utcnow()-dt.timedelta(hours=24))).fetchone()['n']
        same=c.execute('SELECT inbox_id FROM official_reply_log WHERE user_id=%s AND recipient=%s AND created_at>%s LIMIT 1',
                       (item['user_id'],item['reply_address'],utcnow()-dt.timedelta(hours=24))).fetchone()
        if prior>=20 or same:
            return
        claim=c.execute("INSERT INTO official_reply_log(inbox_id,user_id,recipient,status,created_at) VALUES(%s,%s,%s,'sending',%s) ON CONFLICT DO NOTHING RETURNING inbox_id",
                        (inbox_id,item['user_id'],item['reply_address'],utcnow())).fetchone()
        if not claim:
            return
    try:
        # Subject and body are fixed; external text is never executed or echoed.
        mid=spacemail.send(item['user_id'],item['reply_address'],'آفاق طويق — تأكيد استلام طلبك',BODY,
                           in_reply_to=item['message_id'],automatic=True)
        state='sent'
    except Exception:
        mid,state=None,'uncertain'
    with db() as c:
        c.execute('UPDATE official_reply_log SET status=%s,message_id=%s WHERE inbox_id=%s',(state,mid,inbox_id))


def tick():
    for item in rows('''SELECT i.id FROM spacemail_inbox i JOIN official_reply_settings s ON s.user_id=i.user_id
        WHERE s.enabled=TRUE AND i.imported_at>s.enabled_at AND i.reply_address IS NOT NULL
        AND NOT EXISTS(SELECT 1 FROM official_reply_log l WHERE l.inbox_id=i.id) ORDER BY i.id LIMIT 50'''):
        deliver(item['id'])


@router.get('/official-replies',response_class=HTMLResponse)
def dashboard(request:Request):
    s=spacemail.admin(request)
    config=one('SELECT enabled FROM official_reply_settings WHERE user_id=?',(s['user_id'],))
    body='<h1>الرد الأولي التلقائي</h1><p>الحالة: '+('مفعّل' if config and config['enabled'] else 'متوقف')+'</p>'
    body+='<p>لطلبات الخدمات النصية الجديدة فقط؛ رسالة واحدة لكل مرسل خلال 24 ساعة، وبحد أقصى 20 رسالة يوميًا. تُستثنى الرسائل الآلية والقوائم والرسائل القديمة. لا يقدم أسعارًا ولا ينفذ أوامر.</p><pre style="white-space:pre-wrap">'+e(BODY)+'</pre>'
    if recent_stepup(s['id']):
        body+='<form method="post">'+hidden_csrf(s)+'<label><input type="checkbox" name="enabled" value="yes" '+('checked' if config and config['enabled'] else '')+'> تفعيل الرد بالنص المعروض على الطلبات الجديدة</label><button>حفظ سياسة الرد الأولي</button></form>'
    else:
        body+='<a href="/mfa/step-up?next=/official-replies">التحقق لتعديل سياسة الرد</a>'
    for row in rows('SELECT recipient,status,created_at FROM official_reply_log WHERE user_id=? ORDER BY created_at DESC LIMIT 30',(s['user_id'],)):
        body+='<p>'+e(row['recipient'])+' · '+e(row['status'])+' · '+e(row['created_at'])+'</p>'
    return HTMLResponse(page(body),headers={'Cache-Control':'no-store'})


@router.post('/official-replies')
async def save(request:Request):
    s=spacemail.admin(request)
    from app.fine_permissions import has_permission
    if not has_permission(s,'send_email') or not recent_stepup(s['id']):
        raise HTTPException(428)
    data=await spacemail.form(request,s)
    with db() as c:
        c.execute('''INSERT INTO official_reply_settings(user_id,enabled,enabled_at) VALUES(%s,%s,%s)
            ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,
            enabled_at=CASE WHEN official_reply_settings.enabled THEN official_reply_settings.enabled_at ELSE excluded.enabled_at END''',
            (s['user_id'],data.get('enabled')=='yes',utcnow()))
    return RedirectResponse('/official-replies',303)


def register_worker(app):
    async def loop():
        while True:
            try:
                await run_in_threadpool(tick)
                from app.publication_reports import tick as report_tick
                await run_in_threadpool(report_tick)
            except Exception:
                pass
            await asyncio.sleep(60)
    @app.on_event('startup')
    async def start():
        app.state.official_reply_worker=asyncio.create_task(loop())
    @app.on_event('shutdown')
    async def stop():
        app.state.official_reply_worker.cancel()
        with suppress(asyncio.CancelledError):
            await app.state.official_reply_worker
