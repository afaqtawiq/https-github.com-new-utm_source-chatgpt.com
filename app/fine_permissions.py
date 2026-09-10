import html,urllib.parse
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import db,get_session,rows,one,execute,log,utcnow
router=APIRouter()
ACTIONS={'send_email':'إرسال البريد','send_whatsapp':'إرسال واتساب','make_phone_call':'إجراء مكالمة هاتفية','approve_quote':'اعتماد العرض','approve_pricing':'اعتماد التسعير','view_profit':'مشاهدة التكلفة والربحية','manage_users':'إدارة المستخدمين','edit_operations':'تعديل العمليات','manage_gmail':'إدارة Gmail','accept_quote':'تسجيل قبول العميل'}
DEFAULT={'admin':set(ACTIONS),'sales':{'send_email','send_whatsapp','make_phone_call','accept_quote'},'customs':{'edit_operations'},'transport':{'edit_operations','send_whatsapp'},'finance':{'approve_pricing','view_profit'},'viewer':set()}
def init():
 with db() as c:c.execute('''CREATE TABLE IF NOT EXISTS role_permissions(role TEXT NOT NULL,permission TEXT NOT NULL,allowed INTEGER NOT NULL DEFAULT 1,updated_by BIGINT,updated_at TIMESTAMPTZ NOT NULL,PRIMARY KEY(role,permission))''')
init()
def has_permission(sess,perm):
 if not sess:return False
 r=sess.get('role','viewer');x=one('SELECT allowed FROM role_permissions WHERE role=? AND permission=?',(r,perm));return bool(x['allowed']) if x else perm in DEFAULT.get(r,set())
def admin(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s or s.get('role')!='admin':raise HTTPException(403)
 return s
def parse(raw):return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def e(v):return html.escape(str(v or ''))
@router.get('/permissions')
def page(r:Request):
 s=admin(r);roles=['admin','sales','customs','transport','finance','viewer'];trs=''
 for role in roles:
  cells=''
  for p,label in ACTIONS.items():cells+='<td><form method="post" action="/permissions/set"><input type="hidden" name="csrf" value="'+e(s['csrf'])+'"><input type="hidden" name="role" value="'+role+'"><input type="hidden" name="permission" value="'+p+'"><input type="hidden" name="allowed" value="'+('0' if has_permission({'role':role},p) else '1')+'"><button>'+('✓' if has_permission({'role':role},p) else '—')+'</button></form></td>'
  trs+='<tr><th>'+role+'</th>'+cells+'</tr>'
 heads=''.join('<th>'+e(v)+'</th>' for v in ACTIONS.values());return HTMLResponse('<html lang="ar" dir="rtl"><meta charset="utf-8"><style>body{font-family:Arial;background:#07131f;color:#eef6fb;padding:24px}table{width:100%;border-collapse:collapse;background:#102536}td,th{padding:10px;border:1px solid #28475d}button{padding:8px 14px;background:#22c55e;border:0;border-radius:8px}a{color:white}</style><p><a href="/team">الفريق</a> · <a href="/security">الأمن</a></p><h1>Fine-Grained Permissions</h1><p>انقر لتفعيل أو إلغاء الصلاحية. التغيير يطبق على مستوى الخادم.</p><table><tr><th>الدور</th>'+heads+'</tr>'+trs+'</table></html>')
@router.post('/permissions/set')
async def setp(r:Request):
 s=admin(r);d=parse(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 role=d.get('role');p=d.get('permission');allow=1 if d.get('allowed')=='1' else 0
 if role not in DEFAULT or p not in ACTIONS:raise HTTPException(400)
 if role=='admin' and p=='manage_users' and not allow:raise HTTPException(400,'Admin user management cannot be disabled here')
 execute('INSERT INTO role_permissions(role,permission,allowed,updated_by,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(role,permission) DO UPDATE SET allowed=excluded.allowed,updated_by=excluded.updated_by,updated_at=excluded.updated_at',(role,p,allow,s['user_id'],utcnow()));log(s['user_id'],'permission_change','role',None,role+':'+p+'='+str(allow));return RedirectResponse('/permissions',303)
@router.get('/api/v7/permissions')
def api(r:Request):
 s=admin(r);return {'actions':ACTIONS,'effective':{role:{p:has_permission({'role':role},p) for p in ACTIONS} for role in DEFAULT}}
