import os,html,urllib.parse
from fastapi import FastAPI,Request,Response,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from pydantic import BaseModel
from app.storage import init_db,authenticate,create_session,get_session,delete_session,rows,one,execute,log,utcnow

app=FastAPI(title='Gulf Logistics AI',version='6.0.0-operational')
ADMIN_EMAIL=os.getenv('ADMIN_EMAIL','admin@afaaqtuwaiq.local')
ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD','ChangeMe-Now-2026!')
init_db(ADMIN_EMAIL,ADMIN_PASSWORD)

STYLE='''<style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}*{box-sizing:border-box}.wrap{max-width:1250px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}.top{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}.nav{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.nav a,.btn{display:inline-block;padding:10px 14px;border:0;border-radius:10px;background:#18384d;color:white;font-weight:700;text-decoration:none;cursor:pointer}.btn{background:#22c55e;color:#04130a}.danger{background:#7f1d1d;color:white}.muted{color:#9fb4c4}.good{color:#54e28b}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.kpi{background:#0b1d2b;padding:18px;border-radius:12px}.kpi b{font-size:26px;display:block;margin-top:8px}input,select,textarea{padding:12px;border:1px solid #36586e;border-radius:9px;margin:6px 0;background:#081925;color:white;width:100%}textarea{min-height:85px}.formgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}table{width:100%;border-collapse:collapse}th,td{text-align:right;padding:11px;border-bottom:1px solid #28475d;vertical-align:top}.scroll{overflow:auto}.pill{padding:4px 8px;border-radius:999px;background:#18384d}.notice{border-right:4px solid #22c55e}.warn{border-right:4px solid #f59e0b}</style>'''
def esc(x): return html.escape(str(x or ''))
def page(title,body): return '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title>'+STYLE+'<body><div class="wrap">'+body+'</div></body></html>'
def current(r):
    s=get_session(r.cookies.get('gla_session'))
    if not s: raise HTTPException(401,'Authentication required')
    return s
def require(r):
    try:return current(r)
    except HTTPException:return None
def nav(): return '<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/accounts">العملاء</a><a href="/opportunities">الفرص</a><a href="/shipments">الشحنات</a><a href="/pipeline">Pipeline</a><a href="/approvals">الموافقات</a><a href="/activity">السجل</a><a href="/logout">خروج</a></div>'
def head(s,title): return '<div class="top"><div><h1>'+esc(title)+'</h1><div class="muted">Gulf Logistics AI · آفاق طويق</div></div><div><span class="good">● تشغيل فعلي</span><br><span class="muted">'+esc(s['email'])+'</span></div></div>'+nav()
def parse(raw): return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def redirect_login(): return RedirectResponse('/login',status_code=303)

@app.get('/api/v50/health')
def health(): return {'ok':True,'version':'6.0.0-operational','persistent_database':True,'external_actions':False}
@app.get('/')
def root(): return RedirectResponse('/dashboard')
@app.get('/login',response_class=HTMLResponse)
def login_page():
    b='<div class="top"><div><h1>Gulf Logistics AI</h1><div class="muted">منصة تشغيل آفاق طويق</div></div><span class="good">● Online</span></div><div class="card"><h2>تسجيل الدخول</h2><form method="post" action="/login"><label>البريد</label><input name="email" autocomplete="username"><label>كلمة المرور</label><input name="password" type="password" autocomplete="current-password"><button class="btn">دخول</button></form></div>'
    return HTMLResponse(page('تسجيل الدخول',b),headers={'Cache-Control':'no-store'})
@app.post('/login')
async def login_form(r:Request):
    d=parse(await r.body()); u=authenticate(d.get('email',''),d.get('password',''))
    if not u:return HTMLResponse(page('خطأ','<div class="card"><h2>بيانات الدخول غير صحيحة</h2><a class="btn" href="/login">عودة</a></div>'),401)
    sid,csrf,exp=create_session(u['id'],12); resp=RedirectResponse('/dashboard',303); secure=os.getenv('BROWSER_COOKIE_SECURE','1')=='1'; resp.set_cookie('gla_session',sid,httponly=True,secure=secure,samesite='lax',max_age=43200); log(u['id'],'login',summary='Browser login'); return resp
