import os,secrets
from fastapi import FastAPI,Request,Response,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from pydantic import BaseModel
app=FastAPI(title='Gulf Logistics AI',version='5.0.1-demo-functional')
EMAIL='demo@afaaqtuwaiq.local'; PASSWORD='Demo@Tuwaiq2026!'; SESS={}
OPPS=[{'id':1,'company':'شركة الخليج للتجارة','signal':'تبحث عن شريك تخليص ونقل داخل السعودية','score':92,'country':'Saudi Arabia','stage':'Qualified'},{'id':2,'company':'مصنع الرواد','signal':'توسع خليجي وحاجة لتخزين ونقل','score':84,'country':'UAE','stage':'Research'},{'id':3,'company':'متجر نمو','signal':'شحنات متكررة وخدمة باب إلى باب','score':78,'country':'Saudi Arabia','stage':'New'}]
SHIP=[{'reference':'AT-24091','service':'Door to Door','origin':'Jeddah','destination':'Riyadh','status':'In transit'},{'reference':'AT-24092','service':'Customs Clearance','origin':'King Abdulaziz Port','destination':'Dammam','status':'Customs review'},{'reference':'AT-24093','service':'Transport','origin':'Al Batha','destination':'Riyadh','status':'Delivered'}]
class Login(BaseModel): email:str; password:str
@app.get('/')
def root(): return RedirectResponse('/static/app.html')
@app.get('/api/v50/health')
def health(): return {'ok':True,'version':'5.0.1-demo-functional','browser_cookie_auth':True,'csrf':True,'external_actions':False}
@app.post('/api/v30/browser-login')
def login(x:Login,response:Response):
    if x.email!=EMAIL or x.password!=PASSWORD: raise HTTPException(401,'Invalid credentials')
    sid=secrets.token_urlsafe(24); csrf=secrets.token_urlsafe(24); SESS[sid]=csrf
    secure=os.getenv('BROWSER_COOKIE_SECURE','1')=='1'
    response.set_cookie('gla_session',sid,httponly=True,secure=secure,samesite='lax',max_age=43200)
    response.set_cookie('gla_csrf',csrf,secure=secure,samesite='lax',max_age=43200)
    return {'ok':True}
def auth(r:Request):
    if r.cookies.get('gla_session') not in SESS: raise HTTPException(401,'Authentication required')
