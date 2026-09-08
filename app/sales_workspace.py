import html,urllib.parse,datetime
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import get_session,rows,one,execute,log,utcnow
router=APIRouter()
def esc(v):return html.escape(str(v or ''))
def auth(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s
def parse(raw):return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def shell(b):return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}.w{max-width:1250px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:18px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}.btn{display:inline-block;padding:10px 14px;border:0;border-radius:9px;background:#22c55e;color:#04130a;text-decoration:none;font-weight:bold;cursor:pointer}input,select,textarea{width:100%;box-sizing:border-box;padding:10px;margin:5px 0;background:#081925;color:white;border:1px solid #36586e;border-radius:8px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #28475d;text-align:right}.muted{color:#9fb4c4}.nav a{color:white;margin-left:12px}</style><body><div class="w">'+b+'</div></body></html>')
def nav():return '<div class="nav"><a href="/sales-center">مركز المبيعات</a><a href="/sales-copilot">Sales Copilot</a><a href="/outbound">الرسائل</a><a href="/dashboard">الرئيسية</a></div>'
@router.get('/sales-workspace/{oid}')
def workspace(oid:int,request:Request):
 auth(request);o=one('SELECT * FROM opportunities WHERE id=?',(oid,));
 if not o:raise HTTPException(404)
 cs=rows('SELECT * FROM sales_contacts WHERE opportunity_id=? ORDER BY verified DESC,id DESC',(oid,));fs=rows('SELECT * FROM sales_followups WHERE opportunity_id=? ORDER BY due_at,id DESC',(oid,));out=one('SELECT * FROM sales_outcomes WHERE opportunity_id=?',(oid,));intel=one('SELECT * FROM opportunity_intelligence WHERE opportunity_id=?',(oid,))
 ctr=''.join('<tr><td>'+esc(x['name'])+'</td><td>'+esc(x['job_title'])+'</td><td>'+esc(x['email'])+'</td><td>'+('موثق' if x['verified'] else 'غير موثق')+'</td><td>'+('<a class="btn" target="_blank" rel="noopener" href="'+esc(x['source_url'])+'">المصدر</a>' if x.get('source_url') else '—')+'</td></tr>' for x in cs)
 ftr=''.join('<tr><td>'+esc(x['kind'])+'</td><td>'+esc(x['due_at'])+'</td><td>'+esc(x['status'])+'</td><td>'+esc(x['notes'])+'</td><td>'+('<form method="post" action="/sales-workspace/followup/'+str(x['id'])+'/done"><button class="btn">تم</button></form>' if x['status']=='open' else '✓')+'</td></tr>' for x in fs)
 b=nav()+'<h1>'+esc(o['company_name'])+'</h1><div class="grid"><div class="card"><b>المرحلة</b><h2>'+esc(o['stage'])+'</h2></div><div class="card"><b>Score</b><h2>'+str(o['score'])+'/100</h2></div><div class="card"><b>الخدمات</b><p>'+esc((intel or {}).get('services') or 'غير محددة')+'</p></div><div class="card"><b>النتيجة</b><p>'+esc((out or {}).get('outcome') or 'مفتوحة')+'</p></div></div>'
 b+='<div class="card"><h2>Decision Makers / جهات الاتصال</h2><p class="muted">لا تُدخل بيانات مخمنة. استخدم بيانات أعمال عامة موثقة ومصدرها.</p><form method="post" action="/sales-workspace/'+str(oid)+'/contact"><div class="grid"><input name="name" placeholder="الاسم"><input name="job_title" placeholder="المسمى الوظيفي"><input name="email" type="email" placeholder="بريد العمل"><input name="phone" placeholder="هاتف العمل"><input name="source_url" placeholder="رابط المصدر العام"></div><textarea name="notes" placeholder="ملاحظات"></textarea><label><input style="width:auto" type="checkbox" name="verified" value="1"> تم التحقق من المصدر</label><br><button class="btn">حفظ جهة الاتصال</button></form><table><tr><th>الاسم</th><th>المنصب</th><th>البريد</th><th>التحقق</th><th>المصدر</th></tr>'+ctr+'</table></div>'
 b+='<div class="card"><h2>المتابعات</h2><form method="post" action="/sales-workspace/'+str(oid)+'/followup"><div class="grid"><select name="kind"><option value="follow_up">متابعة</option><option value="call">مكالمة</option><option value="proposal_review">مراجعة عرض</option><option value="meeting">اجتماع</option></select><input type="datetime-local" name="due_at" required></div><textarea name="notes" placeholder="المهمة التالية"></textarea><button class="btn">إضافة متابعة</button></form><table><tr><th>النوع</th><th>الموعد</th><th>الحالة</th><th>الملاحظات</th><th></th></tr>'+ftr+'</table></div>'
 b+='<div class="card"><h2>إغلاق الصفقة</h2><form method="post" action="/sales-workspace/'+str(oid)+'/outcome"><div class="grid"><select name="outcome"><option value="won">Won — فازت آفاق طويق</option><option value="lost">Lost — لم تتم الصفقة</option></select><input name="realized_value" type="number" min="0" step="0.01" value="0"><select name="currency"><option>SAR</option><option>AED</option><option>USD</option></select></div><textarea name="reason" placeholder="سبب الفوز/الخسارة"></textarea><button class="btn">تسجيل النتيجة</button></form></div>'
 return shell(b)
@router.post('/sales-workspace/{oid}/contact')
async def contact(oid:int,request:Request):
 s=auth(request);d=parse(await request.body());now=utcnow();cid=execute('INSERT INTO sales_contacts(opportunity_id,name,job_title,email,phone,source_url,verified,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(oid,d.get('name'),d.get('job_title'),d.get('email'),d.get('phone'),d.get('source_url'),1 if d.get('verified')=='1' else 0,d.get('notes'),now,now));log(s['user_id'],'add_sales_contact','sales_contact',cid,'Public business contact recorded');return RedirectResponse('/sales-workspace/'+str(oid),303)
@router.post('/sales-workspace/{oid}/followup')
async def followup(oid:int,request:Request):
 s=auth(request);d=parse(await request.body());raw=d.get('due_at','');
 try:due=datetime.datetime.fromisoformat(raw).replace(tzinfo=datetime.timezone(datetime.timedelta(hours=3)))
 except:raise HTTPException(400,'Invalid due date')
 fid=execute('INSERT INTO sales_followups(opportunity_id,kind,due_at,status,notes,created_by,created_at) VALUES(?,?,?,?,?,?,?)',(oid,d.get('kind','follow_up'),due,'open',d.get('notes'),s['user_id'],utcnow()));log(s['user_id'],'schedule_followup','sales_followup',fid,'Sales follow-up scheduled');return RedirectResponse('/sales-workspace/'+str(oid),303)
@router.post('/sales-workspace/followup/{fid}/done')
def done(fid:int,request:Request):
 s=auth(request);f=one('SELECT * FROM sales_followups WHERE id=?',(fid,));
 if not f:raise HTTPException(404)
 execute('UPDATE sales_followups SET status=?,completed_at=? WHERE id=?',('done',utcnow(),fid));log(s['user_id'],'complete_followup','sales_followup',fid,'Follow-up completed');return RedirectResponse('/sales-workspace/'+str(f['opportunity_id']),303)
@router.post('/sales-workspace/{oid}/outcome')
async def outcome(oid:int,request:Request):
 s=auth(request);d=parse(await request.body());oc=d.get('outcome');
 if oc not in ('won','lost'):raise HTTPException(400)
 value=float(d.get('realized_value') or 0);cur=d.get('currency','SAR');now=utcnow();execute('INSERT INTO sales_outcomes(opportunity_id,outcome,reason,realized_value,currency,recorded_by,recorded_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET outcome=EXCLUDED.outcome,reason=EXCLUDED.reason,realized_value=EXCLUDED.realized_value,currency=EXCLUDED.currency,recorded_by=EXCLUDED.recorded_by,recorded_at=EXCLUDED.recorded_at',(oid,oc,d.get('reason'),value,cur,s['user_id'],now));execute('UPDATE opportunities SET stage=?,updated_at=? WHERE id=?',(oc,now,oid));log(s['user_id'],'record_sales_outcome','opportunity',oid,oc+' '+str(value)+' '+cur);return RedirectResponse('/sales-workspace/'+str(oid),303)
@router.get('/api/v7/followups')
def api(request:Request):
 auth(request);return {'overdue':rows("SELECT f.*,o.company_name FROM sales_followups f JOIN opportunities o ON o.id=f.opportunity_id WHERE f.status='open' AND f.due_at<NOW() ORDER BY f.due_at"),'upcoming':rows("SELECT f.*,o.company_name FROM sales_followups f JOIN opportunities o ON o.id=f.opportunity_id WHERE f.status='open' AND f.due_at>=NOW() ORDER BY f.due_at LIMIT 100")}