@app.get('/logout')
def logout(r:Request):
    sid=r.cookies.get('gla_session'); s=get_session(sid)
    if s: log(s['user_id'],'logout',summary='Browser logout')
    if sid: delete_session(sid)
    resp=RedirectResponse('/login'); resp.delete_cookie('gla_session'); return resp

@app.get('/dashboard',response_class=HTMLResponse)
def dashboard(r:Request):
    s=require(r)
    if not s:return redirect_login()
    a=one('SELECT COUNT(*) n FROM accounts')['n']; o=one('SELECT COUNT(*) n FROM opportunities')['n']; q=one("SELECT COUNT(*) n FROM opportunities WHERE stage IN ('qualified','proposal','won')")['n']; sh=one('SELECT COUNT(*) n FROM shipments')['n']; pipe=one("SELECT COALESCE(SUM(estimated_value),0) v FROM opportunities WHERE stage NOT IN ('lost','won')")['v']; rev=one('SELECT COALESCE(SUM(revenue),0) v FROM shipments')['v']
    b=head(s,'لوحة التشغيل')+f'<div class="grid"><div class="kpi">العملاء<b>{a}</b></div><div class="kpi">الفرص<b>{o}</b></div><div class="kpi">المؤهلة<b>{q}</b></div><div class="kpi">الشحنات<b>{sh}</b></div><div class="kpi">Pipeline<b>{pipe:,.0f} SAR</b></div><div class="kpi">إيراد مسجل<b>{rev:,.0f} SAR</b></div></div><div class="card notice"><h3>النظام الآن يستخدم قاعدة بيانات فعلية</h3><p>أضف العملاء والفرص والشحنات من الصفحات أعلاه. البيانات ليست أمثلة ثابتة.</p></div><div class="card warn"><b>الإجراءات الخارجية متوقفة.</b> أي إرسال أو تواصل خارجي يجب أن يمر عبر موافقة بشرية قبل ربط مزود إرسال.</div>'
    return HTMLResponse(page('لوحة التشغيل',b),headers={'Cache-Control':'no-store'})

@app.get('/accounts',response_class=HTMLResponse)
def accounts(r:Request):
    s=require(r)
    if not s:return redirect_login()
    data=rows('SELECT * FROM accounts ORDER BY id DESC')
    form='<div class="card"><h2>إضافة عميل/شركة</h2><form method="post" action="/accounts"><div class="formgrid"><input name="name" placeholder="اسم الشركة" required><input name="country" placeholder="الدولة"><input name="domain" placeholder="الموقع/النطاق"><select name="status"><option value="lead">Lead</option><option value="qualified">Qualified</option><option value="customer">Customer</option></select></div><textarea name="notes" placeholder="ملاحظات"></textarea><button class="btn">حفظ الشركة</button></form></div>'
    trs=''.join(f'<tr><td>{x["id"]}</td><td>{esc(x["name"])}</td><td>{esc(x["country"])}</td><td>{esc(x["domain"])}</td><td><span class="pill">{esc(x["status"])}</span></td><td>{esc(x["notes"])}</td></tr>' for x in data)
    return HTMLResponse(page('العملاء',head(s,'العملاء والحسابات')+form+'<div class="card scroll"><table><tr><th>#</th><th>الشركة</th><th>الدولة</th><th>النطاق</th><th>الحالة</th><th>ملاحظات</th></tr>'+trs+'</table></div>'),headers={'Cache-Control':'no-store'})
