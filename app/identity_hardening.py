import html,urllib.parse
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import db,get_session,one,rows,execute,hash_password,verify_password,log,utcnow
router=APIRouter()
def e(v):return html.escape(str(v or ''))
def parse(raw):return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def s(r):
 x=get_session(r.cookies.get('gla_session'))
 if not x:raise HTTPException(401)
 return x
def init():
 with db() as c:
  c.execute('ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_agent TEXT')
  c.execute('ALTER TABLE sessions ADD COLUMN IF NOT EXISTS ip_address TEXT')
  c.execute('ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ')
init()
def pg(b):return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><style>body{font-family:Arial;background:#07131f;color:#eef6fb}.w{max-width:900px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}input{width:100%;padding:12px;margin:6px 0;background:#081925;color:white;border:1px solid #36586e;border-radius:9px}.btn{padding:10px 14px;background:#22c55e;border:0;border-radius:9px;font-weight:bold}a{color:#dff6ff}table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #28475d;text-align:right}</style><div class="w">'+b+'</div>')
@router.get('/identity')
def identity(r:Request):
 x=s(r);u=one('SELECT * FROM users WHERE id=?',(x['user_id'],));ss=rows('SELECT id,created_at,expires_at,last_seen_at,ip_address,user_agent FROM sessions WHERE user_id=? AND expires_at>? ORDER BY created_at DESC',(x['user_id'],));tr=''.join('<tr><td>'+e(z['created_at'])+'</td><td>'+e(z.get('ip_address') or '—')+'</td><td>'+e((z.get('user_agent') or '—')[:80])+'</td><td>'+('الحالية' if z['id']==x['id'] else '<form method="post" action="/identity/sessions/'+e(z['id'])+'/revoke"><input type="hidden" name="csrf" value="'+e(x['csrf'])+'"><button class="btn">إنهاء</button></form>')+'</td></tr>' for z in ss)
 return pg('<p><a href="/dashboard">الرئيسية</a></p><h1>Identity & Access</h1><div class="card"><h2>تغيير كلمة المرور</h2><form method="post" action="/identity/password"><input type="hidden" name="csrf" value="'+e(x['csrf'])+'"><input type="password" name="current" placeholder="كلمة المرور الحالية" required><input type="password" name="new" placeholder="كلمة المرور الجديدة — 12 حرفًا على الأقل" required><input type="password" name="confirm" placeholder="تأكيد كلمة المرور" required><button class="btn">تغيير كلمة المرور</button></form></div><div class="card"><h2>الجلسات</h2><form method="post" action="/identity/sessions/revoke-others"><input type="hidden" name="csrf" value="'+e(x['csrf'])+'"><button class="btn">إنهاء كل الجلسات الأخرى</button></form><table><tr><th>الإنشاء</th><th>IP</th><th>الجهاز/المتصفح</th><th></th></tr>'+tr+'</table></div>')
@router.post('/identity/password')
async def password(r:Request):
 x=s(r);d=parse(await r.body())
 if d.get('csrf')!=x['csrf']:raise HTTPException(403)
 u=one('SELECT * FROM users WHERE id=?',(x['user_id'],));new=d.get('new','')
 if not verify_password(d.get('current',''),u['password_hash']):raise HTTPException(400,'Current password is incorrect')
 if len(new)<12 or new!=d.get('confirm'):raise HTTPException(400,'Password must be at least 12 characters and match confirmation')
 execute('UPDATE users SET password_hash=?,must_change_password=0 WHERE id=?',(hash_password(new),x['user_id']));execute('DELETE FROM sessions WHERE user_id=?',(x['user_id'],));log(x['user_id'],'password_changed','user',x['user_id'],'All sessions revoked');resp=RedirectResponse('/login',303);resp.delete_cookie('gla_session');return resp
@router.post('/identity/sessions/revoke-others')
async def revoke_others(r:Request):
 x=s(r);d=parse(await r.body())
 if d.get('csrf')!=x['csrf']:raise HTTPException(403)
 execute('DELETE FROM sessions WHERE user_id=? AND id<>?',(x['user_id'],x['id']));log(x['user_id'],'sessions_revoked','user',x['user_id'],'Revoked other sessions');return RedirectResponse('/identity',303)
@router.post('/identity/sessions/{sid}/revoke')
async def revoke(sid:str,r:Request):
 x=s(r);d=parse(await r.body())
 if d.get('csrf')!=x['csrf']:raise HTTPException(403)
 execute('DELETE FROM sessions WHERE id=? AND user_id=?',(sid,x['user_id']));log(x['user_id'],'session_revoked','user',x['user_id'],'Session revoked');return RedirectResponse('/identity',303)
