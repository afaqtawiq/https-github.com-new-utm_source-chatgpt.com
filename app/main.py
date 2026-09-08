import os,secrets,urllib.parse
from fastapi import FastAPI,Request,Response,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from pydantic import BaseModel
app=FastAPI(title='Gulf Logistics AI',version='5.0.2-demo-stable')
EMAIL='demo@afaaqtuwaiq.local'; PASSWORD='Demo@Tuwaiq2026!'; SESS={}
OPPS=[{'company':'شركة الخليج للتجارة','signal':'تبحث عن شريك تخليص ونقل داخل السعودية','score':92,'country':'Saudi Arabia','stage':'Qualified'},{'company':'مصنع الرواد','signal':'توسع خليجي وحاجة لتخزين ونقل','score':84,'country':'UAE','stage':'Research'},{'company':'متجر نمو','signal':'شحنات متكررة وخدمة باب إلى باب','score':78,'country':'Saudi Arabia','stage':'New'}]
SHIP=[{'reference':'AT-24091','service':'Door to Door','origin':'Jeddah','destination':'Riyadh','status':'In transit'},{'reference':'AT-24092','service':'Customs Clearance','origin':'King Abdulaziz Port','destination':'Dammam','status':'Customs review'},{'reference':'AT-24093','service':'Transport','origin':'Al Batha','destination':'Riyadh','status':'Delivered'}]
ACCTS=[{'name':'شركة الخليج للتجارة','country':'Saudi Arabia','status':'Active lead'},{'name':'مصنع الرواد','country':'UAE','status':'Research'},{'name':'متجر نمو','country':'Saudi Arabia','status':'Qualified'}]
class Login(BaseModel): email:str; password:str
STYLE='''<style>body{font-family:Arial;background:#07131f;color:#fff;margin:0}*{box-sizing:border-box}.wrap{max-width:1180px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}.top{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav a,.btn{display:inline-block;padding:11px 14px;border:0;border-radius:10px;background:#18384d;color:#fff;font-weight:700;text-decoration:none;cursor:pointer}.btn{background:#22c55e;color:#04130a}.muted{color:#9fb4c4}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.kpi{background:#0b1d2b;padding:18px;border-radius:12px}.kpi b{font-size:28px;display:block;margin-top:8px}input{display:block;padding:13px;border:0;border-radius:9px;margin:10px 0;width:min(360px,100%)}table{width:100%;border-collapse:collapse}th,td{text-align:right;padding:12px;border-bottom:1px solid #28475d}.good{color:#54e28b}.err{color:#ff7b7b}</style>'''
def page(title,body): return '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+'</title>'+STYLE+'<body><div class="wrap">'+body+'</div></body></html>'
def auth(r:Request):
    sid=r.cookies.get('gla_session')
    if sid not in SESS: raise HTTPException(401,'Authentication required')
    return sid
def nav(): return '<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/view/opportunities">الفرص</a><a href="/view/accounts">العملاء</a><a href="/view/shipments">الشحنات</a><a href="/view/revenue">الإيرادات</a><a href="/view/automation">الأتمتة</a><a href="/view/security">الأمن</a></div>'
def table(rows,cols):
    h='<div class="card"><table><thead><tr>'+''.join('<th>'+label+'</th>' for key,label in cols)+'</tr></thead><tbody>'
    for row in rows: h+='<tr>'+''.join('<td>'+str(row.get(key,''))+'</td>' for key,label in cols)+'</tr>'
    return h+'</tbody></table></div>'
@app.get('/')
def root(): return RedirectResponse('/static/app.html?v=502')
@app.get('/api/v50/health')
def health(): return {'ok':True,'version':'5.0.2-demo-stable','browser_cookie_auth':True,'external_actions':False}
@app.post('/api/v30/browser-login')
def login(x:Login,response:Response):
    if x.email!=EMAIL or x.password!=PASSWORD: raise HTTPException(401,'Invalid credentials')
    sid=secrets.token_urlsafe(24); SESS[sid]=True; secure=os.getenv('BROWSER_COOKIE_SECURE','1')=='1'
    response.set_cookie('gla_session',sid,httponly=True,secure=secure,samesite='lax',max_age=43200)
    return {'ok':True,'next':'/dashboard'}
@app.post('/login-form')
async def login_form(request:Request):
    raw=(await request.body()).decode(); data=urllib.parse.parse_qs(raw); email=data.get('email',[''])[0]; password=data.get('password',[''])[0]
    if email!=EMAIL or password!=PASSWORD: return HTMLResponse(page('دخول','<h1>بيانات الدخول غير صحيحة</h1><a class="btn" href="/static/app.html?v=502">عودة</a>'),status_code=401,headers={'Cache-Control':'no-store'})
    sid=secrets.token_urlsafe(24); SESS[sid]=True; secure=os.getenv('BROWSER_COOKIE_SECURE','1')=='1'
    resp=RedirectResponse('/dashboard',status_code=303); resp.set_cookie('gla_session',sid,httponly=True,secure=secure,samesite='lax',max_age=43200); return resp
