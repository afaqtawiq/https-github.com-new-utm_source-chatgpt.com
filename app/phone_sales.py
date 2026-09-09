import os,html,urllib.parse,re
import httpx
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import db,get_session,one,execute,utcnow,log,verify_password
router=APIRouter()
RETELL_API_KEY=os.getenv('RETELL_API_KEY','')
RETELL_AGENT_ID=os.getenv('RETELL_AGENT_ID','')
RETELL_FROM_NUMBER=os.getenv('RETELL_FROM_NUMBER','')
PHONE_CALLS_TEST_MODE=os.getenv('PHONE_CALLS_TEST_MODE','1')=='1'
TEST_PHONE_RECIPIENT=os.getenv('TEST_PHONE_RECIPIENT','')
RETELL_TRANSFER_SAFE=os.getenv('RETELL_TRANSFER_SAFE','0')=='1'
def init():
 with db() as c:c.execute('''CREATE TABLE IF NOT EXISTS phone_call_actions(id BIGSERIAL PRIMARY KEY,opportunity_id BIGINT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,contact_id BIGINT REFERENCES sales_contacts(id) ON DELETE SET NULL,phone TEXT NOT NULL,objective TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',approval_id BIGINT REFERENCES approvals(id) ON DELETE SET NULL,provider TEXT NOT NULL DEFAULT 'retell',provider_call_id TEXT,last_error TEXT,created_by BIGINT,approved_by BIGINT,created_at TIMESTAMPTZ NOT NULL,approved_at TIMESTAMPTZ,started_at TIMESTAMPTZ,updated_at TIMESTAMPTZ NOT NULL)''')
init()
def e(v):return html.escape(str(v or ''))
def form(raw):return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode(),keep_blank_values=True).items()}
def normalize_phone(v):
 v=(v or '').strip()
 if v.startswith(' '):v='+'+v.lstrip()
 v=re.sub(r'[\s\-()]+','',v)
 if v.startswith('00'):v='+'+v[2:]
 return v
