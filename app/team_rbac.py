import html,urllib.parse,secrets,string
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import db,get_session,rows,one,execute,hash_password,log,utcnow
router=APIRouter()
ROLES={'admin':'الإدارة','sales':'المبيعات','customs':'التخليص الجمركي','transport':'النقل','finance':'المالية','viewer':'قراءة فقط'}
PERMISSIONS={'admin':['*'],'sales':['sales','customers','quotes','email'],'customs':['operations','customs'],'transport':['operations','transport'],'finance':['quotes','finance','reports'],'viewer':['read']}
def e(v):return html.escape(str(v or ''))
def parse(raw):return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def session(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s
def admin(r):
 s=session(r)
 if s.get('role')!='admin':raise HTTPException(403,'Admin role required')
 return s
def init():
 with db() as c:
  c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active INTEGER NOT NULL DEFAULT 1')
  c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS department TEXT')
  c.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password INTEGER NOT NULL DEFAULT 0')
  c.execute('''CREATE TABLE IF NOT EXISTS role_audit(id BIGSERIAL PRIMARY KEY,target_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,actor_user_id BIGINT,old_role TEXT,new_role TEXT,action TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL)''')
init()
def page(b):return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Arial;background:#07131f;color:#eef6fb}.w{max-width:1200px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}input,select{width:100%;padding:11px;background:#081925;color:white;border:1px solid #36586e;border-radius:9px}.btn{padding:9px 12px;background:#22c55e;color:#04130a;border:0;border-radius:9px;font-weight:bold}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #28475d;text-align:right}a{color:#dff6ff}.muted{color:#9fb4c4}</style><div class="w">'+b+'</div>')
def audit(actor,target,old,new,action):execute('INSERT INTO role_audit(target_user_id,actor_user_id,old_role,new_role,action,created_at) VALUES(?,?,?,?,?,?)',(target,actor,old,new,action,utcnow()))
@router.get('/team')
def team(r:Request):
 s=admin(r);us=rows('SELECT id,email,name,role,department,is_active,must_change_password,created_at FROM users ORDER BY id');tr=''.join('<tr><td>'+e(x['name'])+'<br><span class="muted">'+e(x['email'])+'</span></td><td>'+e(ROLES.get(x['role'],x['role']))+'</td><td>'+e(x.get('department'))+'</td><td>'+('نشط' if x['is_active'] else 'موقوف')+'</td><td><form method="post" action="/team/'+str(x['id'])+'/role"><input type="hidden" name="csrf" value="'+e(s['csrf'])+'"><select name="role">'+''.join('<option value="'+k+'" '+('selected' if k==x['role'] else '')+'>'+v+'</option>' for k,v in ROLES.items())+'</select><button class="btn">تحديث</button></form></td><td><form method="post" action="/team/'+str(x['id'])+'/toggle"><input type="hidden" name="csrf" value="'+e(s['csrf'])+'"><button class="btn">'+('إيقاف' if x['is_active'] else 'تفعيل')+'</button></form></td></tr>' for x in us)
 return page('<p><a href="/security">الأمن</a> · <a href="/dashboard">الرئيسية</a></p><h1>Team & RBAC Management — آفاق طويق</h1><div class="card"><h2>إضافة مستخدم داخلي</h2><p class="muted">ينشئ النظام كلمة مرور مؤقتة عشوائية مرة واحدة. لا تُرسل تلقائيًا لأي شخص.</p><form method="post" action="/team/create"><input type="hidden" name="csrf" value="'+e(s['csrf'])+'"><div class="grid"><input name="name" placeholder="الاسم" required><input type="email" name="email" placeholder="البريد" required><input name="department" placeholder="القسم"><select name="role">'+''.join('<option value="'+k+'">'+v+'</option>' for k,v in ROLES.items())+'</select></div><button class="btn">إنشاء المستخدم</button></form></div><div class="card"><h2>المستخدمون والصلاحيات</h2><table><tr><th>المستخدم</th><th>الدور</th><th>القسم</th><th>الحالة</th><th>تغيير الدور</th><th>الحساب</th></tr>'+tr+'</table></div><div class="card"><h2>مصفوفة الصلاحيات</h2><table>'+''.join('<tr><td>'+e(ROLES[k])+'</td><td>'+e('، '.join(v))+'</td></tr>' for k,v in PERMISSIONS.items())+'</table></div>')
@router.post('/team/create')
async def create(r:Request):
 s=admin(r);d=parse(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 role=d.get('role','viewer')
 if role not in ROLES:raise HTTPException(400)
 alphabet=string.ascii_letters+string.digits+'!@#$%';temp=''.join(secrets.choice(alphabet) for _ in range(20));now=utcnow()
 try:uid=execute('INSERT INTO users(email,name,password_hash,role,created_at,is_active,department,must_change_password) VALUES(?,?,?,?,?,?,?,?)',(d['email'].lower().strip(),d['name'].strip(),hash_password(temp),role,now,1,d.get('department'),1))
 except Exception:raise HTTPException(400,'Email already exists or invalid user data')
 audit(s['user_id'],uid,None,role,'user_created');log(s['user_id'],'team_user_create','user',uid,d['email']);return page('<h1>تم إنشاء المستخدم</h1><div class="card"><p>البريد: <b>'+e(d['email'])+'</b></p><p>كلمة المرور المؤقتة — تظهر الآن فقط:</p><p style="font-size:20px"><b>'+e(temp)+'</b></p><p>سلّمها للمستخدم عبر قناة آمنة. النظام لم يرسلها خارجيًا.</p><a href="/team">العودة للفريق</a></div>')
@router.post('/team/{uid}/role')
async def role(uid:int,r:Request):
 s=admin(r);d=parse(await r.body());
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 u=one('SELECT * FROM users WHERE id=?',(uid,));new=d.get('role')
 if not u or new not in ROLES:raise HTTPException(400)
 if uid==s['user_id'] and new!='admin':raise HTTPException(400,'Cannot remove your own admin role')
 execute('UPDATE users SET role=? WHERE id=?',(new,uid));audit(s['user_id'],uid,u['role'],new,'role_changed');log(s['user_id'],'rbac_role_change','user',uid,u['role']+' -> '+new);return RedirectResponse('/team',303)
@router.post('/team/{uid}/toggle')
async def toggle(uid:int,r:Request):
 s=admin(r);d=parse(await r.body());
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 if uid==s['user_id']:raise HTTPException(400,'Cannot disable your own account')
 u=one('SELECT * FROM users WHERE id=?',(uid,));
 if not u:raise HTTPException(404)
 new=0 if u.get('is_active',1) else 1;execute('UPDATE users SET is_active=? WHERE id=?',(new,uid));
 if not new:execute('DELETE FROM sessions WHERE user_id=?',(uid,))
 audit(s['user_id'],uid,u['role'],u['role'],'account_enabled' if new else 'account_disabled');log(s['user_id'],'team_account_toggle','user',uid,'enabled' if new else 'disabled');return RedirectResponse('/team',303)
@router.get('/api/v7/team')
def api(r:Request):
 admin(r);return {'roles':PERMISSIONS,'users':rows('SELECT id,email,name,role,department,is_active,must_change_password,created_at FROM users ORDER BY id')}