@app.get('/api/v6/me')
def me(r:Request): auth(r); return {'email':EMAIL,'name':'Production Demo Admin','workspace':'آفاق طويق','role':'admin'}
@app.get('/api/v41/shell')
def shell(r:Request): auth(r); return {'workspace':{'name':'آفاق طويق'},'navigation':['home','opportunities','accounts','shipments','revenue','automation','security']}
@app.get('/api/demo/summary')
def summary(r:Request): auth(r); return {'opportunities':3,'qualified':2,'shipments':3,'revenue':22000,'pipeline':185000,'external_actions':False}
@app.get('/static/app.html',response_class=HTMLResponse)
def ui():
    body='<div class="top"><div><h1>Gulf Logistics AI</h1><div class="muted">آفاق طويق — النسخة التجريبية المستقرة v5.0.2</div></div><div class="good">● النظام يعمل</div></div><div class="card"><h2>تسجيل الدخول</h2><form method="post" action="/login-form"><label>البريد</label><input name="email" value="'+EMAIL+'"><label>كلمة المرور</label><input name="password" type="password" value="'+PASSWORD+'"><button class="btn" type="submit">دخول إلى لوحة التحكم</button></form><p class="muted">هذه نسخة Demo ولا تنفذ أي إرسال خارجي.</p></div>'
    return HTMLResponse(page('Gulf Logistics AI',body),headers={'Cache-Control':'no-store, no-cache, must-revalidate','Pragma':'no-cache'})
@app.get('/dashboard',response_class=HTMLResponse)
def dashboard(r:Request):
    try: auth(r)
    except HTTPException: return RedirectResponse('/static/app.html?v=502')
    body='<div class="top"><div><h1>آفاق طويق — لوحة التحكم</h1><div class="muted">Production Demo Admin</div></div><div class="good">● متصل</div></div>'+nav()+'<div class="grid"><div class="kpi">الفرص المكتشفة<b>3</b></div><div class="kpi">فرص مؤهلة<b>2</b></div><div class="kpi">الشحنات<b>3</b></div><div class="kpi">إيراد محجوز<b>22,000 SAR</b></div><div class="kpi">Pipeline<b>185,000 SAR</b></div></div><div class="card"><b>وضع الأمان:</b> <span class="good">External actions OFF</span><p class="muted">الواجهة تعمل من السيرفر مباشرة بدون اعتماد على JavaScript للتنقل.</p></div>'
    return HTMLResponse(page('لوحة التحكم',body),headers={'Cache-Control':'no-store'})
@app.get('/view/{section}',response_class=HTMLResponse)
def view(section:str,r:Request):
    try: auth(r)
    except HTTPException: return RedirectResponse('/static/app.html?v=502')
    head='<div class="top"><h1>Gulf Logistics AI</h1><span class="good">● متصل</span></div>'+nav()
    if section=='opportunities': body=head+'<h2>الفرص المكتشفة</h2>'+table(OPPS,[('company','الشركة'),('signal','إشارة الشراء'),('score','الدرجة'),('country','الدولة'),('stage','المرحلة')])
    elif section=='accounts': body=head+'<h2>العملاء والحسابات</h2>'+table(ACCTS,[('name','الحساب'),('country','الدولة'),('status','الحالة')])
    elif section=='shipments': body=head+'<h2>الشحنات</h2>'+table(SHIP,[('reference','المرجع'),('service','الخدمة'),('origin','المنشأ'),('destination','الوجهة'),('status','الحالة')])
    elif section=='revenue': body=head+'<h2>الإيرادات</h2><div class="grid"><div class="kpi">Booked<b>22,000 SAR</b></div><div class="kpi">Pipeline<b>185,000 SAR</b></div><div class="kpi">Weighted<b>101,500 SAR</b></div></div><div class="card muted">Demo data only</div>'
    elif section=='automation': body=head+'<div class="card"><h2>الأتمتة</h2><p>قواعد المتابعة جاهزة للعرض التجريبي.</p><p class="good">الإرسال الخارجي معطل ويحتاج موافقة بشرية.</p></div>'
    elif section=='security': body=head+'<div class="card"><h2>الأمن والحوكمة</h2><p class="good">HTTPS: مفعّل</p><p class="good">HttpOnly session: مفعّل</p><p class="good">External actions: OFF</p><p class="muted">هذه ليست شهادة امتثال.</p></div>'
    else: return RedirectResponse('/dashboard')
    return HTMLResponse(page(section,body),headers={'Cache-Control':'no-store'})
