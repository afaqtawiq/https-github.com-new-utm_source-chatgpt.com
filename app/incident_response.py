import html,urllib.parse,datetime
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import db,get_session,one,rows,execute,log,utcnow
from app.mfa_stepup import recent_stepup
router=APIRouter()
def e(v):return html.escape(str(v or ''))
def parse(raw):return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def admin(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s or s.get('role')!='admin':raise HTTPException(403)
 return s
def init():
 with db() as c:
  c.execute('''CREATE TABLE IF NOT EXISTS security_incidents(id BIGSERIAL PRIMARY KEY,user_id BIGINT,severity TEXT NOT NULL,event_type TEXT NOT NULL,summary TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',assigned_to BIGINT,source TEXT NOT NULL DEFAULT 'internal',evidence TEXT,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,resolved_at TIMESTAMPTZ)''')
init()
def ensure_alerts():
 now=utcnow();since=now-datetime.timedelta(minutes=15);fails=rows('SELECT user_id,COUNT(*) n FROM mfa_attempts WHERE success=0 AND created_at>=? GROUP BY user_id HAVING COUNT(*)>=5',(since,))
 for x in fails:
  exists=one("SELECT id FROM security_incidents WHERE user_id=? AND event_type='mfa_bruteforce' AND status!='resolved'",(x['user_id'],))
  if not exists:execute('INSERT INTO security_incidents(user_id,severity,event_type,summary,status,source,evidence,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(x['user_id'],'high','mfa_bruteforce','Repeated failed MFA verification','open','internal','failed_attempts='+str(x['n']),now,now))
def page(b):return HTMLResponse('<html lang="ar" dir="rtl"><meta charset="utf-8"><style>body{font-family:Arial;background:#07131f;color:#eef6fb;padding:24px}.w{max-width:1200px;margin:auto}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:18px;margin:12px 0}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #28475d;text-align:right}.critical{color:#f43f5e}.high{color:#fb7185}.medium{color:#fbbf24}.low{color:#4ade80}button,select{padding:8px;border-radius:8px}a{color:#dff6ff}</style><div class="w">'+b+'</div></html>')
@router.get('/incidents')
def incidents(r:Request):
 s=admin(r);ensure_alerts();xs=rows('SELECT i.*,u.email FROM security_incidents i LEFT JOIN users u ON u.id=i.user_id ORDER BY CASE i.severity WHEN \'critical\' THEN 1 WHEN \'high\' THEN 2 WHEN \'medium\' THEN 3 ELSE 4 END,i.created_at DESC LIMIT 100');b='<p><a href="/soc">SOC</a> · <a href="/security">Security</a></p><h1>Security Incidents</h1><div class="card"><table><tr><th>Severity</th><th>المستخدم</th><th>الحادث</th><th>الحالة</th><th>إجراء</th></tr>'
 for x in xs:
  b+='<tr><td class="'+e(x['severity'])+'">'+e(x['severity'])+'</td><td>'+e(x.get('email') or x.get('user_id'))+'</td><td>'+e(x['summary'])+'</td><td>'+e(x['status'])+'</td><td><form method="post" action="/incidents/'+str(x['id'])+'/status"><input type="hidden" name="csrf" value="'+e(s['csrf'])+'"><select name="status"><option>open</option><option>investigating</option><option>resolved</option></select><button>تحديث</button></form></td></tr>'
 b+='</table></div><div class="card">إجراءات الاحتواء التي تؤثر على حساب مستخدم تتطلب Step-up حديثًا ولا تُنفذ تلقائيًا.</div>';return page(b)
@router.post('/incidents/{iid}/status')
async def status(iid:int,r:Request):
 s=admin(r);d=parse(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 st=d.get('status');
 if st not in ('open','investigating','resolved'):raise HTTPException(400)
 now=utcnow();execute('UPDATE security_incidents SET status=?,updated_at=?,resolved_at=? WHERE id=?',(st,now,now if st=='resolved' else None,iid));log(s['user_id'],'security_incident_status','incident',iid,st);return RedirectResponse('/incidents',303)
@router.post('/incidents/{iid}/contain')
async def contain(iid:int,r:Request):
 s=admin(r);d=parse(await r.body())
 if d.get('csrf')!=s['csrf']:raise HTTPException(403)
 if not recent_stepup(s['id']):raise HTTPException(428,'Recent MFA step-up required')
 x=one('SELECT * FROM security_incidents WHERE id=?',(iid,));
 if not x:raise HTTPException(404)
 uid=x.get('user_id');
 if not uid or uid==s['user_id']:raise HTTPException(400,'Cannot contain this account from this incident')
 execute('DELETE FROM sessions WHERE user_id=?',(uid,));execute('UPDATE users SET is_active=0 WHERE id=?',(uid,));now=utcnow();execute("UPDATE security_incidents SET status='investigating',updated_at=? WHERE id=?",(now,iid));log(s['user_id'],'security_containment','user',uid,'Sessions revoked and account suspended from incident '+str(iid));return RedirectResponse('/incidents',303)
@router.get('/api/v7/incidents')
def api(r:Request):
 admin(r);ensure_alerts();return {'incidents':rows('SELECT id,user_id,severity,event_type,summary,status,created_at,updated_at,resolved_at FROM security_incidents ORDER BY created_at DESC LIMIT 100')}
