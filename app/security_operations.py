import html,datetime
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse
from app.storage import db,get_session,one,rows,utcnow
router=APIRouter()
def e(v):return html.escape(str(v or ''))
def sess(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 if s.get('role')!='admin':raise HTTPException(403)
 return s
def init():
 with db() as c:
  c.execute('''CREATE TABLE IF NOT EXISTS security_alerts(id BIGSERIAL PRIMARY KEY,user_id BIGINT,severity TEXT NOT NULL,event_type TEXT NOT NULL,summary TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',source TEXT NOT NULL DEFAULT 'internal',created_at TIMESTAMPTZ NOT NULL,resolved_at TIMESTAMPTZ)''')
init()
def risk_score():
 since=utcnow()-datetime.timedelta(hours=24);f=one('SELECT COUNT(*) n FROM mfa_attempts WHERE success=0 AND created_at>=?',(since,)) or {'n':0};a=one("SELECT COUNT(*) n FROM activity WHERE action IN ('admin_mfa_reset','permissions_updated','mfa_recovery_used') AND created_at>=?",(since,)) or {'n':0};sessions=one('SELECT COUNT(*) n FROM sessions WHERE expires_at>?',(utcnow(),)) or {'n':0};score=min(100,int(f['n'] or 0)*8+int(a['n'] or 0)*10+max(0,int(sessions['n'] or 0)-5)*3);return score,int(f['n'] or 0),int(a['n'] or 0),int(sessions['n'] or 0)
def page(body):return HTMLResponse('<html lang="ar" dir="rtl"><meta charset="utf-8"><style>body{font-family:Arial;background:#07131f;color:#eef6fb;padding:24px}.w{max-width:1200px;margin:auto}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:18px;margin:12px 0}.k{font-size:30px;font-weight:bold}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #28475d;text-align:right}.high{color:#fb7185}.medium{color:#fbbf24}.low{color:#4ade80}a{color:#dff6ff}</style><div class="w">'+body+'</div></html>')
@router.get('/soc')
def soc(r:Request):
 sess(r);score,failed,changes,active=risk_score();level='high' if score>=70 else ('medium' if score>=35 else 'low');attempts=rows('SELECT m.*,u.email FROM mfa_attempts m LEFT JOIN users u ON u.id=m.user_id ORDER BY m.created_at DESC LIMIT 30');acts=rows("SELECT a.*,u.email FROM activity a LEFT JOIN users u ON u.id=a.user_id WHERE a.action IN ('mfa_enabled','mfa_stepup','mfa_recovery_used','mfa_recovery_regenerated','admin_mfa_reset','permissions_updated','user_created','user_disabled') ORDER BY a.created_at DESC LIMIT 30");b='<p><a href="/dashboard">Dashboard</a> · <a href="/security">Security</a> · <a href="/mfa">MFA</a></p><h1>Security Operations Center</h1><div class="grid"><div class="card"><div>Risk Score / 24h</div><div class="k '+level+'">'+str(score)+'/100</div></div><div class="card"><div>محاولات MFA الفاشلة</div><div class="k">'+str(failed)+'</div></div><div class="card"><div>تغييرات أمنية حساسة</div><div class="k">'+str(changes)+'</div></div><div class="card"><div>الجلسات النشطة</div><div class="k">'+str(active)+'</div></div></div><div class="card"><h2>محاولات MFA الأخيرة</h2><table><tr><th>المستخدم</th><th>النوع</th><th>النتيجة</th><th>IP</th><th>الوقت</th></tr>'
 for x in attempts:b+='<tr><td>'+e(x.get('email') or x.get('user_id'))+'</td><td>'+e(x.get('kind'))+'</td><td>'+('نجاح' if x.get('success') else 'فشل')+'</td><td>'+e(x.get('ip_address'))+'</td><td>'+e(x.get('created_at'))+'</td></tr>'
 b+='</table></div><div class="card"><h2>الأحداث الأمنية</h2><table><tr><th>المستخدم</th><th>الحدث</th><th>الملخص</th><th>الوقت</th></tr>'
 for x in acts:b+='<tr><td>'+e(x.get('email') or x.get('user_id'))+'</td><td>'+e(x.get('action'))+'</td><td>'+e(x.get('summary'))+'</td><td>'+e(x.get('created_at'))+'</td></tr>'
 b+='</table></div><div class="card"><p>Risk Score مؤشر تشغيلي داخلي يعتمد على الأحداث المسجلة خلال آخر 24 ساعة، وليس شهادة امتثال أو نظام كشف اختراق خارجي.</p></div>';return page(b)
@router.get('/api/v7/soc')
def api(r:Request):
 sess(r);score,failed,changes,active=risk_score();return {'risk_score':score,'window_hours':24,'failed_mfa':failed,'sensitive_security_changes':changes,'active_sessions':active,'risk_model':'internal heuristic'}
