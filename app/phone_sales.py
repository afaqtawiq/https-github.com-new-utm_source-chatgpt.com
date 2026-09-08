import os,html,urllib.parse,json,re
import httpx
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse,JSONResponse
from app.storage import db,get_session,one,execute,utcnow,log
router=APIRouter()
RETELL_API_KEY=os.getenv('RETELL_API_KEY','')
RETELL_AGENT_ID=os.getenv('RETELL_AGENT_ID','')
RETELL_FROM_NUMBER=os.getenv('RETELL_FROM_NUMBER','')

def init():
 with db() as c:c.execute('''CREATE TABLE IF NOT EXISTS phone_call_actions(id BIGSERIAL PRIMARY KEY,opportunity_id BIGINT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,contact_id BIGINT REFERENCES sales_contacts(id) ON DELETE SET NULL,phone TEXT NOT NULL,objective TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',approval_id BIGINT REFERENCES approvals(id) ON DELETE SET NULL,provider TEXT NOT NULL DEFAULT 'retell',provider_call_id TEXT,last_error TEXT,created_by BIGINT,approved_by BIGINT,created_at TIMESTAMPTZ NOT NULL,approved_at TIMESTAMPTZ,started_at TIMESTAMPTZ,updated_at TIMESTAMPTZ NOT NULL)''')
init()
def e(v):return html.escape(str(v or ''))
def form(raw):return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode(),keep_blank_values=True).items()}
def normalize_phone(v):
 v=(v or '').strip()
 # application/x-www-form-urlencoded decodes a literal + as a space; recover it before validation.
 if v.startswith(' '):v='+'+v.lstrip()
 v=re.sub(r'[\s\-()]+','',v)
 if v.startswith('00'):v='+'+v[2:]
 return v
