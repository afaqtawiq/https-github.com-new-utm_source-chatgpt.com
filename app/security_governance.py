import os,html,time,urllib.parse
from collections import defaultdict,deque
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse,JSONResponse
from app.storage import db,get_session,authenticate,hash_password,verify_password,execute,rows,one,log,utcnow,delete_session
router=APIRouter()
APP_ORIGIN='https://gulf-logistics-ai-v7-production.up.railway.app'
_attempts=defaultdict(deque)
def e(v):return html.escape(str(v or ''))
def session(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s
def admin(r):
 s=session(r)
 if s.get('role')!='admin':raise HTTPException(403,'Admin role required')
 return s
def parse(raw):return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def page(body):return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Arial;background:#07131f;color:#eef6fb}.w{max-width:1050px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}input{width:100%;padding:12px;margin:7px 0;background:#081925;color:white;border:1px solid #36586e;border-radius:9px}.btn{padding:10px 14px;background:#22c55e;color:#04130a;border:0;border-radius:9px;font-weight:bold}a{color:#dff6ff}table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #28475d;text-align:right}.good{color:#86efac}</style><div class="w">'+body+'</div>')
def init_security():
 with db() as c:
  c.execute("""CREATE TABLE IF NOT EXISTS security_events(id BIGSERIAL PRIMARY KEY,user_id BIGINT,event_type TEXT NOT NULL,ip_hash TEXT,detail TEXT,created_at TIMESTAMPTZ NOT NULL)""")
  c.execute("""CREATE TABLE IF NOT EXISTS login_attempts(id BIGSERIAL PRIMARY KEY,email TEXT,ip_hash TEXT,success INTEGER NOT NULL DEFAULT 0,created_at TIMESTAMPTZ NOT NULL)""")
init_security()
def iphash(r):
 import hashlib
 ip=(r.headers.get('x-forwarded-for') or (r.client.host if r.client else 'unknown')).split(',')[0].strip();return hashlib.sha256((ip+'|gla').encode()).hexdigest()[:20]
def record_login(email,r,success):
 execute('INSERT INTO login_attempts(email,ip_hash,success,created_at) VALUES(?,?,?,?)',(email.lower().strip(),iphash(r),1 if success else 0,utcnow()))
def login_allowed(email,r):
 cutoff=utcnow()-__import__('datetime').timedelta(minutes=15);x=one('SELECT COUNT(*) n FROM login_attempts WHERE created_at>? AND success=0 AND (email=? OR ip_hash=?)',(cutoff,email.lower().strip(),iphash(r)));return int(x['n'])<8
@router.get('/security')
def security(r:Request):
 s=admin(r);events=rows('SELECT * FROM security_events ORDER BY id DESC LIMIT 100');ev=''.join('<tr><td>'+e(x['created_at'])+'</td><td>'+e(x['event_type'])+'</td><td>'+e(x['detail'])+'</td></tr>' for x in events);return page('<p><a href="/dashboard">← النظام</a></p><h1>Enterprise Security & Governance</h1><div class="card"><b class="good">الحماية النشطة</b><p>Same-origin CSRF enforcement للطلبات الموثقة · Login rate limiting · Secure/HttpOnly session cookies · RBAC للإدارة · Audit security events.</p></div><div class="card"><h2>تغيير كلمة المرور</h2><form method="post" action="/security/password"><input type="hidden" name="csrf" value="'+e(s['csrf'])+'"><input type="password" name="current_password" placeholder="كلمة المرور الحالية" required><input type="password" name="new_password" placeholder="كلمة المرور الجديدة — 14 حرفًا على الأقل" minlength="14" required><button class="btn">تغيير كلمة المرور وإغلاق الجلسة</button></form></div><div class="card"><h2>Security Audit</h2><table><tr><th>الوقت</th><th>الحدث</th><th>التفاصيل</th></tr>'+ev+'</table></div>')
@router.post('/security/password')
async def change_password(r:Request):
 s=admin(r);d=parse(await r.body())
 if d.get('csrf')!=s.get('csrf'):raise HTTPException(403,'Invalid CSRF token')
 u=one('SELECT * FROM users WHERE id=?',(s['user_id'],))
 if not u or not verify_password(d.get('current_password',''),u['password_hash']):raise HTTPException(400,'Current password is incorrect')
 new=d.get('new_password','')
 if len(new)<14 or new.lower()==new or new.upper()==new or not any(c.isdigit() for c in new):raise HTTPException(400,'Password must be at least 14 characters with upper/lowercase and a number')
 execute('UPDATE users SET password_hash=? WHERE id=?',(hash_password(new),s['user_id']));execute('INSERT INTO security_events(user_id,event_type,ip_hash,detail,created_at) VALUES(?,?,?,?,?)',(s['user_id'],'password_changed',iphash(r),'Admin changed own password',utcnow()));log(s['user_id'],'security_password_change','user',s['user_id'],'Password changed');delete_session(r.cookies.get('gla_session'));resp=RedirectResponse('/login',303);resp.delete_cookie('gla_session');return resp
@router.get('/api/v7/security/status')
def status(r:Request):
 s=admin(r);return {'csrf':'same_origin_enforced_for_authenticated_posts','password_change':True,'login_rate_limit':{'max_failed_attempts':8,'window_minutes':15},'rbac':{'admin_routes':['/security']},'audit':True,'session_cookie':{'httponly':True,'secure':os.getenv('BROWSER_COOKIE_SECURE','1')=='1','samesite':'lax'}}
