import os,html,urllib.parse,base64,hashlib,hmac,struct,time,secrets,datetime,io
import qrcode
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from cryptography.fernet import Fernet
from app.storage import db,get_session,one,execute,log,utcnow
router=APIRouter();STEPUP_MINUTES=10
def e(v):return html.escape(str(v or ''))
def parse(raw):return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def sess(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s
def _fernet():
 raw=os.getenv('TOKEN_ENCRYPTION_KEY','').encode()
 if not raw:raise RuntimeError('TOKEN_ENCRYPTION_KEY is required for MFA secret encryption')
 return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw).digest()))
def enc(v):return _fernet().encrypt(v.encode()).decode()
def dec(v):return _fernet().decrypt(v.encode()).decode()
def gen_secret():return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
def hotp(secret,counter):
 pad='='*((8-len(secret)%8)%8);key=base64.b32decode(secret+pad,casefold=True);msg=struct.pack('>Q',counter);d=hmac.new(key,msg,hashlib.sha1).digest();o=d[-1]&15;return f'{(struct.unpack(">I",d[o:o+4])[0]&0x7fffffff)%1000000:06d}'
def valid_totp(secret,code,window=1):
 if not code or not code.isdigit() or len(code)!=6:return False
 c=int(time.time())//30;return any(hmac.compare_digest(hotp(secret,c+i),code) for i in range(-window,window+1))
def qr_data_uri(text):
 qr=qrcode.QRCode(version=None,error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=8,border=4);qr.add_data(text);qr.make(fit=True)
 img=qr.make_image(fill_color='black',back_color='white');buf=io.BytesIO();img.save(buf,format='PNG')
 return 'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()
def init():
 with db() as c:
  c.execute('CREATE TABLE IF NOT EXISTS user_mfa(user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,secret_enc TEXT,mfa_enabled INTEGER NOT NULL DEFAULT 0,enrolled_at TIMESTAMPTZ,updated_at TIMESTAMPTZ NOT NULL)')
  c.execute('CREATE TABLE IF NOT EXISTS stepup_auth(session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,user_id BIGINT NOT NULL,verified_at TIMESTAMPTZ NOT NULL,expires_at TIMESTAMPTZ NOT NULL)')
init()
def mfa_state(user_id):return one('SELECT * FROM user_mfa WHERE user_id=?',(user_id,))
def recent_stepup(session_id):return bool(one('SELECT * FROM stepup_auth WHERE session_id=? AND expires_at>?',(session_id,utcnow())))
def guard_attempt(s,kind,ok,r):
 from app.mfa_recovery import blocked,attempt
 if blocked(s['user_id']):raise HTTPException(429,'Too many MFA attempts; try again later')
 attempt(s,kind,ok,r.client.host if r.client else None)
def page(b):return HTMLResponse('<html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Arial;background:#07131f;color:#eef6fb}.w{max-width:850px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}input{width:100%;padding:12px;margin:7px 0;background:#081925;color:white;border:1px solid #36586e;border-radius:9px;box-sizing:border-box}.btn{padding:10px 14px;background:#22c55e;color:#04130a;border:0;border-radius:9px;font-weight:bold}a{color:#dff6ff}.secret{font-family:monospace;font-size:18px;word-break:break-all;background:#081925;padding:12px;border-radius:9px}.qr{background:#fff;padding:14px;border-radius:14px;display:inline-block;margin:12px 0}.qr img{display:block;width:min(300px,78vw);height:auto}.muted{color:#b7c9d5;line-height:1.8}.warn{background:#2b1d11;border:1px solid #6d4a22;padding:12px;border-radius:10px}</style><div class="w">'+b+'</div>')
@router.get('/mfa')
def mfa(r:Request):
 s=sess(r);m=mfa_state(s['user_id']);enabled=bool(m and m['mfa_enabled']);body='<p><a href="/identity">Identity & Access</a></p><h1>MFA / 2FA</h1>'
 if enabled:body+='<div class="card"><h2>المصادقة الثنائية مفعلة ✓</h2><a class="btn" href="/mfa/step-up">تحقق الآن</a> <a href="/mfa/recovery">أكواد الاسترداد</a> · <a href="/mfa/recovery/step-up">استخدام كود استرداد</a></div>'
 else:body+='<div class="card"><h2>تفعيل المصادقة الثنائية</h2><p class="muted">سيتم إنشاء رمز QR حقيقي يمكنك مسحه مباشرة باستخدام Google Authenticator أو Microsoft Authenticator.</p><form method="post" action="/mfa/setup"><input type="hidden" name="csrf" value="'+e(s['csrf'])+'"><button class="btn">إنشاء QR وبدء الإعداد</button></form></div>'
 return page(body)