def sess(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s
@router.get('/phone-sales',response_class=HTMLResponse)
def page(r:Request):
 s=sess(r)
 with db() as c:
  items=c.execute('''SELECT a.*,o.company_name,o.stage,c.name contact_name,c.verified FROM phone_call_actions a JOIN opportunities o ON o.id=a.opportunity_id LEFT JOIN sales_contacts c ON c.id=a.contact_id ORDER BY a.updated_at DESC LIMIT 100''').fetchall()
  opps=c.execute("SELECT id,company_name,stage FROM opportunities WHERE stage NOT IN ('won','lost') ORDER BY updated_at DESC LIMIT 100").fetchall()
 rows=''.join(f"<tr><td>{e(x['company_name'])}</td><td>{e(x['contact_name'])}</td><td>{e(x['phone'])}</td><td>{e(x['objective'])}</td><td>{e(x['status'])}</td><td>{'<form method=post action=/phone-sales/'+str(x['id'])+'/request-approval><input type=hidden name=csrf value='+e(s['csrf'])+'><button>طلب الموافقة</button></form>' if x['status']=='draft' else ''}{'<form method=post action=/phone-sales/'+str(x['id'])+'/execute><input type=hidden name=csrf value='+e(s['csrf'])+'><button>تنفيذ المكالمة</button></form>' if x['status']=='approved' else ''}</td></tr>" for x in items)
 options=''.join(f"<option value={x['id']}>{e(x['company_name'])} — {e(x['stage'])}</option>" for x in opps)
 return HTMLResponse(f'''<html lang="ar" dir="rtl"><meta charset="utf-8"><style>body{{font-family:Arial;background:#f5f7fa;padding:28px}}.box{{background:white;padding:20px;border-radius:14px;margin-bottom:18px}}input,select,textarea,button{{padding:10px;margin:5px;width:100%;box-sizing:border-box}}table{{width:100%;border-collapse:collapse}}td,th{{padding:9px;border-bottom:1px solid #ddd}}button{{cursor:pointer}}</style><div class=box><h1>مكالمات المبيعات — Retell</h1><p>Draft → Approval → MFA step-up → Retell. لا توجد مكالمة تلقائية.</p><form method=post action=/phone-sales/prepare accept-charset="UTF-8"><input type=hidden name=csrf value="{e(s['csrf'])}"><label>الفرصة</label><select name=opportunity_id>{options}</select><label>رقم هاتف العميل المسجل</label><input name=phone type=tel dir=ltr autocomplete=tel placeholder="+9665XXXXXXXX" required><small>استخدم +9665XXXXXXXX أو 009665XXXXXXXX. يجب أن يطابق جهة اتصال موثقة في CRM.</small><label>هدف المكالمة</label><textarea name=objective required placeholder="تأهيل احتياج التخليص الجمركي والنقل"></textarea><button>تجهيز المكالمة فقط</button></form></div><div class=box><table><tr><th>الشركة</th><th>جهة الاتصال</th><th>الهاتف</th><th>الهدف</th><th>الحالة</th><th>الإجراء</th></tr>{rows or '<tr><td colspan=6>لا توجد إجراءات بعد.</td></tr>'}</table></div></html>''')
@router.post('/phone-sales/prepare')
async def prepare(r:Request):
 s=sess(r);d=form(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 try:oid=int(d.get('opportunity_id','0'))
 except:raise HTTPException(400,'Opportunity is required')
 phone=normalize_phone(d.get('phone'));objective=(d.get('objective') or '').strip()
 if not re.fullmatch(r'\+[1-9]\d{7,14}',phone or ''):raise HTTPException(400,'Phone must be E.164, for example +9665XXXXXXXX')
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
 now=utcnow();execute("UPDATE approvals SET status='approved',decided_by=?,decided_at=? WHERE id=? AND status='pending'",(s['user_id'],now,a['approval_id']));execute("UPDATE phone_call_actions SET status='approved',approved_by=?,approved_at=?,updated_at=? WHERE id=?",(s['user_id'],now,now,aid));log(s['user_id'],'phone_call_approved','phone_call_action',aid,'Phone call approved by human');return RedirectResponse('/phone-sales',303)
@router.post('/phone-sales/{aid}/execute')
async def execute_call(aid:int,r:Request):
 s=sess(r);d=form(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 a=one('SELECT a.*,p.status approval_status FROM phone_call_actions a LEFT JOIN approvals p ON p.id=a.approval_id WHERE a.id=?',(aid,))
 if not a or a['status']!='approved' or a.get('approval_status')!='approved':raise HTTPException(403,'Approved human authorization required')
 if not RETELL_API_KEY or not RETELL_AGENT_ID or not RETELL_FROM_NUMBER:raise HTTPException(503,'Retell outbound configuration incomplete')
 payload={'from_number':RETELL_FROM_NUMBER,'to_number':a['phone'],'override_agent_id':RETELL_AGENT_ID,'metadata':{'opportunity_id':a['opportunity_id'],'phone_call_action_id':aid},'retell_llm_dynamic_variables':{'call_objective':a['objective']}}
 try:
  async with httpx.AsyncClient(timeout=15) as client:resp=await client.post('https://api.retellai.com/v2/create-phone-call',headers={'Authorization':'Bearer '+RETELL_API_KEY,'Content-Type':'application/json'},json=payload)
  if resp.status_code>=300:
   err=('Retell HTTP '+str(resp.status_code))[:500];execute("UPDATE phone_call_actions SET status='failed',last_error=?,updated_at=? WHERE id=?",(err,utcnow(),aid));raise HTTPException(502,err)
  data=resp.json();cid=str(data.get('call_id') or '')
  execute("UPDATE phone_call_actions SET status='started',provider_call_id=?,started_at=?,updated_at=? WHERE id=?",(cid,utcnow(),utcnow(),aid));log(s['user_id'],'phone_call_started','phone_call_action',aid,'Approved Retell call started');return RedirectResponse('/phone-sales',303)
 except HTTPException:raise
 except Exception as ex:
  execute("UPDATE phone_call_actions SET status='failed',last_error=?,updated_at=? WHERE id=?",(str(ex)[:500],utcnow(),aid));raise HTTPException(502,'Retell call request failed')
@router.get('/api/v7/phone-sales')
def api(r:Request):
 sess(r)
 with db() as c:items=c.execute('SELECT id,opportunity_id,contact_id,objective,status,approval_id,provider,provider_call_id,last_error,created_at,approved_at,started_at,updated_at FROM phone_call_actions ORDER BY updated_at DESC LIMIT 100').fetchall()
 return {'items':[dict(x) for x in items],'automatic_external_calls':False}
