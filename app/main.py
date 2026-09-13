import os,html,urllib.parse
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import init_db,authenticate,create_session,get_session,delete_session,rows,one,execute,log,utcnow
from app.discovery import fetch_public
from app.intelligence import analyze

app=FastAPI(title='Gulf Logistics AI',version='7.2.0-sales-copilot')
ADMIN_EMAIL=os.getenv('ADMIN_EMAIL','admin@afaaqtuwaiq.local'); ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD','ChangeMe-Now-2026!')
init_db(ADMIN_EMAIL,ADMIN_PASSWORD)
STYLE='''<style>
:root{--navy:#07131f;--navy2:#0b2031;--panel:rgba(16,38,55,.92);--line:rgba(148,184,205,.18);--gold:#e7b64b;--gold2:#ffd978;--text:#f4f8fb;--muted:#a7bdcb;--green:#45d483}*{box-sizing:border-box}html{scroll-behavior:smooth}body{font-family:"Segoe UI",Tahoma,Arial,sans-serif;background:radial-gradient(circle at 85% 0,rgba(31,101,129,.28),transparent 32%),linear-gradient(145deg,#06111b 0%,#0a1c2b 55%,#07131f 100%);background-attachment:fixed;color:var(--text);margin:0;min-height:100vh;line-height:1.65}body:before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);background-size:32px 32px}.wrap{position:relative;max-width:1440px;margin:auto;padding:28px}.card{background:linear-gradient(145deg,rgba(18,45,64,.94),rgba(10,29,44,.96));border:1px solid var(--line);border-radius:20px;padding:22px;margin:16px 0;box-shadow:0 18px 50px rgba(0,0,0,.16);backdrop-filter:blur(10px)}.top{display:flex;justify-content:space-between;gap:18px;align-items:center;flex-wrap:wrap;padding:8px 2px 18px;border-bottom:1px solid var(--line)}.brand{display:flex;align-items:center;gap:14px}.brandmark{width:54px;height:54px;display:grid;place-items:center;border-radius:17px;background:linear-gradient(135deg,var(--gold2),var(--gold));color:#132331;font-weight:900;font-size:22px;box-shadow:0 10px 30px rgba(231,182,75,.24)}h1,h2,h3{margin-top:0;letter-spacing:-.02em}h1{font-size:clamp(26px,4vw,38px);margin-bottom:3px}.account{background:rgba(8,25,37,.58);border:1px solid var(--line);border-radius:14px;padding:10px 14px}.nav{display:flex;gap:8px;overflow-x:auto;padding:14px 2px 7px;margin:0 0 16px;scrollbar-width:thin}.nav a,.btn{display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:9px 14px;border:1px solid transparent;border-radius:12px;background:rgba(25,61,83,.72);color:white;font-weight:700;text-decoration:none;cursor:pointer;white-space:nowrap;transition:.2s ease}.nav a:hover{background:#234e68;border-color:rgba(255,255,255,.16);transform:translateY(-1px)}.nav a.primary{background:linear-gradient(135deg,var(--gold2),var(--gold));color:#132331}.nav a.logout{margin-right:auto;background:rgba(126,39,52,.35);color:#ffc5cc}.btn{background:linear-gradient(135deg,var(--gold2),var(--gold));color:#132331;box-shadow:0 8px 24px rgba(231,182,75,.14)}.btn:hover{filter:brightness(1.05);transform:translateY(-1px)}.muted{color:var(--muted)}.good{color:var(--green)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:14px}.kpi{position:relative;overflow:hidden;background:linear-gradient(145deg,rgba(18,46,65,.98),rgba(8,26,40,.96));padding:20px;border:1px solid var(--line);border-radius:18px;min-height:130px;box-shadow:0 12px 35px rgba(0,0,0,.14)}.kpi:after{content:"";position:absolute;width:85px;height:85px;border-radius:50%;background:rgba(231,182,75,.08);left:-26px;bottom:-30px}.kpi b{font-size:30px;display:block;margin-top:8px;color:var(--gold2);line-height:1.2}.hero{background:linear-gradient(120deg,rgba(20,58,79,.96),rgba(9,28,43,.97));border:1px solid rgba(231,182,75,.22);border-radius:24px;padding:28px;margin:16px 0 20px;box-shadow:0 20px 60px rgba(0,0,0,.2)}.quick{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.quick a{display:block;padding:17px;background:rgba(9,29,44,.64);border:1px solid var(--line);border-radius:15px;text-decoration:none;color:var(--text);font-weight:700}.quick a:hover{border-color:rgba(231,182,75,.55);background:rgba(23,58,78,.74)}input,select,textarea{padding:12px 14px;border:1px solid #36586e;border-radius:11px;margin:6px 0;background:rgba(6,23,35,.86);color:white;width:100%;outline:none}input:focus,select:focus,textarea:focus{border-color:var(--gold);box-shadow:0 0 0 3px rgba(231,182,75,.12)}textarea{min-height:90px}.formgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}table{width:100%;border-collapse:collapse}th,td{text-align:right;padding:12px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--gold2);font-size:14px;background:rgba(4,19,30,.35)}tr:hover td{background:rgba(255,255,255,.018)}.scroll{overflow:auto;border-radius:14px}.pill{display:inline-block;padding:4px 10px;border-radius:999px;background:#23465d;border:1px solid var(--line)}.notice{border-right:4px solid var(--green)}.warn{border-right:4px solid var(--gold)}.login-shell{min-height:calc(100vh - 56px);display:grid;place-items:center}.login-card{width:min(460px,100%);padding:34px;text-align:center}.login-card .brandmark{margin:0 auto 16px}.login-card form{text-align:right}.login-card .btn{width:100%;margin-top:10px}.eyebrow{color:var(--gold2);font-weight:800;font-size:13px;letter-spacing:.08em}@media(max-width:700px){.wrap{padding:16px}.top{align-items:flex-start}.account{width:100%}.nav{margin-inline:-16px;padding-inline:16px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.kpi{min-height:112px;padding:16px}.kpi b{font-size:24px}.hero{padding:20px}.card{padding:17px;border-radius:17px}}@media(max-width:430px){.grid{grid-template-columns:1fr}.brandmark{width:48px;height:48px}.login-card{padding:24px}}
</style>'''
def esc(x): return html.escape(str(x or ''))
def page(t,b): return '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(t)+'</title>'+STYLE+'<body><div class="wrap">'+b+'</div></body></html>'
def current(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s: raise HTTPException(401)
 return s
def require(r):
 try:return current(r)
 except:return None
def nav(): return '<div class="nav"><a class="primary" href="/dashboard">⌂ الرئيسية</a><a href="/commands">🎙 مساعد الأوامر</a><a href="/naqliat">🚚 شحنات نقليات</a><a href="/freight-workflow">عروض الشحن</a><a href="/shipping-agents">⚓ وكلاء الملاحة</a><a href="/saber">سابر</a><a href="/discovery">اكتشاف الفرص</a><a href="/intelligence-v2">الذكاء</a><a href="/sales-copilot">مساعد المبيعات</a><a href="/accounts">العملاء</a><a href="/drivers">السائقون</a><a href="/data-import">استيراد البيانات</a><a href="/opportunities">الفرص</a><a href="/shipments">الشحنات</a><a href="/pipeline">مسار المبيعات</a><a href="/approvals">الموافقات</a><a href="/activity">السجل</a><a class="logout" href="/logout">تسجيل الخروج</a></div>'
def head(s,t): return '<div class="top"><div class="brand"><div class="brandmark">آط</div><div><div class="eyebrow">AFAQ TUWAIQ OPERATIONS</div><h1>'+esc(t)+'</h1><div class="muted">من الحدود... إلى وجهة تجارتك</div></div></div><div class="account"><span class="good">● النظام متصل</span><br><span class="muted">'+esc(s['email'])+'</span></div></div>'+nav()
def parse(raw): return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def rl(): return RedirectResponse('/login',303)
@app.get('/api/v50/health')
def health(): return {'ok':True,'version':'7.2.0-sales-copilot','database':'postgresql','shared_storage':True,'sales_copilot':True,'external_actions':False}
@app.get('/')
def root(): return RedirectResponse('/dashboard')
@app.get('/login',response_class=HTMLResponse)
def login_page(): return HTMLResponse(page('دخول آفاق طويق','<div class="login-shell"><div class="card login-card"><div class="brandmark">آط</div><div class="eyebrow">AFAQ TUWAIQ</div><h1>منصة العمليات الذكية</h1><p class="muted">إدارة الشحنات والعملاء والسائقين من مكان واحد</p><form method="post" action="/login"><label>البريد الإلكتروني</label><input name="email" type="email" autocomplete="username" placeholder="name@company.com" required><label>كلمة المرور</label><input name="password" type="password" autocomplete="current-password" placeholder="••••••••" required><button class="btn">دخول آمن إلى المنصة</button></form></div></div>'))
@app.post('/login')
async def login(r:Request):
 d=parse(await r.body());u=authenticate(d.get('email',''),d.get('password',''))
 if not u:return HTMLResponse(page('خطأ','<div class="card">بيانات الدخول غير صحيحة</div>'),401)
 sid,csrf,exp=create_session(u['id']);resp=RedirectResponse('/dashboard',303);resp.set_cookie('gla_session',sid,httponly=True,secure=os.getenv('BROWSER_COOKIE_SECURE','1')=='1',samesite='lax',max_age=43200);log(u['id'],'login',summary='Browser login');return resp
@app.get('/logout')
def logout(r:Request):
 sid=r.cookies.get('gla_session');s=get_session(sid)
 if s:log(s['user_id'],'logout',summary='Browser logout')
 if sid:delete_session(sid)
 resp=RedirectResponse('/login');resp.delete_cookie('gla_session');return resp
@app.get('/dashboard',response_class=HTMLResponse)
def dashboard(r:Request):
 s=require(r)
 if not s:return rl()
 a=one('SELECT COUNT(*) n FROM accounts')['n'];o=one('SELECT COUNT(*) n FROM opportunities')['n'];d=one('SELECT COUNT(*) n FROM drivers')['n'];sig=one('SELECT COUNT(*) n FROM discovered_signals')['n'];src=one('SELECT COUNT(*) n FROM source_watches WHERE enabled=1')['n'];pipe=one("SELECT COALESCE(SUM(estimated_value),0) v FROM opportunities WHERE stage NOT IN ('lost','won')")['v']
 b=head(s,'لوحة التحكم')+f'<div class="hero"><div class="eyebrow">مركز قيادة العمليات</div><h2>صباح الخير، هذه صورة أعمال آفاق طويق الآن</h2><p class="muted">تابع الشحنات والفرص وابدأ أهم الإجراءات اليومية من لوحة واحدة.</p><div class="quick"><a href="/freight-workflow">🚛 إدارة عروض الشحن<br><span class="muted">التفاوض والإرسال للسائقين</span></a><a href="/shipping-agents">⚓ وكلاء الملاحة<br><span class="muted">البوالص والتأكيدات والمتابعة</span></a><a href="/commands">🎙 مساعد الأوامر<br><span class="muted">نفّذ مهامك بلغة واضحة</span></a><a href="/approvals">✓ مركز الموافقات<br><span class="muted">راجع قبل أي إجراء خارجي</span></a></div></div><div class="grid"><div class="kpi">العملاء<b>{a}</b><span class="muted">جهة مسجلة</span></div><div class="kpi"><a href="/drivers" style="color:inherit;text-decoration:none">السائقون<b>{d}</b><span class="muted">سائق في النظام</span></a></div><div class="kpi">الفرص<b>{o}</b><span class="muted">فرصة تجارية</span></div><div class="kpi">إشارات السوق<b>{sig}</b><span class="muted">إشارة مكتشفة</span></div><div class="kpi">مصادر المراقبة<b>{src}</b><span class="muted">مصدر نشط</span></div><div class="kpi">قيمة الفرص<b>{pipe:,.0f}</b><span class="muted">ريال سعودي</span></div></div><div class="card notice"><b>النظام التشغيلي جاهز.</b> البيانات محفوظة في قاعدة مركزية مشتركة، وجميع الإجراءات الخارجية تمر عبر موافقة بشرية.</div><div class="card warn"><b>قناة واتساب قيد التجهيز.</b> يمكنك حاليًا استخدام أزرار التواصل اليدوي حتى إضافة الرقم الجديد.</div>'
 return HTMLResponse(page('لوحة التشغيل',b))
@app.get('/discovery',response_class=HTMLResponse)
def discovery(r:Request):
 s=require(r)
 if not s:return rl()
 src=rows('SELECT * FROM source_watches ORDER BY id DESC'); sig=rows('SELECT * FROM discovered_signals ORDER BY score DESC,id DESC LIMIT 200')
 f='<div class="card"><h2>إضافة مصدر عام للمراقبة</h2><form method="post" action="/discovery/source"><div class="formgrid"><input name="name" placeholder="اسم المصدر" required><input name="url" placeholder="https://..." required></div><button class="btn">إضافة المصدر</button></form></div>'
 st=''.join(f'<tr><td>{esc(x["name"])}</td><td>{esc(x["url"])}</td><td>{esc(x["last_status"])}</td><td>{esc(x["last_checked_at"])}</td></tr>' for x in src); sg=''.join(f'<tr><td>{x["score"]}</td><td>{esc(x["company_name"])}</td><td>{esc(x["title"])}</td><td>{esc(x["matched_terms"])}</td><td><a class="btn" href="{esc(x["url"])}" target="_blank">المصدر</a></td></tr>' for x in sig)
 return HTMLResponse(page('الاكتشاف',head(s,'محرك اكتشاف الفرص')+f+'<div class="card scroll"><h3>المصادر</h3><table><tr><th>الاسم</th><th>URL</th><th>الحالة</th><th>آخر فحص</th></tr>'+st+'</table></div><div class="card scroll"><h3>الإشارات</h3><table><tr><th>Score</th><th>الجهة</th><th>العنوان</th><th>المطابقة</th><th>دليل</th></tr>'+sg+'</table></div>'))
@app.post('/discovery/source')
async def add_source(r:Request):
 s=require(r)
 if not s:return rl()
 d=parse(await r.body());url=d.get('url','').strip()
 try:
  result=fetch_public(url);iid=execute('INSERT INTO source_watches(name,url,source_type,enabled,last_status,last_checked_at,created_at) VALUES(?,?,?,?,?,?,?)',(d.get('name',''),url,'web',1,'validated',utcnow(),utcnow()));log(s['user_id'],'create','source_watch',iid,url)
 except Exception as e:return HTMLResponse(page('خطأ','<div class="card">تعذر اعتماد المصدر العام: '+esc(e)+'</div>'),400)
 return RedirectResponse('/discovery',303)
@app.get('/intelligence',response_class=HTMLResponse)
def intelligence(r:Request):
 s=require(r)
 if not s:return rl()
 data=rows('SELECT * FROM opportunities ORDER BY score DESC,id DESC');trs=''
 for x in data:
  z=analyze(x);trs+=f'<tr><td><span class="pill">{z["priority"]}</span></td><td>{esc(x["company_name"])}</td><td>{x["score"]}</td><td>{esc(z["intent"])}</td><td>{esc(", ".join(z["services"]))}</td><td>{esc(z["next_action"])}</td></tr>'
 return HTMLResponse(page('الذكاء',head(s,'Opportunity Intelligence')+'<div class="card scroll"><table><tr><th>الأولوية</th><th>الشركة</th><th>Score</th><th>نية الشراء</th><th>الخدمات</th><th>الإجراء التالي</th></tr>'+trs+'</table></div>'))
@app.get('/accounts',response_class=HTMLResponse)
def accounts(r:Request):
 s=require(r)
 if not s:return rl()
 data=rows('''SELECT a.id,a.name,a.country,a.domain,COALESCE(NULLIF(a.phone,''),c.phone) phone,COALESCE(NULLIF(a.email,''),c.email) email,a.status
 FROM accounts a LEFT JOIN LATERAL (SELECT phone,email FROM customer_directory d WHERE LOWER(d.company_name)=LOWER(a.name) ORDER BY d.id DESC LIMIT 1) c ON TRUE
 UNION ALL SELECT -d.id,d.company_name,COALESCE(NULLIF(d.city,''),'السعودية'),NULL,d.phone,d.email,'جهة اتصال'
 FROM customer_directory d WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name)=LOWER(d.company_name)) ORDER BY id DESC''');f='<div class="card"><form method="post" action="/accounts"><div class="formgrid"><input name="name" placeholder="اسم الشركة" required><input name="country" placeholder="الدولة"><input name="phone" placeholder="رقم الجوال" type="tel"><input name="email" placeholder="البريد الإلكتروني" type="email"><input name="domain" placeholder="النطاق"></div><textarea name="notes" placeholder="ملاحظات"></textarea><button class="btn">حفظ العميل</button></form></div>';trs=''.join(f'<tr><td>{x["id"]}</td><td>{esc(x["name"])}</td><td>{esc(x["country"])}</td><td dir="ltr">{esc(x.get("phone"))}</td><td dir="ltr">{esc(x.get("email"))}</td><td>{esc(x["domain"])}</td><td>{esc(x["status"])}</td></tr>' for x in data);return HTMLResponse(page('العملاء',head(s,'العملاء')+f+'<div class="card scroll"><table><tr><th>ID</th><th>اسم الشركة</th><th>البلد</th><th>الجوال</th><th>الإيميل</th><th>النطاق</th><th>الحالة</th></tr>'+trs+'</table></div>'))
@app.post('/accounts')
async def add_account(r:Request):
 s=require(r)
 if not s:return rl()
 d=parse(await r.body());now=utcnow();iid=execute('INSERT INTO accounts(name,country,domain,phone,email,status,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(d['name'],d.get('country'),d.get('domain'),d.get('phone'),d.get('email'),'lead',d.get('notes'),now,now));log(s['user_id'],'create','account',iid,d['name']);return RedirectResponse('/accounts',303)
@app.get('/opportunities',response_class=HTMLResponse)
def opportunities(r:Request):
 s=require(r)
 if not s:return rl()
 data=rows('SELECT * FROM opportunities ORDER BY id DESC');f='<div class="card"><form method="post" action="/opportunities"><div class="formgrid"><input name="company_name" placeholder="الشركة" required><input name="source_url" placeholder="رابط المصدر"><input name="score" type="number" min="0" max="100" value="50"><input name="estimated_value" type="number" min="0" value="0"></div><textarea name="signal" placeholder="إشارة الشراء"></textarea><button class="btn">إضافة فرصة</button></form></div>';trs=''.join(f'<tr><td>{x["id"]}</td><td>{esc(x["company_name"])}</td><td>{x["score"]}</td><td>{esc(x["stage"])}</td><td>{x["estimated_value"]:,.0f} {esc(x["currency"])}</td><td><a class="btn" href="/sales-copilot/{x["id"]}">Sales Copilot</a></td></tr>' for x in data);return HTMLResponse(page('الفرص',head(s,'الفرص')+f+'<div class="card scroll"><table><tr><th>ID</th><th>الشركة</th><th>Score</th><th>المرحلة</th><th>القيمة</th><th>مساعد البيع</th></tr>'+trs+'</table></div>'))
@app.post('/opportunities')
async def add_opportunity(r:Request):
 s=require(r)
 if not s:return rl()
 d=parse(await r.body());now=utcnow();iid=execute('INSERT INTO opportunities(company_name,source_url,signal,score,stage,estimated_value,currency,owner,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(d['company_name'],d.get('source_url'),d.get('signal'),int(d.get('score',50)),'new',float(d.get('estimated_value',0)),'SAR',s['email'],now,now));log(s['user_id'],'create','opportunity',iid,d['company_name']);return RedirectResponse('/opportunities',303)
@app.get('/shipments',response_class=HTMLResponse)
def shipments(r:Request):
 s=require(r)
 if not s:return rl()
 data=rows('SELECT * FROM shipments ORDER BY id DESC');f='<div class="card"><form method="post" action="/shipments"><div class="formgrid"><input name="reference" placeholder="المرجع" required><select name="service_type"><option>Customs Clearance</option><option>Transport</option><option>Shipping</option><option>Warehousing</option><option>Door to Door</option></select><input name="origin" placeholder="المنشأ"><input name="destination" placeholder="الوجهة"><input name="revenue" type="number" value="0"><input name="cost" type="number" value="0"></div><button class="btn">إضافة شحنة</button></form></div>';trs=''.join(f'<tr><td>{esc(x["reference"])}</td><td>{esc(x["service_type"])}</td><td>{esc(x["origin"])}</td><td>{esc(x["destination"])}</td><td>{esc(x["status"])}</td></tr>' for x in data);return HTMLResponse(page('الشحنات',head(s,'الشحنات')+f+'<div class="card scroll"><table>'+trs+'</table></div>'))
@app.post('/shipments')
async def add_shipment(r:Request):
 s=require(r)
 if not s:return rl()
 d=parse(await r.body());now=utcnow();iid=execute('INSERT INTO shipments(reference,service_type,origin,destination,status,revenue,cost,currency,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(d['reference'],d['service_type'],d.get('origin'),d.get('destination'),'new',float(d.get('revenue',0)),float(d.get('cost',0)),'SAR',now,now));log(s['user_id'],'create','shipment',iid,d['reference']);return RedirectResponse('/shipments',303)
@app.get('/pipeline',response_class=HTMLResponse)
def pipeline(r:Request):
 s=require(r)
 if not s:return rl()
 data=rows('SELECT stage,COUNT(*) n,COALESCE(SUM(estimated_value),0) value FROM opportunities GROUP BY stage ORDER BY stage');cards=''.join(f'<div class="kpi">{esc(x["stage"])}<b>{x["n"]}</b><span>{x["value"]:,.0f} SAR</span></div>' for x in data);return HTMLResponse(page('Pipeline',head(s,'Pipeline')+'<div class="grid">'+cards+'</div>'))
@app.get('/approvals',response_class=HTMLResponse)
def approvals(r:Request):
 s=require(r)
 if not s:return rl()
 data=rows('SELECT * FROM approvals ORDER BY id DESC');trs=''.join(f'<tr><td>{x["id"]}</td><td>{esc(x["kind"])}</td><td>{esc(x["entity_type"])} #{x["entity_id"]}</td><td>{esc(x["status"])}</td><td>{esc(x["notes"])}</td></tr>' for x in data);return HTMLResponse(page('الموافقات',head(s,'الموافقات البشرية')+'<div class="card warn">لا توجد إجراءات خارجية تلقائية.</div><div class="card scroll"><table>'+trs+'</table></div>'))
@app.get('/activity',response_class=HTMLResponse)
def activity(r:Request):
 s=require(r)
 if not s:return rl()
 data=rows('SELECT * FROM activity ORDER BY id DESC LIMIT 300');trs=''.join(f'<tr><td>{esc(x["created_at"])}</td><td>{esc(x["action"])}</td><td>{esc(x["entity_type"])}</td><td>{esc(x["entity_id"])}</td><td>{esc(x["summary"])}</td></tr>' for x in data);return HTMLResponse(page('السجل',head(s,'سجل النشاط')+'<div class="card scroll"><table>'+trs+'</table></div>'))
@app.get('/api/v7/me')
def me(r:Request):
 s=current(r);return {'email':s['email'],'name':s['name'],'role':s['role']}
@app.get('/api/v7/accounts')
def api_accounts(r:Request): current(r);return rows('SELECT * FROM accounts ORDER BY id DESC')
@app.get('/api/v7/opportunities')
def api_opps(r:Request): current(r);return rows('SELECT * FROM opportunities ORDER BY id DESC')
@app.get('/api/v7/shipments')
def api_shipments(r:Request): current(r);return rows('SELECT * FROM shipments ORDER BY id DESC')
