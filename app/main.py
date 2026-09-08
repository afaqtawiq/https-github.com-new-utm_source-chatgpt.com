import os,html,urllib.parse
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import init_db,authenticate,create_session,get_session,delete_session,rows,one,execute,log,utcnow
from app.discovery import fetch_public
from app.intelligence import analyze

app=FastAPI(title='Gulf Logistics AI',version='7.1.0-shared-db')
ADMIN_EMAIL=os.getenv('ADMIN_EMAIL','admin@afaaqtuwaiq.local'); ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD','ChangeMe-Now-2026!')
init_db(ADMIN_EMAIL,ADMIN_PASSWORD)
STYLE='''<style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}*{box-sizing:border-box}.wrap{max-width:1250px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}.top{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}.nav{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.nav a,.btn{display:inline-block;padding:10px 14px;border:0;border-radius:10px;background:#18384d;color:white;font-weight:700;text-decoration:none;cursor:pointer}.btn{background:#22c55e;color:#04130a}.muted{color:#9fb4c4}.good{color:#54e28b}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.kpi{background:#0b1d2b;padding:18px;border-radius:12px}.kpi b{font-size:26px;display:block;margin-top:8px}input,select,textarea{padding:12px;border:1px solid #36586e;border-radius:9px;margin:6px 0;background:#081925;color:white;width:100%}textarea{min-height:85px}.formgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}table{width:100%;border-collapse:collapse}th,td{text-align:right;padding:11px;border-bottom:1px solid #28475d;vertical-align:top}.scroll{overflow:auto}.pill{padding:4px 8px;border-radius:999px;background:#18384d}.notice{border-right:4px solid #22c55e}.warn{border-right:4px solid #f59e0b}</style>'''
def esc(x): return html.escape(str(x or ''))
def page(t,b): return '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(t)+'</title>'+STYLE+'<body><div class="wrap">'+b+'</div></body></html>'
def current(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s: raise HTTPException(401)
 return s
def require(r):
 try:return current(r)
 except:return None
def nav(): return '<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/discovery">الاكتشاف</a><a href="/intelligence">الذكاء</a><a href="/accounts">العملاء</a><a href="/opportunities">الفرص</a><a href="/shipments">الشحنات</a><a href="/pipeline">Pipeline</a><a href="/approvals">الموافقات</a><a href="/activity">السجل</a><a href="/logout">خروج</a></div>'
def head(s,t): return '<div class="top"><div><h1>'+esc(t)+'</h1><div class="muted">Gulf Logistics AI · آفاق طويق</div></div><div><span class="good">● PostgreSQL مشترك</span><br><span class="muted">'+esc(s['email'])+'</span></div></div>'+nav()
def parse(raw): return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def rl(): return RedirectResponse('/login',303)
@app.get('/api/v50/health')
def health(): return {'ok':True,'version':'7.1.0-shared-db','database':'postgresql','shared_storage':True,'external_actions':False}
@app.get('/')
def root(): return RedirectResponse('/dashboard')
@app.get('/login',response_class=HTMLResponse)
def login_page(): return HTMLResponse(page('دخول','<div class="card"><h1>Gulf Logistics AI</h1><form method="post" action="/login"><input name="email" placeholder="البريد"><input name="password" type="password" placeholder="كلمة المرور"><button class="btn">دخول</button></form></div>'))
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
 a=one('SELECT COUNT(*) n FROM accounts')['n'];o=one('SELECT COUNT(*) n FROM opportunities')['n'];sig=one('SELECT COUNT(*) n FROM discovered_signals')['n'];src=one('SELECT COUNT(*) n FROM source_watches WHERE enabled=1')['n'];pipe=one("SELECT COALESCE(SUM(estimated_value),0) v FROM opportunities WHERE stage NOT IN ('lost','won')")['v']
 b=head(s,'لوحة التشغيل')+f'<div class="grid"><div class="kpi">العملاء<b>{a}</b></div><div class="kpi">الفرص<b>{o}</b></div><div class="kpi">إشارات مكتشفة<b>{sig}</b></div><div class="kpi">مصادر مراقبة<b>{src}</b></div><div class="kpi">Pipeline<b>{pipe:,.0f} SAR</b></div></div><div class="card notice"><b>قاعدة PostgreSQL مركزية مشتركة.</b> الويب والـDiscovery Worker يستخدمان نفس مخزن البيانات.</div><div class="card warn">التواصل الخارجي متوقف ويحتاج موافقة بشرية.</div>'
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
 data=rows('SELECT * FROM accounts ORDER BY id DESC');f='<div class="card"><form method="post" action="/accounts"><div class="formgrid"><input name="name" placeholder="الشركة" required><input name="country" placeholder="الدولة"><input name="domain" placeholder="النطاق"></div><textarea name="notes" placeholder="ملاحظات"></textarea><button class="btn">حفظ</button></form></div>';trs=''.join(f'<tr><td>{x["id"]}</td><td>{esc(x["name"])}</td><td>{esc(x["country"])}</td><td>{esc(x["domain"])}</td><td>{esc(x["status"])}</td></tr>' for x in data);return HTMLResponse(page('العملاء',head(s,'العملاء')+f+'<div class="card scroll"><table>'+trs+'</table></div>'))
@app.post('/accounts')
async def add_account(r:Request):
 s=require(r)
 if not s:return rl()
 d=parse(await r.body());n=utcnow();iid=execute('INSERT INTO accounts(name,country,domain,status,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(d.get('name',''),d.get('country',''),d.get('domain',''),'lead',d.get('notes',''),n,n));log(s['user_id'],'create','account',iid,d.get('name',''));return RedirectResponse('/accounts',303)
@app.get('/opportunities',response_class=HTMLResponse)
def opps(r:Request):
 s=require(r)
 if not s:return rl()
 data=rows('SELECT * FROM opportunities ORDER BY score DESC,id DESC');f='<div class="card"><form method="post" action="/opportunities"><div class="formgrid"><input name="company_name" placeholder="الشركة" required><input name="source_url" placeholder="رابط الدليل"><input name="score" type="number" min="0" max="100" value="50"><input name="estimated_value" type="number" placeholder="القيمة SAR"></div><textarea name="signal" placeholder="إشارة الشراء"></textarea><button class="btn">حفظ الفرصة</button></form></div>';trs=''.join(f'<tr><td>{x["score"]}</td><td>{esc(x["company_name"])}</td><td>{esc(x["signal"])}</td><td>{esc(x["stage"])}</td><td>{x["estimated_value"]:,.0f}</td></tr>' for x in data);return HTMLResponse(page('الفرص',head(s,'الفرص')+f+'<div class="card scroll"><table>'+trs+'</table></div>'))
@app.post('/opportunities')
async def add_opp(r:Request):
 s=require(r)
 if not s:return rl()
 d=parse(await r.body());n=utcnow();iid=execute('INSERT INTO opportunities(company_name,source_url,signal,score,stage,estimated_value,currency,owner,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(d.get('company_name',''),d.get('source_url',''),d.get('signal',''),max(0,min(100,int(d.get('score') or 0))),'new',float(d.get('estimated_value') or 0),'SAR',s['email'],n,n));log(s['user_id'],'create','opportunity',iid,d.get('company_name',''));return RedirectResponse('/opportunities',303)
@app.get('/shipments',response_class=HTMLResponse)
def shipments(r:Request):
 s=require(r)
 if not s:return rl()
 data=rows('SELECT * FROM shipments ORDER BY id DESC');return HTMLResponse(page('الشحنات',head(s,'الشحنات')+'<div class="card scroll"><table>'+''.join(f'<tr><td>{esc(x["reference"])}</td><td>{esc(x["service_type"])}</td><td>{esc(x["status"])}</td><td>{x["revenue"]:,.0f}</td></tr>' for x in data)+'</table></div>'))
@app.get('/pipeline',response_class=HTMLResponse)
def pipeline(r:Request):
 s=require(r)
 if not s:return rl()
 data=rows('SELECT stage,COUNT(*) n,COALESCE(SUM(estimated_value),0) value FROM opportunities GROUP BY stage ORDER BY value DESC');return HTMLResponse(page('Pipeline',head(s,'Pipeline')+'<div class="card scroll"><table>'+''.join(f'<tr><td>{esc(x["stage"])}</td><td>{x["n"]}</td><td>{x["value"]:,.0f} SAR</td></tr>' for x in data)+'</table></div>'))
@app.get('/approvals',response_class=HTMLResponse)
def approvals(r:Request):
 s=require(r)
 if not s:return rl()
 return HTMLResponse(page('الموافقات',head(s,'الموافقات البشرية')+'<div class="card warn">الإرسال الخارجي غير مفعّل. الموافقة البشرية إلزامية قبل أي تكامل تواصل.</div>'))
@app.get('/activity',response_class=HTMLResponse)
def activity(r:Request):
 s=require(r)
 if not s:return rl()
 data=rows('SELECT * FROM activity ORDER BY id DESC LIMIT 200');return HTMLResponse(page('السجل',head(s,'سجل النشاط')+'<div class="card scroll"><table>'+''.join(f'<tr><td>{esc(x["created_at"])}</td><td>{esc(x["action"])}</td><td>{esc(x["summary"])}</td></tr>' for x in data)+'</table></div>'))
@app.get('/api/v6/me')
def me(r:Request):
 s=current(r);return {'email':s['email'],'role':s['role']}
@app.get('/api/v6/opportunities')
def api_opps(r:Request):current(r);return rows('SELECT * FROM opportunities ORDER BY score DESC,id DESC')