@app.post('/accounts')
async def add_account(r:Request):
    s=require(r)
    if not s:return redirect_login()
    d=parse(await r.body()); now=utcnow(); iid=execute('INSERT INTO accounts(name,country,domain,status,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(d.get('name','').strip(),d.get('country',''),d.get('domain',''),d.get('status','lead'),d.get('notes',''),now,now)); log(s['user_id'],'create','account',iid,d.get('name','')); return RedirectResponse('/accounts',303)

@app.get('/opportunities',response_class=HTMLResponse)
def opportunities(r:Request):
    s=require(r)
    if not s:return redirect_login()
    data=rows('SELECT * FROM opportunities ORDER BY score DESC,id DESC'); ac=rows('SELECT id,name FROM accounts ORDER BY name'); opts='<option value="">بدون ربط</option>'+''.join(f'<option value="{x["id"]}">{esc(x["name"])}</option>' for x in ac)
    form='<div class="card"><h2>تسجيل فرصة حقيقية</h2><form method="post" action="/opportunities"><div class="formgrid"><select name="account_id">'+opts+'</select><input name="company_name" placeholder="اسم الشركة" required><input name="source_url" placeholder="رابط المصدر العام"><input name="score" type="number" min="0" max="100" value="50"><select name="stage"><option value="new">New</option><option value="research">Research</option><option value="qualified">Qualified</option><option value="proposal">Proposal</option><option value="won">Won</option><option value="lost">Lost</option></select><input name="estimated_value" type="number" step="0.01" placeholder="القيمة المتوقعة SAR"></div><textarea name="signal" placeholder="إشارة الشراء / المشكلة العامة التي ظهرت"></textarea><button class="btn">حفظ الفرصة</button></form></div>'
    trs=''.join(f'<tr><td>{x["id"]}</td><td>{esc(x["company_name"])}</td><td>{esc(x["signal"])}</td><td>{x["score"]}</td><td>{esc(x["stage"])}</td><td>{x["estimated_value"]:,.0f} {esc(x["currency"])}</td><td>{("<a class=\"btn\" target=\"_blank\" href=\""+esc(x["source_url"])+"\">المصدر</a>") if x["source_url"] else ""}</td></tr>' for x in data)
    return HTMLResponse(page('الفرص',head(s,'الفرص')+form+'<div class="card scroll"><table><tr><th>#</th><th>الشركة</th><th>الإشارة</th><th>Score</th><th>المرحلة</th><th>القيمة</th><th>المصدر</th></tr>'+trs+'</table></div>'),headers={'Cache-Control':'no-store'})
@app.post('/opportunities')
async def add_opportunity(r:Request):
    s=require(r)
    if not s:return redirect_login()
    d=parse(await r.body()); now=utcnow(); aid=int(d['account_id']) if d.get('account_id') else None; score=max(0,min(100,int(d.get('score') or 0))); val=float(d.get('estimated_value') or 0); iid=execute('INSERT INTO opportunities(account_id,company_name,source_url,signal,score,stage,estimated_value,currency,owner,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(aid,d.get('company_name',''),d.get('source_url',''),d.get('signal',''),score,d.get('stage','new'),val,'SAR',s['email'],now,now)); log(s['user_id'],'create','opportunity',iid,d.get('company_name','')); return RedirectResponse('/opportunities',303)

@app.get('/shipments',response_class=HTMLResponse)
def shipments(r:Request):
    s=require(r)
    if not s:return redirect_login()
    data=rows('SELECT s.*,a.name account_name FROM shipments s LEFT JOIN accounts a ON a.id=s.account_id ORDER BY s.id DESC'); ac=rows('SELECT id,name FROM accounts ORDER BY name'); opts='<option value="">بدون عميل</option>'+''.join(f'<option value="{x["id"]}">{esc(x["name"])}</option>' for x in ac)
    form='<div class="card"><h2>إضافة شحنة</h2><form method="post" action="/shipments"><div class="formgrid"><select name="account_id">'+opts+'</select><input name="reference" placeholder="رقم المرجع" required><select name="service_type"><option>Customs Clearance</option><option>Transport</option><option>Shipping</option><option>Warehousing</option><option>Door to Door</option></select><input name="origin" placeholder="المنشأ"><input name="destination" placeholder="الوجهة"><select name="status"><option value="new">New</option><option value="customs">Customs</option><option value="in_transit">In transit</option><option value="delivered">Delivered</option></select><input name="revenue" type="number" step="0.01" placeholder="الإيراد"><input name="cost" type="number" step="0.01" placeholder="التكلفة"></div><button class="btn">حفظ الشحنة</button></form></div>'
    trs=''.join(f'<tr><td>{esc(x["reference"])}</td><td>{esc(x["account_name"])}</td><td>{esc(x["service_type"])}</td><td>{esc(x["origin"])}</td><td>{esc(x["destination"])}</td><td>{esc(x["status"])}</td><td>{x["revenue"]:,.0f}</td><td>{x["cost"]:,.0f}</td></tr>' for x in data)
    return HTMLResponse(page('الشحنات',head(s,'الشحنات والعمليات')+form+'<div class="card scroll"><table><tr><th>المرجع</th><th>العميل</th><th>الخدمة</th><th>المنشأ</th><th>الوجهة</th><th>الحالة</th><th>الإيراد</th><th>التكلفة</th></tr>'+trs+'</table></div>'),headers={'Cache-Control':'no-store'})
@app.post('/shipments')
async def add_shipment(r:Request):
    s=require(r)
    if not s:return redirect_login()
    d=parse(await r.body()); now=utcnow(); aid=int(d['account_id']) if d.get('account_id') else None
    try:iid=execute('INSERT INTO shipments(account_id,reference,service_type,origin,destination,status,revenue,cost,currency,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(aid,d.get('reference',''),d.get('service_type',''),d.get('origin',''),d.get('destination',''),d.get('status','new'),float(d.get('revenue') or 0),float(d.get('cost') or 0),'SAR',now,now))
    except Exception:return HTMLResponse(page('خطأ','<div class="card">رقم المرجع مستخدم مسبقًا. <a class="btn" href="/shipments">عودة</a></div>'),400)
    log(s['user_id'],'create','shipment',iid,d.get('reference','')); return RedirectResponse('/shipments',303)

@app.get('/pipeline',response_class=HTMLResponse)
def pipeline(r:Request):
    s=require(r)
    if not s:return redirect_login()
    data=rows("SELECT stage,COUNT(*) n,COALESCE(SUM(estimated_value),0) value FROM opportunities GROUP BY stage ORDER BY value DESC"); trs=''.join(f'<tr><td>{esc(x["stage"])}</td><td>{x["n"]}</td><td>{x["value"]:,.0f} SAR</td></tr>' for x in data); return HTMLResponse(page('Pipeline',head(s,'Pipeline والإيرادات')+'<div class="card scroll"><table><tr><th>المرحلة</th><th>العدد</th><th>القيمة</th></tr>'+trs+'</table></div>'),headers={'Cache-Control':'no-store'})
@app.get('/approvals',response_class=HTMLResponse)
def approvals(r:Request):
    s=require(r)
    if not s:return redirect_login()
    data=rows('SELECT * FROM approvals ORDER BY id DESC'); trs=''.join(f'<tr><td>{x["id"]}</td><td>{esc(x["kind"])}</td><td>{esc(x["entity_type"])}</td><td>{x["entity_id"]}</td><td>{esc(x["status"])}</td><td>{esc(x["notes"])}</td></tr>' for x in data); return HTMLResponse(page('الموافقات',head(s,'الموافقات البشرية')+'<div class="card warn">لا يوجد إرسال خارجي مباشر. هذه الصفحة هي بوابة الحوكمة قبل ربط أي مزود تواصل.</div><div class="card scroll"><table><tr><th>#</th><th>النوع</th><th>الكيان</th><th>ID</th><th>الحالة</th><th>ملاحظات</th></tr>'+trs+'</table></div>'),headers={'Cache-Control':'no-store'})
@app.get('/activity',response_class=HTMLResponse)
def activity(r:Request):
    s=require(r)
    if not s:return redirect_login()
    data=rows('SELECT * FROM activity ORDER BY id DESC LIMIT 200'); trs=''.join(f'<tr><td>{esc(x["created_at"])}</td><td>{esc(x["action"])}</td><td>{esc(x["entity_type"])}</td><td>{esc(x["summary"])}</td></tr>' for x in data); return HTMLResponse(page('السجل',head(s,'سجل النشاط')+'<div class="card scroll"><table><tr><th>الوقت</th><th>الإجراء</th><th>النوع</th><th>الوصف</th></tr>'+trs+'</table></div>'),headers={'Cache-Control':'no-store'})

@app.get('/api/v6/me')
def me(r:Request):
    s=current(r); return {'email':s['email'],'name':s['name'],'workspace':'آفاق طويق','role':s['role']}
@app.get('/api/v6/accounts')
def api_accounts(r:Request): current(r); return rows('SELECT * FROM accounts ORDER BY id DESC')
@app.get('/api/v6/opportunities')
def api_opps(r:Request): current(r); return rows('SELECT * FROM opportunities ORDER BY score DESC,id DESC')
@app.get('/api/v6/shipments')
def api_shipments(r:Request): current(r); return rows('SELECT * FROM shipments ORDER BY id DESC')
