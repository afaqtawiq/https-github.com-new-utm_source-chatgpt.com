"""Explicitly approved customer campaigns with immutable content and send receipts."""
import asyncio
import hashlib
import json
import os
import secrets
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from app.storage import db, one, rows, execute, log, utcnow, get_session
from app.fine_permissions import has_permission
from app.spacemail import connection as mailbox_connection, send as official_send
from app import zernio_whatsapp as wa
from app.marketing_content import (EMAIL, PHONE, WEBSITE, SUBJECT, TEMPLATE_NAME,
    select_recipients, message_text, message_html)
from app.outbound import shell, esc

router = APIRouter()
KEY = 'jeddah-port-introduction-20260922-v2'
PDF = Path(__file__).parent / 'assets/afaaq-jeddah-brochure.pdf'
PDF_PATH = '/brochures/afaaq-jeddah-v2.pdf'
ART_PATH = '/brochures/afaaq-jeddah-v2.jpg'
RIYADH = ZoneInfo('Asia/Riyadh')


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS customer_campaigns(
            id BIGSERIAL PRIMARY KEY, campaign_key TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
            subject TEXT NOT NULL, plain_template TEXT NOT NULL, html_template TEXT NOT NULL,
            brochure_url TEXT NOT NULL, unsubscribe_base TEXT NOT NULL,
            created_by BIGINT NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS customer_campaign_channels(
            campaign_id BIGINT REFERENCES customer_campaigns(id), channel TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft', approved_by BIGINT, approved_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL, last_error TEXT,
            PRIMARY KEY(campaign_id,channel))''')
        c.execute('''CREATE TABLE IF NOT EXISTS customer_campaign_recipients(
            id BIGSERIAL PRIMARY KEY, campaign_id BIGINT NOT NULL REFERENCES customer_campaigns(id),
            channel TEXT NOT NULL, recipient TEXT NOT NULL, company_name TEXT NOT NULL,
            sources TEXT NOT NULL, unsubscribe_token TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending', provider_message_id TEXT, last_error TEXT,
            claimed_at TIMESTAMPTZ, sent_at TIMESTAMPTZ,
            UNIQUE(campaign_id,channel,recipient))''')
        c.execute('''CREATE TABLE IF NOT EXISTS marketing_suppressions(
            channel TEXT NOT NULL, recipient TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY(channel,recipient))''')
        c.execute('''CREATE TABLE IF NOT EXISTS customer_campaign_schedule(
            id INTEGER PRIMARY KEY CHECK(id=1), enabled BOOLEAN NOT NULL DEFAULT FALSE,
            approved_by BIGINT NOT NULL REFERENCES users(id), approved_at TIMESTAMPTZ NOT NULL,
            content_digest TEXT NOT NULL, last_error TEXT)''')


init()


def admin(request):
    s = get_session(request.cookies.get('gla_session'))
    if not s: raise HTTPException(401)
    if s.get('role') != 'admin': raise HTTPException(403)
    return s


async def checked_form(request):
    s = admin(request)
    data = {k:v[0] for k,v in parse_qs((await request.body()).decode()).items()}
    if data.get('csrf') != s['csrf']: raise HTTPException(403)
    return s, data


def origin():
    # No request Host header is ever copied into outward-facing messages.
    return os.getenv('AFAAQ_PUBLIC_ORIGIN', 'https://gulf-logistics-ai-v7-production.up.railway.app').rstrip('/')


def roster():
    return rows('''SELECT 'account:' || id::text AS source,name,phone,email,status FROM accounts
        UNION ALL SELECT 'directory:' || id::text,company_name,phone,email,'' FROM customer_directory''')


def prepare(user_id, day=None):
    day = day or datetime.now(RIYADH).date()
    daily_key = KEY + '-' + day.isoformat()
    listing = select_recipients(roster(), [(r['channel'],r['recipient']) for r in rows('SELECT * FROM marketing_suppressions')])
    url, base = origin() + PDF_PATH, origin() + '/marketing/unsubscribe/'
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(73002030)')
        existing = c.execute('SELECT id FROM customer_campaigns WHERE campaign_key=%s',(daily_key,)).fetchone()
        if existing: return existing['id']
        campaign = c.execute('''INSERT INTO customer_campaigns(campaign_key,title,subject,plain_template,html_template,
            brochure_url,unsubscribe_base,created_by,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
            (daily_key,'بروشور خدمات ميناء جدة — '+day.isoformat(),SUBJECT,message_text(url,'__UNSUBSCRIBE__'),
             message_html(url,'__UNSUBSCRIBE__'),url,base,user_id,utcnow())).fetchone()['id']
        for channel in ('email','whatsapp'):
            c.execute('INSERT INTO customer_campaign_channels(campaign_id,channel,updated_at) VALUES(%s,%s,%s)',(campaign,channel,utcnow()))
        for item in listing:
            c.execute('''INSERT INTO customer_campaign_recipients(campaign_id,channel,recipient,company_name,sources,unsubscribe_token)
                VALUES(%s,%s,%s,%s,%s,%s)''',(campaign,item['channel'],item['recipient'],item['company_name'],json.dumps(item['sources']),secrets.token_urlsafe(24)))
    log(user_id,'customer_campaign_prepared','customer_campaign',campaign,f'{len(listing)} channel recipients; no messages sent')
    return campaign


def counts(campaign):
    return rows('SELECT channel,status,COUNT(*) AS n FROM customer_campaign_recipients WHERE campaign_id=? GROUP BY channel,status ORDER BY channel,status',(campaign,))


def template_spec(campaign):
    return {'name':TEMPLATE_NAME,'language':'ar','category':'MARKETING','components':[
        {'type':'body','text':campaign['plain_template'].replace('__UNSUBSCRIBE__','{{1}}'),
         'example':{'body_text':[[campaign['unsubscribe_base']+'example']]}}]}


async def approved_template(campaign):
    expected = template_spec(campaign)['components'][0]['text']
    async with wa.client() as c:
        await wa.validate_account(c)
        for item in await wa.templates(c):
            if item.get('name') == TEMPLATE_NAME and item.get('language') == 'ar':
                body = next((p.get('text') for p in item.get('components',[]) if p.get('type','').lower()=='body'),None)
                if body == expected and item.get('status')=='APPROVED': return True
                raise wa.WhatsAppBlocked('قالب بروشور ميناء جدة: ' + str(item.get('status') or 'غير معتمد') + '؛ لم يبدأ إرسال واتساب.')
    raise wa.WhatsAppBlocked('قالب بروشور ميناء جدة لم يُجهز بعد؛ استخدم زر تجهيز القالب.')


@router.get('/customer-campaigns', response_class=HTMLResponse)
def home(request: Request):
    s=admin(request)
    audience=select_recipients(roster(),[(r['channel'],r['recipient']) for r in rows('SELECT * FROM marketing_suppressions')])
    ec=sum(r['channel']=='email' for r in audience);wc=sum(r['channel']=='whatsapp' for r in audience)
    schedule=one('SELECT * FROM customer_campaign_schedule WHERE id=1')
    enabled=bool(schedule and schedule['enabled'])
    schedule_box=f'''<div class=card><h2>الإرسال اليومي للشركات</h2><p>الحالة: {'مفعّل' if enabled else 'متوقف'} · يوميًا الساعة 9 صباحًا بتوقيت السعودية.</p>
        <p>البروشور المعتمد عبر البريد وواتساب إلى الشركات المسجلة، مرة واحدة لكل عنوان في اليوم، مع استبعاد من أوقف الرسائل. يبدأ واتساب عند اعتماد قالب Meta.</p>
        <p>{esc(schedule.get('last_error') if schedule else '')}</p>
        <form method=post action=/customer-campaigns/schedule><input type=hidden name=csrf value="{esc(s['csrf'])}">
        <input type=hidden name=enabled value="{'0' if enabled else '1'}">
        {'' if enabled else '<label><input style="width:auto" type=checkbox name=confirmed value=yes required> أعتمد إرسال هذا البروشور يوميًا عبر البريد وواتساب إلى الشركات المسجلة الحالية والجديدة</label>'}
        <button class=btn>{'إيقاف الإرسال اليومي' if enabled else 'تفعيل الإرسال اليومي'}</button></form>
        <p><a href=/mfa/step-up?next=/customer-campaigns>التحقق الأمني لتفعيل الجدولة</a></p></div>'''
    cards=''.join(f'<p><a href="/customer-campaigns/{x["id"]}">{esc(x["title"])}</a> · {esc(x["created_at"])}</p>' for x in rows('SELECT id,title,created_at FROM customer_campaigns ORDER BY id DESC'))
    return HTMLResponse(shell('حملات العملاء',f'''<div class=nav><a href=/dashboard>الرئيسية</a><a href=/accounts>العملاء</a></div>
        <h1>حملات الشركات والعملاء</h1><div class=card><h2>خدمات آفاق طويق في ميناء جدة</h2>
        <p>{EMAIL} · <span dir=ltr>{PHONE}</span> · <a href="{WEBSITE}">www.afaqtwiq.com</a></p>
        <p>قائمة العملاء المسجلين: {ec} عنوان بريد و{wc} رقم واتساب بعد التحقق من الصيغة وإزالة التكرار والاستبعادات.</p>
        <p>التحقق من الصيغة لا يثبت أن العنوان نشط. لن تُضاف قائمة السائقين أو جهات خارج سجل العملاء.</p>
        <a href="{PDF_PATH}" target=_blank><img src="{ART_PATH}" alt="بروشور خدمات آفاق طويق في ميناء جدة" style="display:block;width:100%;max-width:440px;border-radius:12px;margin:20px 0"></a><a class=btn href="{PDF_PATH}" target=_blank>عرض البروشور PDF</a>
        <form method=post action=/customer-campaigns/prepare><input type=hidden name=csrf value="{esc(s['csrf'])}"><button class=btn>تجهيز حملة ميناء جدة</button></form></div>{schedule_box}<div class=card>{cards}</div>'''))


@router.post('/customer-campaigns/prepare')
async def prepare_route(request: Request):
    s,_=await checked_form(request)
    return RedirectResponse('/customer-campaigns/'+str(prepare(s['user_id'])),303)


@router.get('/customer-campaigns/{cid}',response_class=HTMLResponse)
def detail(cid:int,request:Request):
    s=admin(request);campaign=one('SELECT * FROM customer_campaigns WHERE id=?',(cid,))
    if not campaign:raise HTTPException(404)
    listing=rows('SELECT company_name,channel,recipient,status,last_error FROM customer_campaign_recipients WHERE campaign_id=? ORDER BY channel,id',(cid,))
    stat=' · '.join(f"{x['channel']}: {x['status']} {x['n']}" for x in counts(cid))
    channels=rows('SELECT * FROM customer_campaign_channels WHERE campaign_id=? ORDER BY channel',(cid,))
    actions=''
    for ch in channels:
        name='البريد الإلكتروني' if ch['channel']=='email' else 'واتساب'
        actions+=f'<div class=card><h2>{name}</h2><p>الحالة: {esc(ch["status"])} · {esc(ch["last_error"])}</p>'
        if ch['status'] in ('draft','paused','waiting_template'):
            actions+=f'''<form method=post action="/customer-campaigns/{cid}/send/{ch['channel']}"><input type=hidden name=csrf value="{esc(s['csrf'])}"><label><input style="width:auto" type=checkbox name=confirmed value=yes required> راجعت البروشور وقائمة المستلمين وأعتمد إرسال هذه الحملة مرة واحدة</label><button class=btn>إرسال {name} للمستلمين المتبقين</button></form>'''
        actions+='</div>'
    records=''.join('<tr>'+''.join('<td>'+esc(r[k])+'</td>' for k in ('company_name','channel','recipient','status','last_error'))+'</tr>' for r in listing)
    preview=campaign['plain_template'].replace('__UNSUBSCRIBE__','رابط إيقاف خاص بكل مستلم')
    return HTMLResponse(shell(campaign['title'],f'''<div class=nav><a href=/customer-campaigns>الحملات</a><a href=/settings/email/spacemail>البريد الرسمي</a><a href=/settings/whatsapp/channel>قناة واتساب</a></div>
        <h1>{esc(campaign['title'])}</h1><div class=card><b>{esc(stat)}</b><p>sent تعني قبول مزود الإرسال؛ لا تعني وصول الرسالة أو قراءتها.</p><a class=btn href="{PDF_PATH}" target=_blank>البروشور المرفق PDF</a><p><a href="/customer-campaigns/{cid}/preview" target=_blank>معاينة البريد بتصميم البروشور</a></p><pre style="white-space:pre-wrap">{esc(preview)}</pre></div>
        <form method=post action="/customer-campaigns/{cid}/template"><input type=hidden name=csrf value="{esc(s['csrf'])}"><button class=btn>تجهيز قالب واتساب لبروشور ميناء جدة</button></form>
        <p><a href="/mfa/step-up?next=/customer-campaigns/{cid}">التحقق الأمني للإرسال</a></p>{actions}
        <div class="card scroll"><table><tr><th>الشركة</th><th>القناة</th><th>المستلم</th><th>الحالة</th><th>الملاحظة</th></tr>{records}</table></div>'''))


@router.get('/customer-campaigns/{cid}/preview',response_class=HTMLResponse)
def preview(cid:int,request:Request):
    admin(request);item=one('SELECT html_template FROM customer_campaigns WHERE id=?',(cid,))
    if not item:raise HTTPException(404)
    return HTMLResponse(item['html_template'].replace('__UNSUBSCRIBE__','#'))


@router.get(PDF_PATH)
def brochure():
    return Response(PDF.read_bytes(),media_type='application/pdf',headers={'Content-Disposition':'inline; filename="Afaaq_Jeddah_Brochure.pdf"','Cache-Control':'public, max-age=3600'})


@router.get(ART_PATH)
def brochure_artwork():
    return Response(PDF.with_suffix('.jpg').read_bytes(),media_type='image/jpeg',headers={'Cache-Control':'public, max-age=86400'})


@router.get('/marketing/unsubscribe/{token}',response_class=HTMLResponse)
def unsubscribe_page(token:str):
    if not one('SELECT id FROM customer_campaign_recipients WHERE unsubscribe_token=?',(token,)):raise HTTPException(404)
    return HTMLResponse(shell('إيقاف الرسائل',f'<div class=card><h1>إيقاف رسائل آفاق طويق التسويقية</h1><p>اضغط لتأكيد إيقاف الرسائل على هذه القناة.</p><form method=post><button class=btn>تأكيد إيقاف الرسائل</button></form></div>'))


@router.post('/marketing/unsubscribe/{token}',response_class=HTMLResponse)
def unsubscribe(token:str):
    with db() as c:
        item=c.execute('SELECT channel,recipient FROM customer_campaign_recipients WHERE unsubscribe_token=%s',(token,)).fetchone()
        if not item:raise HTTPException(404)
        c.execute('INSERT INTO marketing_suppressions(channel,recipient,created_at) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(item['channel'],item['recipient'],utcnow()))
        c.execute("UPDATE customer_campaign_recipients SET status='suppressed' WHERE channel=%s AND recipient=%s AND status IN ('pending','blocked')",(item['channel'],item['recipient']))
    return HTMLResponse(shell('تم إيقاف الرسائل','<div class=card><h1>تم إيقاف الرسائل التسويقية على هذه القناة.</h1></div>'))


@router.post('/customer-campaigns/{cid}/template')
async def provision(cid:int,request:Request):
    s,_=await checked_form(request)
    if not has_permission(s,'send_whatsapp'):raise HTTPException(403)
    campaign=one('SELECT * FROM customer_campaigns WHERE id=?',(cid,))
    if not campaign:raise HTTPException(404)
    async with wa.client() as c:
        await wa.validate_account(c)
        listing=await wa.templates(c)
        if not any(x.get('name')==TEMPLATE_NAME and x.get('language')=='ar' for x in listing):
            result=await c.post(wa.BASE+'/whatsapp/templates',json={'accountId':wa.account_id(),**template_spec(campaign)})
            if not result.is_success:raise HTTPException(503,'لم يؤكد المزود إنشاء قالب البروشور؛ لم تُرسل رسائل.')
    execute("UPDATE customer_campaign_channels SET status='waiting_template',last_error=?,updated_at=? WHERE campaign_id=? AND channel='whatsapp' AND status IN ('draft','waiting_template')",('بانتظار اعتماد قالب البروشور من Meta',utcnow(),cid))
    return RedirectResponse(f'/customer-campaigns/{cid}',303)


async def deliver(cid,channel,user_id):
    campaign=one('SELECT * FROM customer_campaigns WHERE id=?',(cid,))
    if not campaign:return
    # Atomic row claims survive concurrent requests. A crash leaves sending rows
    # uncertain, never eligible for an automatic repeat.
    for _ in range(2000):
        state=one('SELECT status FROM customer_campaign_channels WHERE campaign_id=? AND channel=?',(cid,channel))
        if not state or state['status']!='sending':return
        with db() as c:
            c.execute("UPDATE customer_campaign_recipients r SET status='suppressed' WHERE campaign_id=%s AND channel=%s AND status='pending' AND EXISTS(SELECT 1 FROM marketing_suppressions s WHERE s.channel=r.channel AND s.recipient=r.recipient)",(cid,channel))
            item=c.execute("""UPDATE customer_campaign_recipients SET status='sending',claimed_at=%s WHERE id=(
                SELECT id FROM customer_campaign_recipients WHERE campaign_id=%s AND channel=%s AND status='pending'
                ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *""",(utcnow(),cid,channel)).fetchone()
        if not item:break
        url=campaign['unsubscribe_base']+item['unsubscribe_token']
        body=campaign['plain_template'].replace('__UNSUBSCRIBE__',url)
        try:
            if channel=='email':
                mid=await run_in_threadpool(official_send,user_id,item['recipient'],campaign['subject'],body,
                    ('Afaaq_Jeddah_Brochure.pdf','application/pdf',PDF.read_bytes()),
                    html_body=campaign['html_template'].replace('__UNSUBSCRIBE__',url))
            else:
                result=await wa.send(item['recipient'],body,template_prefix='afaaq_marketing_')
                mid=result['messages'][0]['id']
            if not mid:raise RuntimeError('Missing provider receipt')
        except Exception as exc:
            status='blocked' if isinstance(exc,wa.WhatsAppBlocked) else 'uncertain'
            error=str(exc)[:300] if status=='blocked' else 'تعذر تأكيد نتيجة الإرسال؛ راجع المزود قبل أي إعادة إرسال.'
            execute('UPDATE customer_campaign_recipients SET status=?,last_error=? WHERE id=?',(status,error,item['id']))
            execute("UPDATE customer_campaign_channels SET status='paused',last_error=?,updated_at=? WHERE campaign_id=? AND channel=?",(error,utcnow(),cid,channel))
            return
        execute("UPDATE customer_campaign_recipients SET status='sent',provider_message_id=?,sent_at=?,last_error=NULL WHERE id=?",(mid,utcnow(),item['id']))
    execute("UPDATE customer_campaign_channels SET status='completed',updated_at=? WHERE campaign_id=? AND channel=? AND status='sending'",(utcnow(),cid,channel))
    log(user_id,'customer_campaign_channel_finished','customer_campaign',cid,channel+'; provider receipts recorded')


@router.post('/customer-campaigns/{cid}/send/{channel}')
async def send_campaign(cid:int,channel:str,request:Request,background_tasks:BackgroundTasks):
    s,data=await checked_form(request)
    if channel not in ('email','whatsapp'):raise HTTPException(404)
    if not has_permission(s,'send_'+channel):raise HTTPException(403)
    if data.get('confirmed')!='yes':raise HTTPException(400,'راجع المحتوى والمستلمين وأكد الإرسال.')
    if os.getenv('ENABLE_EXTERNAL_ACTIONS','0')!='1':raise HTTPException(409,'الإرسال الخارجي غير مفعّل.')
    campaign=one('SELECT * FROM customer_campaigns WHERE id=?',(cid,))
    if not campaign:raise HTTPException(404)
    if channel=='email':
        conn=mailbox_connection(s['user_id'])
        if not conn or conn['status']!='connected':raise HTTPException(409,'البريد الرسمي غير متصل.')
    else:
        try:await approved_template(campaign)
        except wa.WhatsAppBlocked as exc:
            execute("UPDATE customer_campaign_channels SET status='waiting_template',last_error=?,updated_at=? WHERE campaign_id=? AND channel='whatsapp' AND status IN ('draft','paused','waiting_template')",(str(exc),utcnow(),cid))
            return RedirectResponse(f'/customer-campaigns/{cid}',303)
    with db() as c:
        claimed=c.execute("""UPDATE customer_campaign_channels SET status='sending',approved_by=%s,approved_at=%s,
            updated_at=%s,last_error=NULL WHERE campaign_id=%s AND channel=%s AND status IN ('draft','paused','waiting_template') RETURNING channel""",(s['user_id'],utcnow(),utcnow(),cid,channel)).fetchone()
        if not claimed:raise HTTPException(409,'هذه القناة قيد الإرسال أو سبق اكتمالها.')
        c.execute("UPDATE customer_campaign_recipients SET status='pending',last_error=NULL WHERE campaign_id=%s AND channel=%s AND status='blocked'",(cid,channel))
    log(s['user_id'],'customer_campaign_approved','customer_campaign',cid,channel+'; exact immutable content and recipient roster approved')
    background_tasks.add_task(deliver,cid,channel,s['user_id'])
    return RedirectResponse(f'/customer-campaigns/{cid}',303)


def content_digest():
    data = (SUBJECT + message_text(origin()+PDF_PATH,'__UNSUBSCRIBE__') +
            message_html(origin()+PDF_PATH,'__UNSUBSCRIBE__')).encode()
    return hashlib.sha256(data + PDF.read_bytes() + PDF.with_suffix('.jpg').read_bytes()).hexdigest()


@router.post('/customer-campaigns/schedule')
async def schedule_campaign(request:Request):
    s,data=await checked_form(request)
    if not all(has_permission(s,p) for p in ('send_email','send_whatsapp')):raise HTTPException(403)
    enabled=data.get('enabled')=='1'
    if enabled and data.get('confirmed')!='yes':raise HTTPException(400,'اعتمد الإرسال اليومي أولًا.')
    execute('''INSERT INTO customer_campaign_schedule(id,enabled,approved_by,approved_at,content_digest)
        VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled,
        approved_by=excluded.approved_by,approved_at=excluded.approved_at,
        content_digest=excluded.content_digest,last_error=NULL''',(enabled,s['user_id'],utcnow(),content_digest()))
    if not enabled:
        execute("UPDATE customer_campaign_channels SET status='paused',last_error=? WHERE status='sending' AND campaign_id IN (SELECT id FROM customer_campaigns WHERE campaign_key LIKE ?)",('أوقف المسؤول الإرسال اليومي.',KEY+'-%'))
    log(s['user_id'],'customer_campaign_schedule','customer_campaign',None,
        ('Enabled' if enabled else 'Disabled')+' daily 09:00 Asia/Riyadh; email and WhatsApp; current and newly registered customers; approved artwork fingerprint')
    return RedirectResponse('/customer-campaigns',303)


async def daily_tick(now=None):
    now=(now or datetime.now(RIYADH)).astimezone(RIYADH)
    schedule=one('SELECT * FROM customer_campaign_schedule WHERE id=1')
    if not schedule or not schedule['enabled'] or now.hour<9:return
    if os.getenv('ENABLE_EXTERNAL_ACTIONS','0')!='1':return
    user=one('SELECT id,role,is_active FROM users WHERE id=?',(schedule['approved_by'],))
    from app.mfa_stepup import mfa_state
    mfa=mfa_state(schedule['approved_by'])
    if (not user or not user['is_active'] or user['role']!='admin' or not mfa or not mfa['mfa_enabled']
        or not all(has_permission(user,p) for p in ('send_email','send_whatsapp'))):
        execute('UPDATE customer_campaign_schedule SET enabled=FALSE,last_error=? WHERE id=1',('توقفت الجدولة بسبب تغير صلاحية حساب الاعتماد.',));return
    if schedule['content_digest']!=content_digest():
        execute('UPDATE customer_campaign_schedule SET enabled=FALSE,last_error=? WHERE id=1',('تغير محتوى البروشور؛ راجعه وأعد تفعيل الجدولة.',));return
    cid=prepare(user['id'],now.date())
    campaign=one('SELECT * FROM customer_campaigns WHERE id=?',(cid,))
    for channel in ('email','whatsapp'):
        state=one('SELECT * FROM customer_campaign_channels WHERE campaign_id=? AND channel=?',(cid,channel))
        if state['status'] not in ('draft','waiting_template'):continue
        if state['status']=='waiting_template' and state['updated_at']>utcnow()-timedelta(minutes=30):continue
        try:
            if channel=='email':
                connection=mailbox_connection(user['id'])
                if not connection or connection['status']!='connected':
                    raise wa.WhatsAppBlocked('البريد الرسمي غير متصل؛ لم يبدأ إرسال البريد.')
            else:await approved_template(campaign)
        except (wa.WhatsAppBlocked,wa.httpx.HTTPError):
            execute("UPDATE customer_campaign_channels SET status='waiting_template',last_error=?,updated_at=? WHERE campaign_id=? AND channel=? AND status IN ('draft','waiting_template')",
                ('بانتظار جاهزية البريد الرسمي.' if channel=='email' else 'بانتظار اعتماد قالب واتساب وجاهزية القناة.',utcnow(),cid,channel))
            continue
        with db() as c:
            # Persisted schedule and atomic channel claim prevent parallel workers
            # or restarts from replaying any already-started daily batch.
            claimed=c.execute("""UPDATE customer_campaign_channels SET status='sending',approved_by=%s,
                approved_at=%s,updated_at=%s,last_error=NULL WHERE campaign_id=%s AND channel=%s
                AND status IN ('draft','waiting_template') AND EXISTS(
                SELECT 1 FROM customer_campaign_schedule WHERE id=1 AND enabled=TRUE AND content_digest=%s)
                RETURNING channel""",(user['id'],schedule['approved_at'],utcnow(),cid,channel,schedule['content_digest'])).fetchone()
        if claimed:await deliver(cid,channel,user['id'])


def register_worker(app):
    async def loop():
        while True:
            try:await daily_tick()
            except asyncio.CancelledError:raise
            except Exception:
                execute('UPDATE customer_campaign_schedule SET last_error=? WHERE id=1 AND enabled=TRUE',
                    ('تعذر إكمال فحص الحملة اليومية؛ راجع حالة قنوات الإرسال.',))
            await asyncio.sleep(60)
    @app.on_event('startup')
    async def start():app.state.customer_marketing_worker=asyncio.create_task(loop())
    @app.on_event('shutdown')
    async def stop():
        task=getattr(app.state,'customer_marketing_worker',None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):await task
