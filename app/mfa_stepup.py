import os,html,urllib.parse,base64,hashlib,hmac,struct,time,secrets,datetime
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from cryptography.fernet import Fernet
from app.storage import db,get_session,one,execute,log,utcnow
router=APIRouter()
STEPUP_MINUTES=10

def e(v):return html.escape(str(v or ''))
def parse(raw):return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def sess(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s

def _fernet():
 raw=os.getenv('TOKEN_ENCRYPTION_KEY','').encode()
 if not raw:raise RuntimeError('TOKEN_ENCRYPTION_KEY is required for MFA secret encryption')
 key=base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
 return Fernet(key)
def enc(v):return _fernet().encrypt(v.encode()).decode()
def dec(v):return _fernet().decrypt(v.encode()).decode()
def gen_secret():return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
def hotp(secret,counter):
 pad='='*((8-len(secret)%8)%8);key=base64.b32decode(secret+pad,casefold=True);msg=struct.pack('>Q',counter);d=hmac.new(key,msg,hashlib.sha1).digest();o=d[-1]&15;code=(struct.unpack('>I',d[o:o+4])[0]&0x7fffffff)%1000000;return f'{code:06d}'
def valid_totp(secret,code,window=1):
 if not code or not code.isdigit() or len(code)!=6:return False
 c=int(time.time())//30
 return any(hmac.compare_digest(hotp(secret,c+i),code) for i in range(-window,window+1))
def init():
 with db() as c:
  c.execute('''CREATE TABLE IF NOT EXISTS user_mfa(user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,secret_enc TEXT,mfa_enabled INTEGER NOT NULL DEFAULT 0,enrolled_at TIMESTAMPTZ,updated_at TIMESTAMPTZ NOT NULL)''')
  c.execute('''CREATE TABLE IF NOT EXISTS stepup_auth(session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,user_id BIGINT NOT NULL,verified_at TIMESTAMPTZ NOT NULL,expires_at TIMESTAMPTZ NOT NULL)''')
init()
def mfa_state(user_id):return one('SELECT * FROM user_mfa WHERE user_id=?',(user_id,))
def recent_stepup(session_id):
 x=one('SELECT * FROM stepup_auth WHERE session_id=? AND expires_at>?',(session_id,utcnow()));return bool(x)
def page(b):return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Arial;background:#07131f;color:#eef6fb}.w{max-width:850px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}input{width:100%;padding:12px;margin:7px 0;background:#081925;color:white;border:1px solid #36586e;border-radius:9px}.btn{padding:10px 14px;background:#22c55e;color:#04130a;border:0;border-radius:9px;font-weight:bold}a{color:#dff6ff}.secret{font-family:monospace;font-size:18px;word-break:break-all;background:#081925;padding:12px;border-radius:9px}</style><div class="w">'+b+'</div>')
@router.get('/mfa')
def mfa(r:Request):
 s=sess(r);m=mfa_state(s['user_id']);enabled=bool(m and m['mfa_enabled'])
 body='<p><a href="/identity">Identity & Access</a> · <a href="/dashboard">الرئيسية</a></p><h1>MFA / 2FA</h1>'
 if enabled:
  body+='<div class="card"><h2>المصادقة الثنائية مفعلة ✓</h2><p>تُستخدم رموز TOTP من تطبيق مصادقة متوافق. الإجراءات الحساسة تحتاج Step-up خلال آخر '+str(STEPUP_MINUTES)+' دقائق.</p><a class="btn" href="/mfa/step-up">تحقق الآن</a></div>'
 else:
  body+='<div class="card"><h2>تفعيل المصادقة الثنائية</h2><p>ابدأ الإعداد لإنشاء مفتاح TOTP ثم أضفه إلى تطبيق المصادقة.</p><form method="post" action="/mfa/setup"><input type="hidden" name="csrf" value="'+e(s['csrf'])+'"><button class="btn">بدء الإعداد</button></form></div>'
 return page(body)
@router.post('/mfa/setup')
async def setup(r:Request):
 s=sess(r);d=parse(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 secret=gen_secret();now=utcnow();execute('INSERT INTO user_mfa(user_id,secret_enc,mfa_enabled,enrolled_at,updated_at) VALUES(?,?,0,NULL,?) ON CONFLICT(user_id) DO UPDATE SET secret_enc=excluded.secret_enc,mfa_enabled=0,enrolled_at=NULL,updated_at=excluded.updated_at',(s['user_id'],enc(secret),now));uri='otpauth://totp/Gulf%20Logistics%20AI:'+urllib.parse.quote(s['email'])+'?secret='+secret+'&issuer=Gulf%20Logistics%20AI&digits=6&period=30'
 return page('<h1>إعداد MFA</h1><div class="card"><p>أضف المفتاح التالي يدويًا إلى تطبيق المصادقة:</p><div class="secret">'+e(secret)+'</div><p>أو استخدم URI التالي في تطبيق يدعم الاستيراد:</p><div class="secret">'+e(uri)+'</div><form method="post" action="/mfa/enable"><input type="hidden" name="csrf" value="'+e(s['csrf'])+'"><input name="code" inputmode="numeric" maxlength="6" placeholder="رمز التحقق المكوّن من 6 أرقام" required><button class="btn">تأكيد وتفعيل MFA</button></form></div>')
@router.post('/mfa/enable')
async def enable(r:Request):
 s=sess(r);d=parse(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 m=mfa_state(s['user_id'])
 if not m or not m.get('secret_enc'):raise HTTPException(400,'Start MFA setup first')
 if not valid_totp(dec(m['secret_enc']),d.get('code','')):raise HTTPException(400,'Invalid verification code')
 now=utcnow();execute('UPDATE user_mfa SET mfa_enabled=1,enrolled_at=?,updated_at=? WHERE user_id=?',(now,now,s['user_id']));log(s['user_id'],'mfa_enabled','user',s['user_id'],'TOTP MFA enabled');return RedirectResponse('/mfa',303)
@router.get('/mfa/step-up')
def stepup(r:Request,next:str='/dashboard'):
 s=sess(r);m=mfa_state(s['user_id'])
 if not m or not m['mfa_enabled']:return RedirectResponse('/mfa',303)
 safe=next if next.startswith('/') and not next.startswith('//') else '/dashboard'
 return page('<h1>Step-up Authentication</h1><div class="card"><p>أدخل رمز MFA لإتاحة الإجراءات الحساسة لمدة '+str(STEPUP_MINUTES)+' دقائق.</p><form method="post" action="/mfa/step-up"><input type="hidden" name="csrf" value="'+e(s['csrf'])+'"><input type="hidden" name="next" value="'+e(safe)+'"><input name="code" inputmode="numeric" maxlength="6" placeholder="رمز MFA" required><button class="btn">تحقق</button></form></div>')
@router.post('/mfa/step-up')
async def stepup_post(r:Request):
 s=sess(r);d=parse(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 m=mfa_state(s['user_id'])
 if not m or not m['mfa_enabled'] or not valid_totp(dec(m['secret_enc']),d.get('code','')):raise HTTPException(400,'Invalid MFA code')
 now=utcnow();exp=now+datetime.timedelta(minutes=STEPUP_MINUTES);execute('INSERT INTO stepup_auth(session_id,user_id,verified_at,expires_at) VALUES(?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET verified_at=excluded.verified_at,expires_at=excluded.expires_at',(s['id'],s['user_id'],now,exp));log(s['user_id'],'mfa_stepup','session',None,'Step-up authentication completed');n=d.get('next','/dashboard');return RedirectResponse(n if n.startswith('/') and not n.startswith('//') else '/dashboard',303)
@router.get('/api/v7/mfa/status')
def status(r:Request):
 s=sess(r);m=mfa_state(s['user_id']);return {'enabled':bool(m and m['mfa_enabled']),'recent_stepup':recent_stepup(s['id']),'stepup_window_minutes':STEPUP_MINUTES}
