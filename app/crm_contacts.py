import html,re,urllib.parse
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import db,get_session,one,execute,utcnow,log
router=APIRouter()
TEST_PHONE='+966502083821'
def e(v): return html.escape(str(v or ''))
def form(raw): return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode(),keep_blank_values=True).items()}
def session(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s: raise HTTPException(401)
 return s
def normalize(v):
 v=(v or '').strip()
 if v.startswith(' '): v='+'+v.lstrip()
 v=re.sub(r'[\s\-()]+','',v)
 if v.startswith('00'): v='+'+v[2:]
 return v
@router.get('/crm/contacts',response_class=HTMLResponse)
def contacts_page(r:Request):
 s=session(r)
 with db() as c:
  opps=c.execute("SELECT id,company_name,stage FROM opportunities WHERE stage NOT IN ('won','lost') ORDER BY updated_at DESC LIMIT 100").fetchall()
  contacts=c.execute('SELECT c.*,o.company_name FROM sales_contacts c JOIN opportunities o ON o.id=c.opportunity_id ORDER BY c.updated_at DESC LIMIT 100').fetchall()
 opts=''.join(f'<option value="{x["id"]}">{e(x["company_name"])} — {e(x["stage"])}</option>' for x in opps)
 rows=''
 for x in contacts:
  verify=''
  if not x['verified']:
   verify=f'''<form method="post" action="/crm/contacts/{x['id']}/verify"><input type="hidden" name="csrf" value="{e(s['csrf'])}"><label><input type="checkbox" name="confirmed" value="yes" required> أؤكد أن الرقم مملوك لي أو لدي إذن صريح باستخدامه للاتصال</label><button>توثيق الرقم</button></form>'''
  rows+=f'''<tr><td>{e(x['company_name'])}</td><td>{e(x['name'])}</td><td dir="ltr">{e(x['phone'])}</td><td>{'موثق' if x['verified'] else 'غير موثق'}</td><td>{verify}</td></tr>'''
 return HTMLResponse(f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><title>جهات اتصال CRM</title><style>body{{font-family:Arial;background:#f5f7fa;padding:28px}}.box{{background:white;padding:22px;border-radius:14px;margin-bottom:18px}}input,select,button{{padding:10px;margin:6px 0;width:100%;box-sizing:border-box}}table{{width:100%;border-collapse:collapse}}td,th{{padding:10px;border-bottom:1px solid #ddd}}label input[type=checkbox]{{width:auto}}.note{{background:#eef7ff;padding:12px;border-radius:10px}}</style><div class="box"><h1>جهات اتصال CRM</h1><div class="note">التسجيل لا يعني التوثيق. التوثيق خطوة مستقلة ويتطلب تأكيد الإذن باستخدام الرقم.</div><form method="post" action="/crm/contacts/create" accept-charset="UTF-8"><input type="hidden" name="csrf" value="{e(s['csrf'])}"><label>الفرصة</label><select name="opportunity_id" required>{opts}</select><label>اسم جهة الاتصال</label><input name="name" value="جهة اتصال اختبار" required><label>رقم الهاتف</label><input name="phone" type="tel" dir="ltr" value="{TEST_PHONE}" required><label>ملاحظات</label><input name="notes" value="رقم اختبار مصرح به للمكالمة التجريبية"><button>تسجيل الرقم في CRM</button></form></div><div class="box"><h2>الأرقام المسجلة</h2><table><tr><th>الشركة</th><th>الاسم</th><th>الهاتف</th><th>الحالة</th><th>الإجراء</th></tr>{rows or '<tr><td colspan="5">لا توجد جهات اتصال.</td></tr>'}</table></div></html>''')
@router.post('/crm/contacts/create')
async def create_contact(r:Request):
 s=session(r);d=form(await r.body())
 if d.get('csrf')!=s['csrf']: raise HTTPException(403)
 try: oid=int(d.get('opportunity_id','0'))
 except: raise HTTPException(400,'Opportunity required')
 if not one('SELECT id FROM opportunities WHERE id=?',(oid,)): raise HTTPException(404,'Opportunity not found')
 phone=normalize(d.get('phone'));name=(d.get('name') or '').strip();notes=(d.get('notes') or '').strip()
 if not re.fullmatch(r'\+[1-9]\d{7,14}',phone): raise HTTPException(400,'Phone must be valid E.164')
 if not name: raise HTTPException(400,'Contact name required')
 existing=one('SELECT id FROM sales_contacts WHERE opportunity_id=? AND phone=?',(oid,phone))
 if existing: return RedirectResponse('/crm/contacts',303)
 cid=execute('INSERT INTO sales_contacts(opportunity_id,name,phone,verified,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(oid,name,phone,0,notes,utcnow(),utcnow()))
 log(s['user_id'],'crm_contact_created','sales_contact',cid,'Phone contact registered; verification pending')
 return RedirectResponse('/crm/contacts',303)
@router.post('/crm/contacts/{cid}/verify')
async def verify_contact(cid:int,r:Request):
 s=session(r);d=form(await r.body())
 if d.get('csrf')!=s['csrf']: raise HTTPException(403)
 if d.get('confirmed')!='yes': raise HTTPException(400,'Explicit authorization confirmation required')
 c=one('SELECT * FROM sales_contacts WHERE id=?',(cid,))
 if not c: raise HTTPException(404)
 note=' | Phone authorization explicitly confirmed by CRM user '+str(s['user_id'])
 execute("UPDATE sales_contacts SET verified=1,notes=COALESCE(notes,'') || ?,updated_at=? WHERE id=?",(note,utcnow(),cid))
 log(s['user_id'],'crm_phone_verified','sales_contact',cid,'Phone authorization explicitly confirmed; contact marked verified')
 return RedirectResponse('/crm/contacts',303)