@router.post('/mfa/setup')
async def setup(r:Request):
 s=sess(r);d=parse(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 secret=gen_secret();now=utcnow();execute('INSERT INTO user_mfa(user_id,secret_enc,mfa_enabled,enrolled_at,updated_at) VALUES(?,?,0,NULL,?) ON CONFLICT(user_id) DO UPDATE SET secret_enc=excluded.secret_enc,mfa_enabled=0,enrolled_at=NULL,updated_at=excluded.updated_at',(s['user_id'],enc(secret),now));uri='otpauth://totp/Gulf%20Logistics%20AI:'+urllib.parse.quote(s['email'])+'?secret='+secret+'&issuer=Gulf%20Logistics%20AI&digits=6&period=30';qr=qr_data_uri(uri);return page('<h1>إعداد MFA</h1><div class="card"><h2>1) امسح رمز QR</h2><p class="muted">افتح Google Authenticator أو Microsoft Authenticator ثم اختر إضافة حساب عبر مسح QR.</p><div class="qr"><img alt="TOTP QR code" src="'+qr+'"></div><div class="warn">لا تشارك صورة QR أو المفتاح السري أو رمز التحقق مع أي شخص.</div><details><summary>إدخال يدوي بدل QR</summary><p class="muted">إذا تعذر المسح، أضف حسابًا يدويًا باستخدام المفتاح التالي:</p><div class="secret">'+e(secret)+'</div></details><h2>2) أدخل الرمز الحالي من التطبيق</h2><form method="post" action="/mfa/enable"><input type="hidden" name="csrf" value="'+e(s['csrf'])+'"><input name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" placeholder="123456" required><button class="btn">تأكيد وتفعيل MFA</button></form><p class="muted">استخدم الرمز الظاهر الآن في التطبيق. إذا كان المؤقت على وشك الانتهاء، انتظر الرمز التالي ثم أدخله فورًا.</p></div>')
@router.post('/mfa/enable')
async def enable(r:Request):
 s=sess(r);d=parse(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 from app.mfa_recovery import blocked
 if blocked(s['user_id']):raise HTTPException(429,'Too many MFA attempts; try again later')
 m=mfa_state(s['user_id']);ok=bool(m and m.get('secret_enc') and valid_totp(dec(m['secret_enc']),d.get('code','')));guard_attempt(s,'enable',ok,r)
 if not ok:raise HTTPException(400,'Invalid verification code')
 now=utcnow();execute('UPDATE user_mfa SET mfa_enabled=1,enrolled_at=?,updated_at=? WHERE user_id=?',(now,now,s['user_id']));log(s['user_id'],'mfa_enabled','user',s['user_id'],'TOTP MFA enabled');return RedirectResponse('/mfa/recovery',303)
@router.get('/mfa/step-up')
def stepup(r:Request,next:str='/dashboard'):
 s=sess(r);m=mfa_state(s['user_id'])
 if not m or not m['mfa_enabled']:return RedirectResponse('/mfa',303)
 safe=next if next.startswith('/') and not next.startswith('//') else '/dashboard';return page('<h1>Step-up Authentication</h1><div class="card"><form method="post" action="/mfa/step-up"><input type="hidden" name="csrf" value="'+e(s['csrf'])+'"><input type="hidden" name="next" value="'+e(safe)+'"><input name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" required><button class="btn">تحقق</button></form><p><a href="/mfa/recovery/step-up?next='+urllib.parse.quote(safe)+'">استخدام كود استرداد</a></p></div>')
@router.post('/mfa/step-up')
async def stepup_post(r:Request):
 s=sess(r);d=parse(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 from app.mfa_recovery import blocked
 if blocked(s['user_id']):raise HTTPException(429,'Too many MFA attempts; try again later')
 m=mfa_state(s['user_id']);ok=bool(m and m['mfa_enabled'] and valid_totp(dec(m['secret_enc']),d.get('code','')));guard_attempt(s,'stepup',ok,r)
 if not ok:raise HTTPException(400,'Invalid MFA code')
 now=utcnow();exp=now+datetime.timedelta(minutes=STEPUP_MINUTES);execute('INSERT INTO stepup_auth(session_id,user_id,verified_at,expires_at) VALUES(?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET verified_at=excluded.verified_at,expires_at=excluded.expires_at',(s['id'],s['user_id'],now,exp));log(s['user_id'],'mfa_stepup','session',None,'Step-up authentication completed');n=d.get('next','/dashboard');return RedirectResponse(n if n.startswith('/') and not n.startswith('//') else '/dashboard',303)
@router.get('/api/v7/mfa/status')
def status(r:Request):
 s=sess(r);m=mfa_state(s['user_id']);return {'enabled':bool(m and m['mfa_enabled']),'recent_stepup':recent_stepup(s['id']),'stepup_window_minutes':STEPUP_MINUTES}