def sess(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s

@router.get('/retell-web-test',response_class=HTMLResponse)
def web_test_page(r:Request):
 s=sess(r)
 return HTMLResponse(f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>اختبار وكيل آفاق طويق</title><style>body{{font-family:Arial;background:#f4f7fb;color:#17202a;display:grid;place-items:center;min-height:90vh}}.box{{background:#fff;max-width:560px;width:90%;padding:28px;border-radius:18px;box-shadow:0 8px 30px #0002}}input,button{{box-sizing:border-box;width:100%;padding:13px;margin:7px 0;border-radius:9px;border:1px solid #ccd4df}}button{{background:#155eef;color:white;font-weight:bold;cursor:pointer}}button.stop{{background:#b42318}}#status{{padding:12px;background:#eef4ff;border-radius:9px;margin:10px 0}}#transcript{{white-space:pre-wrap;max-height:260px;overflow:auto}}</style><div class=box><h1>اختبار Web Call</h1><p>تحدث مباشرة مع وكيل <b>Afaaq Tuwaiq Sales AI</b> عبر ميكروفون المتصفح، دون رقم هاتف.</p><input id=password type=password autocomplete=current-password placeholder="كلمة مرور الحساب"><button id=start>بدء الاختبار الصوتي</button><button id=stop class=stop disabled>إنهاء المكالمة</button><div id=status>جاهز</div><div id=transcript></div></div><script type=module>import{{RetellWebClient}}from'https://esm.sh/retell-client-js-sdk';const client=new RetellWebClient(),start=document.querySelector('#start'),stop=document.querySelector('#stop'),status=document.querySelector('#status'),transcript=document.querySelector('#transcript');client.on('call_started',()=>{{status.textContent='المكالمة متصلة — تحدث الآن';start.disabled=true;stop.disabled=false}});client.on('update',u=>{{transcript.textContent=(u.transcript||[]).map(x=>(x.role==='agent'?'الوكيل: ':'أنت: ')+x.content).join('\n')}});client.on('call_ended',()=>{{status.textContent='انتهت المكالمة';start.disabled=false;stop.disabled=true}});client.on('error',e=>{{status.textContent='تعذر تشغيل المكالمة: '+String(e);client.stopCall()}});start.onclick=async()=>{{start.disabled=true;status.textContent='جارٍ الاتصال...';const body=new URLSearchParams({{csrf:'{e(s['csrf'])}',password:document.querySelector('#password').value}});const response=await fetch('/retell-web-test/start',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body}});const data=await response.json();if(!response.ok){{status.textContent=data.detail||'فشل بدء الاختبار';start.disabled=false;return}}try{{await client.startCall({{accessToken:data.access_token}})}}catch(e){{status.textContent='اسمح للمتصفح باستخدام الميكروفون ثم حاول مجددًا';start.disabled=false}}}};stop.onclick=()=>client.stopCall();</script>''')

@router.post('/retell-web-test/start')
async def start_web_test(r:Request):
 s=sess(r);d=form(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 import datetime
 since=utcnow()-datetime.timedelta(minutes=15);fails=one("SELECT COUNT(*) n FROM mfa_attempts WHERE user_id=? AND kind='web_call_password' AND success=0 AND created_at>=?",(s['user_id'],since))
 if int((fails or {}).get('n') or 0)>=5:raise HTTPException(429,'Too many password attempts; try again later')
 u=one('SELECT password_hash FROM users WHERE id=?',(s['user_id'],));password_ok=bool(u and verify_password(d.get('password',''),u['password_hash']))
 execute('INSERT INTO mfa_attempts(user_id,session_id,kind,success,ip_address,created_at) VALUES(?,?,?,?,?,?)',(s['user_id'],s['id'],'web_call_password',1 if password_ok else 0,r.client.host if r.client else None,utcnow()))
 if not password_ok:raise HTTPException(400,'Invalid account password')
 if not RETELL_API_KEY or not RETELL_AGENT_ID:raise HTTPException(503,'Retell web-call configuration incomplete')
 payload={'agent_id':RETELL_AGENT_ID,'metadata':{'pilot_test':True,'initiated_by_user_id':s['user_id']},'retell_llm_dynamic_variables':{'call_objective':'Authorized browser voice test for Afaaq Tuwaiq Sales AI'}}
 try:
  async with httpx.AsyncClient(timeout=15) as client:resp=await client.post('https://api.retellai.com/v2/create-web-call',headers={'Authorization':'Bearer '+RETELL_API_KEY,'Content-Type':'application/json'},json=payload)
  if resp.status_code>=300:
   try:detail=str((resp.json() or {}).get('message') or (resp.json() or {}).get('detail') or '')
   except Exception:detail=''
   raise HTTPException(502,('Retell HTTP '+str(resp.status_code)+((': '+detail) if detail else ''))[:500])
  data=resp.json();token=str(data.get('access_token') or '');cid=str(data.get('call_id') or '')
  if not token:raise HTTPException(502,'Retell did not return a web-call access token')
  log(s['user_id'],'retell_web_test_started','retell_call',None,'Authorized Retell browser web call created: '+cid[:80])
  return {'access_token':token,'call_id':cid}
 except HTTPException:raise
 except Exception:raise HTTPException(502,'Retell web-call request failed')
def action_html(x,s):
 aid=str(x['id'])
 if x['status']=='draft':return f'<form method=post action=/phone-sales/{aid}/request-approval><input type=hidden name=csrf value="{e(s["csrf"])}"><button>طلب الموافقة</button></form>'
 if x['status']=='approval_requested' and s.get('role')=='admin':return f'<form method=post action=/phone-sales/{aid}/approve><input type=hidden name=csrf value="{e(s["csrf"])}"><button>موافقة الإدارة</button></form>'
 if x['status'] in ('approved','failed') and x.get('approval_status')=='approved':return f'<form method=post action=/phone-sales/{aid}/execute><input type=hidden name=csrf value="{e(s["csrf"])}"><input type=password name=password autocomplete=current-password placeholder="كلمة مرور الحساب" required><button>تأكيد كلمة المرور وتنفيذ Retell</button></form>'
 return ''
@router.get('/phone-sales',response_class=HTMLResponse)
def page(r:Request):
 s=sess(r)
 with db() as c:
  items=c.execute('''SELECT a.*,o.company_name,o.stage,c.name contact_name,c.verified,p.status approval_status FROM phone_call_actions a JOIN opportunities o ON o.id=a.opportunity_id LEFT JOIN sales_contacts c ON c.id=a.contact_id LEFT JOIN approvals p ON p.id=a.approval_id ORDER BY a.updated_at DESC LIMIT 100''').fetchall()
  opps=c.execute("SELECT id,company_name,stage FROM opportunities WHERE stage NOT IN ('won','lost') ORDER BY updated_at DESC LIMIT 100").fetchall()
 rows=''.join(f"<tr><td>{e(x['company_name'])}</td><td>{e(x['contact_name'])}</td><td dir=ltr>{e(x['phone'])}</td><td>{e(x['objective'])}</td><td>{e(x['status'])}</td><td>{action_html(x,s)}</td></tr>" for x in items)
 options=''.join(f"<option value={x['id']}>{e(x['company_name'])} — {e(x['stage'])}</option>" for x in opps)
 pilot=('مفعّل' if PHONE_CALLS_TEST_MODE else 'متوقف');transfer=('آمن' if RETELL_TRANSFER_SAFE else 'غير مؤكد — التنفيذ محظور')
 return HTMLResponse(f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><title>مكالمات المبيعات</title><style>body{{font-family:Arial;background:#f5f7fa;padding:28px}}.box{{background:white;padding:20px;border-radius:14px;margin-bottom:18px}}.status{{background:#eef7ff;padding:12px;border-radius:10px;margin:8px 0}}input,select,textarea,button{{padding:10px;margin:5px;width:100%;box-sizing:border-box}}table{{width:100%;border-collapse:collapse}}td,th{{padding:9px;border-bottom:1px solid #ddd}}button{{cursor:pointer}}</style><div class=box><h1>مكالمات المبيعات — Retell</h1><p>تجهيز → طلب موافقة → موافقة الإدارة → تأكيد كلمة المرور → تنفيذ Retell. لا توجد مكالمة تلقائية.</p><div class=status>وضع الاختبار: {pilot} | رقم الاختبار المسموح: <span dir=ltr>{e(TEST_PHONE_RECIPIENT or 'غير مضبوط')}</span> | حالة تحويل المكالمة: {transfer}</div><form method=post action=/phone-sales/prepare accept-charset="UTF-8"><input type=hidden name=csrf value="{e(s['csrf'])}"><label>الفرصة</label><select name=opportunity_id required>{options}</select><label>رقم هاتف العميل المسجل</label><input name=phone type=tel dir=ltr autocomplete=tel value="{e(TEST_PHONE_RECIPIENT)}" placeholder="+9665XXXXXXXX" required><small>يجب أن يطابق جهة اتصال موثقة في CRM.</small><label>هدف المكالمة</label><textarea name=objective required>مكالمة اختبار مصرح بها للتأكد من تشغيل مساعد آفاق طويق للمبيعات عبر Retell دون تقديم أسعار أو التزامات.</textarea><button>تجهيز المكالمة فقط</button></form></div><div class=box><table><tr><th>الشركة</th><th>جهة الاتصال</th><th>الهاتف</th><th>الهدف</th><th>الحالة</th><th>الإجراء</th></tr>{rows or '<tr><td colspan=6>لا توجد إجراءات بعد.</td></tr>'}</table></div></html>''')
@router.post('/phone-sales/prepare')
async def prepare(r:Request):
 s=sess(r);d=form(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 try:oid=int(d.get('opportunity_id','0'))
 except:raise HTTPException(400,'Opportunity is required')
 phone=normalize_phone(d.get('phone'));objective=(d.get('objective') or '').strip()
 if not re.fullmatch(r'\+[1-9]\d{7,14}',phone or ''):raise HTTPException(400,'Phone must be E.164, for example +9665XXXXXXXX')
 if PHONE_CALLS_TEST_MODE and (not TEST_PHONE_RECIPIENT or phone!=normalize_phone(TEST_PHONE_RECIPIENT)):raise HTTPException(403,'Pilot mode permits only the configured test recipient')
 if not objective:raise HTTPException(400,'Call objective is required')
 contact=one('SELECT id,name,verified,phone FROM sales_contacts WHERE opportunity_id=? AND (phone=? OR REPLACE(REPLACE(REPLACE(REPLACE(phone,\' \',\'\'),\'-\',\'\'),\'(\',\'\'),\')\',\'\')=?)',(oid,phone,phone))
 if not contact or not contact.get('verified'):raise HTTPException(400,'Phone must match a verified CRM contact for this opportunity')
 now=utcnow();aid=execute('INSERT INTO phone_call_actions(opportunity_id,contact_id,phone,objective,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(oid,contact['id'],phone,objective,'draft',s['user_id'],now,now));log(s['user_id'],'phone_call_prepared','phone_call_action',aid,'Retell phone call prepared; no external call');return RedirectResponse('/phone-sales',303)
@router.post('/phone-sales/{aid}/request-approval')
async def request_approval(aid:int,r:Request):
 s=sess(r);d=form(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 a=one('SELECT * FROM phone_call_actions WHERE id=?',(aid,))
 if not a or a['status']!='draft':raise HTTPException(400)
 ap=execute('INSERT INTO approvals(kind,entity_type,entity_id,status,requested_by,created_at) VALUES(?,?,?,?,?,?)',('phone_call','phone_call_action',aid,'pending',s['user_id'],utcnow()))
 execute("UPDATE phone_call_actions SET status='approval_requested',approval_id=?,updated_at=? WHERE id=?",(ap,utcnow(),aid));log(s['user_id'],'phone_call_approval_requested','phone_call_action',aid,'Human approval requested');return RedirectResponse('/phone-sales',303)
@router.post('/phone-sales/{aid}/approve')
async def approve(aid:int,r:Request):
 s=sess(r);d=form(await r.body())
 if s.get('role')!='admin':raise HTTPException(403)
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 a=one('SELECT * FROM phone_call_actions WHERE id=?',(aid,))
 if not a or a['status']!='approval_requested':raise HTTPException(400)
 now=utcnow();execute("UPDATE approvals SET status='approved',decided_by=?,decided_at=? WHERE id=? AND status='pending'",(s['user_id'],now,a['approval_id']));execute("UPDATE phone_call_actions SET status='approved',approved_by=?,approved_at=?,updated_at=? WHERE id=?",(s['user_id'],now,now,aid));log(s['user_id'],'phone_call_approved','phone_call_action',aid,'Phone call approved by human after MFA gate');return RedirectResponse('/phone-sales',303)
@router.post('/phone-sales/{aid}/execute')
async def execute_call(aid:int,r:Request):
 s=sess(r);d=form(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 import datetime
 since=utcnow()-datetime.timedelta(minutes=15);fails=one("SELECT COUNT(*) n FROM mfa_attempts WHERE user_id=? AND kind='phone_execute_password' AND success=0 AND created_at>=?",(s['user_id'],since))
 if int((fails or {}).get('n') or 0)>=5:raise HTTPException(429,'Too many password attempts; try again later')
 u=one('SELECT password_hash FROM users WHERE id=?',(s['user_id'],));password_ok=bool(u and verify_password(d.get('password',''),u['password_hash']))
 execute('INSERT INTO mfa_attempts(user_id,session_id,kind,success,ip_address,created_at) VALUES(?,?,?,?,?,?)',(s['user_id'],s['id'],'phone_execute_password',1 if password_ok else 0,r.client.host if r.client else None,utcnow()))
 if not password_ok:raise HTTPException(400,'Invalid account password')
 a=one('SELECT a.*,p.status approval_status FROM phone_call_actions a LEFT JOIN approvals p ON p.id=a.approval_id WHERE a.id=?',(aid,))
 if not a or a['status'] not in ('approved','failed') or a.get('approval_status')!='approved':raise HTTPException(403,'Approved human authorization required')
 if PHONE_CALLS_TEST_MODE and (not TEST_PHONE_RECIPIENT or normalize_phone(a['phone'])!=normalize_phone(TEST_PHONE_RECIPIENT)):raise HTTPException(403,'Pilot mode permits only the configured test recipient')
 if not RETELL_TRANSFER_SAFE:raise HTTPException(409,'Retell transfer destination must be disabled or replaced with an authorized number before a real call')
 if not RETELL_API_KEY or not RETELL_AGENT_ID or not RETELL_FROM_NUMBER:raise HTTPException(503,'Retell outbound configuration incomplete')
 try:
  headers={'Authorization':'Bearer '+RETELL_API_KEY,'Content-Type':'application/json'}
  async with httpx.AsyncClient(timeout=15) as client:
   from_number=RETELL_FROM_NUMBER
   number_check=await client.get('https://api.retellai.com/get-phone-number/'+urllib.parse.quote(from_number,safe=''),headers=headers)
   if number_check.status_code==404:
    listed=await client.get('https://api.retellai.com/list-phone-numbers',headers=headers)
    if listed.status_code!=200:raise HTTPException(502,'Retell could not list account phone numbers')
    numbers=listed.json()
    if isinstance(numbers,dict):numbers=numbers.get('phone_numbers') or numbers.get('data') or []
    valid=[x for x in numbers if isinstance(x,dict) and x.get('phone_number')]
    linked=[x for x in valid if x.get('outbound_agent_id')==RETELL_AGENT_ID]
    choices=linked or valid
    if len(choices)!=1:raise HTTPException(409,'Retell sending number is invalid and no unique authorized replacement is available')
    from_number=str(choices[0]['phone_number'])
   elif number_check.status_code!=200:raise HTTPException(502,'Retell phone-number verification failed')
   payload={'from_number':from_number,'to_number':a['phone'],'override_agent_id':RETELL_AGENT_ID,'metadata':{'opportunity_id':a['opportunity_id'],'phone_call_action_id':aid,'pilot_test':PHONE_CALLS_TEST_MODE},'retell_llm_dynamic_variables':{'call_objective':a['objective']}}
   resp=await client.post('https://api.retellai.com/v2/create-phone-call',headers=headers,json=payload)
  if resp.status_code>=300:
   try:
    body=resp.json();detail=str(body.get('message') or body.get('detail') or body.get('error') or '')
   except Exception:detail=''
   err=('Retell HTTP '+str(resp.status_code)+((': '+detail) if detail else ''))[:500];execute("UPDATE phone_call_actions SET status='approved',last_error=?,updated_at=? WHERE id=?",(err,utcnow(),aid));raise HTTPException(502,err)
  data=resp.json();cid=str(data.get('call_id') or '')
  execute("UPDATE phone_call_actions SET status='started',provider_call_id=?,started_at=?,updated_at=? WHERE id=?",(cid,utcnow(),utcnow(),aid));log(s['user_id'],'phone_call_started','phone_call_action',aid,'Approved Retell pilot call started');return RedirectResponse('/phone-sales',303)
 except HTTPException:raise
 except Exception as ex:
  execute("UPDATE phone_call_actions SET status='approved',last_error=?,updated_at=? WHERE id=?",(str(ex)[:500],utcnow(),aid));raise HTTPException(502,'Retell call request failed')
@router.get('/api/v7/phone-sales')
def api(r:Request):
 sess(r)
 with db() as c:items=c.execute('SELECT id,opportunity_id,contact_id,objective,status,approval_id,provider,provider_call_id,last_error,created_at,approved_at,started_at,updated_at FROM phone_call_actions ORDER BY updated_at DESC LIMIT 100').fetchall()
 return {'items':[dict(x) for x in items],'automatic_external_calls':False,'pilot_test_mode':PHONE_CALLS_TEST_MODE,'test_recipient_configured':bool(TEST_PHONE_RECIPIENT),'retell_transfer_safe':RETELL_TRANSFER_SAFE}