@app.get('/api/v6/me')
def me(r:Request): auth(r); return {'email':EMAIL,'name':'Production Demo Admin','workspace':'آفاق طويق','role':'admin'}
@app.get('/api/v41/shell')
def shell(r:Request): auth(r); return {'workspace':{'name':'آفاق طويق'},'navigation':['home','opportunities','accounts','shipments','revenue','automation','security']}
@app.get('/api/demo/summary')
def summary(r:Request): auth(r); return {'opportunities':len(OPPS),'qualified':2,'shipments':len(SHIP),'revenue':22000,'pipeline':185000,'external_actions':False}
@app.get('/api/demo/opportunities')
def opportunities(r:Request): auth(r); return OPPS
@app.get('/api/demo/shipments')
def shipments(r:Request): auth(r); return SHIP
@app.get('/api/demo/accounts')
def accounts(r:Request): auth(r); return [{'name':'شركة الخليج للتجارة','country':'Saudi Arabia','status':'Active lead'},{'name':'مصنع الرواد','country':'UAE','status':'Research'},{'name':'متجر نمو','country':'Saudi Arabia','status':'Qualified'}]
@app.get('/api/demo/revenue')
def revenue(r:Request): auth(r); return {'currency':'SAR','booked':22000,'pipeline':185000,'weighted':101500,'note':'Demo data only'}
@app.get('/static/app.html',response_class=HTMLResponse)
def ui(): return HTMLResponse('''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Gulf Logistics AI</title><style>body{font-family:Arial;background:#07131f;color:#fff;margin:0}*{box-sizing:border-box}.wrap{max-width:1180px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}.top{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav button,.loginbtn{padding:11px 14px;border:0;border-radius:10px;background:#22c55e;color:#04130a;font-weight:700;cursor:pointer}.nav button{background:#18384d;color:#fff}.nav button.active{background:#22c55e;color:#04130a}.muted{color:#9fb4c4}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.kpi{background:#0b1d2b;padding:18px;border-radius:12px}.kpi b{font-size:28px;display:block;margin-top:8px}input{padding:13px;border:0;border-radius:9px;margin:6px;width:min(330px,100%)}table{width:100%;border-collapse:collapse}th,td{text-align:right;padding:12px;border-bottom:1px solid #28475d}.badge{padding:5px 9px;border-radius:999px;background:#18384d}.good{color:#54e28b}.warn{color:#ffd166}.err{color:#ff7b7b}</style><body><div class="wrap"><div class="top"><div><h1>Gulf Logistics AI</h1><div class="muted">آفاق طويق — منصة التجارة واللوجستيات الذكية</div></div><div id="health" class="muted">فحص النظام...</div></div><div id="loginBox" class="card"><h2>تسجيل الدخول</h2><input id="email" value="demo@afaaqtuwaiq.local"><input id="password" type="password" value="Demo@Tuwaiq2026!"><button class="loginbtn" id="loginBtn">دخول</button><div id="msg" class="err"></div></div><div id="appBox" style="display:none"><div class="card"><div class="top"><div id="who">...</div><div class="nav" id="nav"></div></div></div><div id="content"></div></div></div><script>
const q=s=>document.querySelector(s);let current='home';
async function api(u){let r=await fetch(u,{credentials:'same-origin'});if(!r.ok)throw new Error(r.status);return r.json()}
async function health(){try{let d=await (await fetch('/api/v50/health')).json();q('#health').innerHTML='<span class="good">● النظام يعمل</span> — '+d.version}catch(e){q('#health').innerHTML='<span class="err">● غير متصل</span>'}}
async function login(){q('#msg').textContent='';let r=await fetch('/api/v30/browser-login',{method:'POST',headers:{'content-type':'application/json'},credentials:'same-origin',body:JSON.stringify({email:q('#email').value,password:q('#password').value})});if(!r.ok){q('#msg').textContent='بيانات الدخول غير صحيحة';return}q('#loginBox').style.display='none';q('#appBox').style.display='block';let me=await api('/api/v6/me');q('#who').textContent=me.workspace+' — '+me.name;buildNav();show('home')}
function buildNav(){let items=[['home','الرئيسية'],['opportunities','الفرص'],['accounts','العملاء'],['shipments','الشحنات'],['revenue','الإيرادات'],['automation','الأتمتة'],['security','الأمن']];q('#nav').innerHTML=items.map(x=>`<button data-v="${x[0]}">${x[1]}</button>`).join('');q('#nav').onclick=e=>{if(e.target.dataset.v)show(e.target.dataset.v)}}
function table(rows,cols){return `<div class="card"><table><thead><tr>${cols.map(c=>`<th>${c[1]}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${cols.map(c=>`<td>${r[c[0]]??''}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}
async function show(v){current=v;document.querySelectorAll('#nav button').forEach(b=>b.classList.toggle('active',b.dataset.v===v));let c=q('#content');c.innerHTML='<div class="card muted">جارٍ التحميل...</div>';try{if(v==='home'){let d=await api('/api/demo/summary');c.innerHTML=`<div class="grid"><div class="kpi">الفرص المكتشفة<b>${d.opportunities}</b></div><div class="kpi">فرص مؤهلة<b>${d.qualified}</b></div><div class="kpi">الشحنات<b>${d.shipments}</b></div><div class="kpi">إيراد محجوز<b>${d.revenue.toLocaleString()} SAR</b></div><div class="kpi">Pipeline<b>${d.pipeline.toLocaleString()} SAR</b></div></div><div class="card"><b>وضع الأمان:</b> <span class="good">External actions OFF</span><p class="muted">هذه نسخة Demo تشغيلية ببيانات تجريبية، ولا ترسل أي تواصل خارجي.</p></div>`}else if(v==='opportunities'){let d=await api('/api/demo/opportunities');c.innerHTML=table(d,[['company','الشركة'],['signal','إشارة الشراء'],['score','الدرجة'],['country','الدولة'],['stage','المرحلة']])}else if(v==='accounts'){let d=await api('/api/demo/accounts');c.innerHTML=table(d,[['name','الحساب'],['country','الدولة'],['status','الحالة']])}else if(v==='shipments'){let d=await api('/api/demo/shipments');c.innerHTML=table(d,[['reference','المرجع'],['service','الخدمة'],['origin','المنشأ'],['destination','الوجهة'],['status','الحالة']])}else if(v==='revenue'){let d=await api('/api/demo/revenue');c.innerHTML=`<div class="grid"><div class="kpi">Booked<b>${d.booked.toLocaleString()} ${d.currency}</b></div><div class="kpi">Pipeline<b>${d.pipeline.toLocaleString()} ${d.currency}</b></div><div class="kpi">Weighted<b>${d.weighted.toLocaleString()} ${d.currency}</b></div></div><div class="card muted">${d.note}</div>`}else if(v==='automation'){c.innerHTML='<div class="card"><h2>الأتمتة</h2><p>قواعد المتابعة جاهزة للعرض التجريبي.</p><p class="good">الإرسال الخارجي معطل افتراضيًا ويحتاج موافقة بشرية.</p></div>'}else if(v==='security'){c.innerHTML='<div class="card"><h2>الأمن والحوكمة</h2><p class="good">HttpOnly session cookie: مفعّل</p><p class="good">HTTPS: مفعّل</p><p class="good">External actions: OFF</p><p class="muted">هذه النسخة ليست ادعاء امتثال أو شهادة أمنية.</p></div>'}}catch(e){c.innerHTML='<div class="card err">تعذر تحميل هذه الوحدة. حدّث الصفحة وحاول مجددًا.</div>'}}
q('#loginBtn').onclick=login;health();
</script></body></html>''')
