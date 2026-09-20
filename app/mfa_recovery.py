import hashlib,secrets,html,urllib.parse,datetime
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import db,get_session,one,rows,execute,log,utcnow
router=APIRouter()
MAX_ATTEMPTS=5
WINDOW_MINUTES=15

def e(v):return html.escape(str(v or ''))
def parse(raw):return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def sess(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s
def init():
 with db() as c:
  c.execute('''CREATE TABLE IF NOT EXISTS mfa_recovery_codes(id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,code_hash TEXT NOT NULL UNIQUE,used_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL)''')
  c.execute('''CREATE TABLE IF NOT EXISTS mfa_attempts(id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL,session_id TEXT,kind TEXT NOT NULL,success INTEGER NOT NULL,ip_address TEXT,created_at TIMESTAMPTZ NOT NULL)''')
init()
def h(code):return hashlib.sha256(code.strip().upper().encode()).hexdigest()
def blocked(user_id):
 since=utcnow()-datetime.timedelta(minutes=WINDOW_MINUTES);x=one('SELECT COUNT(*) n FROM mfa_attempts WHERE user_id=? AND success=0 AND created_at>=?',(user_id,since));return int(x['n'] or 0)>=MAX_ATTEMPTS
def attempt(s,kind,ok,ip):execute('INSERT INTO mfa_attempts(user_id,session_id,kind,success,ip_address,created_at) VALUES(?,?,?,?,?,?)',(s['user_id'],s['id'],kind,1 if ok else 0,ip,utcnow()))
def generate_codes(user_id):
 execute('DELETE FROM mfa_recovery_codes WHERE user_id=?',(user_id,));now=utcnow();codes=[]
 for _ in range(10):
  raw=secrets.token_hex(5).upper();code=raw[:5]+'-'+raw[5:];codes.append(code);execute('INSERT INTO mfa_recovery_codes(user_id,code_hash,created_at) VALUES(?,?,?)',(user_id,h(code),now))
 return codes
def use_recovery(user_id,code):
 x=one('SELECT id FROM mfa_recovery_codes WHERE user_id=? AND code_hash=? AND used_at IS NULL',(user_id,h(code)))
 if not x:return False
 execute('UPDATE mfa_recovery_codes SET used_at=? WHERE id=? AND used_at IS NULL',(utcnow(),x['id']));return True
def pg(b):return HTMLResponse('<html lang="ar" dir="rtl"><meta charset="utf-8"><style>body{font-family:Arial;background:#07131f;color:#eef6fb;padding:24px}.card{max-width:850px;margin:15px auto;background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px}input{width:100%;padding:12px;margin:7px 0;background:#081925;color:white;border:1px solid #36586e;border-radius:9px}.btn{padding:10px 14px;background:#22c55e;border:0;border-radius:9px;font-weight:bold}.codes{font-family:monospace;font-size:18px;line-height:1.8}a{color:white}</style>'+b+'</html>')
@router.get('/mfa/recovery')
def recovery(r:Request):
 s=sess(r);remaining=one('SELECT COUNT(*) n FROM mfa_recovery_codes WHERE user_id=? AND used_at IS NULL',(s['user_id'],));return pg('<div class="card"><p><a href="/mfa">MFA</a></p><h1>MFA Recovery & Resilience</h1><p>أكواد الاسترداد المتبقية: <b>'+str(remaining['n'])+'</b></p><form method="post" action="/mfa/recovery/generate"><input type="hidden" name="csrf" value="'+e(s['csrf'])+'"><button class="btn">إنشاء أكواد استرداد جديدة</button></form><p>إنشاء مجموعة جديدة يلغي جميع الأكواد القديمة.</p></div>')
@router.post('/mfa/recovery/generate')
async def generate(r:Request):
 s=sess(r);d=parse(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 from app.mfa_stepup import recent_stepup
 if not recent_stepup(s['id']):return RedirectResponse('/mfa/step-up?next=/mfa/recovery',303)
 codes=generate_codes(s['user_id']);log(s['user_id'],'mfa_recovery_regenerated','user',s['user_id'],'Recovery codes regenerated')
 return pg('<div class="card"><h1>أكواد الاسترداد</h1><p>احفظها الآن في مكان آمن. لن يعرض النظام هذه القيم مرة أخرى.</p><div class="codes">'+'<br>'.join(e(x) for x in codes)+'</div><p><a href="/mfa">العودة إلى MFA</a></p></div>')
@router.get('/mfa/recovery/step-up')
def recovery_stepup(r:Request,next:str='/dashboard'):
 s=sess(r);safe=next if next.startswith('/') and not next.startswith('//') else '/dashboard';return pg('<div class="card"><h1>استخدام كود استرداد</h1><form method="post" action="/mfa/recovery/step-up"><input type="hidden" name="csrf" value="'+e(s['csrf'])+'"><input type="hidden" name="next" value="'+e(safe)+'"><input name="code" placeholder="XXXXX-XXXXX" required><button class="btn">تحقق</button></form></div>')
@router.post('/mfa/recovery/step-up')
async def recovery_post(r:Request):
 s=sess(r);d=parse(await r.body());ip=r.client.host if r.client else None
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 if blocked(s['user_id']):raise HTTPException(429,'Too many MFA attempts; try again later')
 ok=use_recovery(s['user_id'],d.get('code',''));attempt(s,'recovery',ok,ip)
 if not ok:raise HTTPException(400,'Invalid or already used recovery code')
 from app.mfa_stepup import STEPUP_MINUTES
 now=utcnow();exp=now+datetime.timedelta(minutes=STEPUP_MINUTES);execute('INSERT INTO stepup_auth(session_id,user_id,verified_at,expires_at) VALUES(?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET verified_at=excluded.verified_at,expires_at=excluded.expires_at',(s['id'],s['user_id'],now,exp));log(s['user_id'],'mfa_recovery_used','session',None,'Recovery code used for step-up');n=d.get('next','/dashboard');return RedirectResponse(n if n.startswith('/') and not n.startswith('//') else '/dashboard',303)
@router.post('/team/{uid}/reset-mfa')
async def admin_reset(uid:int,r:Request):
 s=sess(r);d=parse(await r.body())
 if s.get('role')!='admin':raise HTTPException(403)
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 from app.mfa_stepup import recent_stepup
 if not recent_stepup(s['id']):raise HTTPException(428,'Admin MFA step-up required before resetting another user MFA')
 if uid==s['user_id']:raise HTTPException(400,'Use your recovery flow for your own account')
 u=one('SELECT id FROM users WHERE id=?',(uid,));
 if not u:raise HTTPException(404)
 execute('DELETE FROM user_mfa WHERE user_id=?',(uid,));execute('DELETE FROM mfa_recovery_codes WHERE user_id=?',(uid,));execute('DELETE FROM stepup_auth WHERE user_id=?',(uid,));execute('DELETE FROM sessions WHERE user_id=?',(uid,));log(s['user_id'],'admin_mfa_reset','user',uid,'MFA reset; target sessions revoked');return RedirectResponse('/team',303)
@router.get('/api/v7/mfa/security')
def api(r:Request):
 s=sess(r);remaining=one('SELECT COUNT(*) n FROM mfa_recovery_codes WHERE user_id=? AND used_at IS NULL',(s['user_id'],));return {'recovery_codes_remaining':remaining['n'],'rate_limit':{'max_failed_attempts':MAX_ATTEMPTS,'window_minutes':WINDOW_MINUTES},'admin_reset_requires_stepup':True}
