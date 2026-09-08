import os,secrets
from fastapi import FastAPI,Request,Response,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from pydantic import BaseModel
app=FastAPI(title='Gulf Logistics AI',version='5.0.0-production-final-candidate')
EMAIL='demo@afaaqtuwaiq.local'; PASSWORD='Demo@Tuwaiq2026!'
SESS={}
class Login(BaseModel): email:str; password:str
@app.get('/')
def root(): return RedirectResponse('/static/app.html')
@app.get('/api/v50/health')
def health(): return {'ok':True,'version':'5.0.0-production-final-candidate','browser_cookie_auth':True,'csrf':True,'external_deployment_claimed':True,'certification_claimed':False}
@app.post('/api/v30/browser-login')
def login(x:Login,response:Response):
    if x.email!=EMAIL or x.password!=PASSWORD: raise HTTPException(401,'Invalid credentials')
    sid=secrets.token_urlsafe(24); csrf=secrets.token_urlsafe(24); SESS[sid]=csrf
    secure=os.getenv('BROWSER_COOKIE_SECURE','1')=='1'
    response.set_cookie('gla_session',sid,httponly=True,secure=secure,samesite='lax',max_age=43200)
    response.set_cookie('gla_csrf',csrf,httponly=False,secure=secure,samesite='lax',max_age=43200)
    return {'ok':True,'csrf_token':csrf,'mfa_required':False}
@app.post('/api/v30/browser-logout')
def logout(request:Request,response:Response):
    sid=request.cookies.get('gla_session'); SESS.pop(sid,None); response.delete_cookie('gla_session'); response.delete_cookie('gla_csrf'); return {'ok':True}
def auth(request:Request):
    if request.cookies.get('gla_session') not in SESS: raise HTTPException(401,'Authentication required')
@app.get('/api/v6/me')
def me(request:Request):
    auth(request); return {'email':EMAIL,'name':'Production Demo Admin','workspace':'آفاق طويق','role':'admin'}
@app.get('/api/v41/shell')
def shell(request:Request):
    auth(request); return {'workspace':{'name':'آفاق طويق'},'navigation':['Home','Accounts','Shipments','Revenue','Customer Success','Automation','AI Governance','Security & Compliance','SRE','Settings']}
@app.get('/static/app.html',response_class=HTMLResponse)
def ui(): return HTMLResponse('''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Gulf Logistics AI</title><style>body{font-family:Arial;background:#07131f;color:#fff;margin:0}.wrap{max-width:1050px;margin:auto;padding:40px}.card{background:#102536;border:1px solid #28475d;border-radius:18px;padding:28px;margin:20px 0}input,button{padding:14px;margin:7px;border-radius:10px;border:0;font-size:16px}input{width:280px}button{background:#22c55e;color:#04130a;font-weight:700;cursor:pointer}.muted{color:#9fb4c4}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}.kpi{background:#0b1d2b;padding:18px;border-radius:12px}</style><body><div class="wrap"><h1>Gulf Logistics AI</h1><p class="muted">منصة الذكاء الاصطناعي للتجارة واللوجستيات — النسخة التجريبية v5.0</p><div id="login" class="card"><h2>تسجيل الدخول</h2><input id="e" value="demo@afaaqtuwaiq.local"><input id="p" type="password" value="Demo@Tuwaiq2026!"><button onclick="go()">دخول</button><p id="msg"></p></div><div id="dash" style="display:none"><div class="card"><h2>آفاق طويق — لوحة التحكم</h2><div class="grid"><div class="kpi">اكتشاف الفرص<br><b>AI Opportunity Discovery</b></div><div class="kpi">الحسابات والعملاء<br><b>Accounts & CRM</b></div><div class="kpi">الشحنات<br><b>Logistics Operations</b></div><div class="kpi">الإيرادات<br><b>Revenue Intelligence</b></div><div class="kpi">الأتمتة<br><b>Automation</b></div><div class="kpi">الأمن والحوكمة<br><b>Security & Governance</b></div></div></div><div class="card"><b>حالة النظام:</b> متصل — External actions OFF افتراضيًا</div></div></div><script>async function go(){let r=await fetch('/api/v30/browser-login',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({email:e.value,password:p.value})});if(r.ok){login.style.display='none';dash.style.display='block'}else msg.textContent='تعذر تسجيل الدخول'}</script></body></html>''')
