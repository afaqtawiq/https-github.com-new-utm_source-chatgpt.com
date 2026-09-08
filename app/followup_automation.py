import html,datetime
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import get_session,rows,one,execute,log,utcnow
router=APIRouter()
def esc(v):return html.escape(str(v or ''))
def auth(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s
def shell(b):return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}.w{max-width:1300px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:18px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.k{background:#0b1d2b;padding:18px;border-radius:12px}.k b{font-size:25px;display:block;margin-top:8px}.btn{display:inline-block;padding:9px 12px;border:0;border-radius:9px;background:#22c55e;color:#04130a;text-decoration:none;font-weight:bold}table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #28475d;text-align:right}.muted{color:#9fb4c4}.nav a{color:white;margin-left:12px}</style><body><div class="w">'+b+'</div></body></html>')
def nav():return '<div class="nav"><a href="/sales-center">مركز المبيعات</a><a href="/sales-today">مهام اليوم</a><a href="/sales-performance">Conversion & Revenue</a><a href="/outbound">الرسائل</a><a href="/dashboard">الرئيسية</a></div>'
@router.get('/sales-today')
def today(request:Request):
 auth(request);now=utcnow();end=now+datetime.timedelta(days=1);due=rows("SELECT f.*,o.company_name,o.score FROM sales_followups f JOIN opportunities o ON o.id=f.opportunity_id WHERE f.status='open' AND f.due_at<=? ORDER BY f.due_at",(end,));stale=rows("SELECT o.id,o.company_name,o.score,m.sent_at FROM opportunities o JOIN LATERAL (SELECT * FROM outbound_messages x WHERE x.opportunity_id=o.id AND x.status='sent' ORDER BY x.sent_at DESC LIMIT 1) m ON true WHERE o.stage NOT IN ('won','lost','test') AND m.sent_at<? AND NOT EXISTS(SELECT 1 FROM sales_followups f WHERE f.opportunity_id=o.id AND f.status='open') ORDER BY m.sent_at",(now-datetime.timedelta(days=3),))
 tr=''.join('<tr><td>'+esc(x['company_name'])+'</td><td>'+esc(x['kind'])+'</td><td>'+esc(x['due_at'])+'</td><td>'+esc(x['notes'])+'</td><td><a class="btn" href="/sales-workspace/'+str(x['opportunity_id'])+'">فتح</a></td></tr>' for x in due);sr=''.join('<tr><td>'+esc(x['company_name'])+'</td><td>'+str(x['score'])+'</td><td>'+esc(x['sent_at'])+'</td><td><form method="post" action="/sales-automation/'+str(x['id'])+'/sequence"><button class="btn">إنشاء تسلسل متابعة</button></form></td></tr>' for x in stale)
 return shell(nav()+'<h1>مهام المبيعات اليوم</h1><div class="card"><b>المتابعات المستحقة والمتأخرة:</b> '+str(len(due))+'<p class="muted">لا يوجد إرسال تلقائي. التسلسل ينشئ مهام ومسودات متابعة فقط، وكل إرسال يبقى خاضعًا للموافقة.</p></div><div class="card"><h2>المهام</h2><table><tr><th>العميل</th><th>النوع</th><th>الموعد</th><th>المهمة</th><th></th></tr>'+tr+'</table></div><div class="card"><h2>مرّ 3 أيام على الإرسال ولا توجد متابعة مفتوحة</h2><table><tr><th>العميل</th><th>Score</th><th>آخر إرسال</th><th></th></tr>'+sr+'</table></div>')
@router.post('/sales-automation/{oid}/sequence')
def sequence(oid:int,request:Request):
 s=auth(request);o=one('SELECT * FROM opportunities WHERE id=?',(oid,));
 if not o:raise HTTPException(404)
 if o['stage'] in ('won','lost','test'):raise HTTPException(409,'Closed opportunity')
 existing=one("SELECT COUNT(*) n FROM sales_followups WHERE opportunity_id=? AND status='open'",(oid,))['n']
 if existing:return RedirectResponse('/sales-workspace/'+str(oid),303)
 now=utcnow();steps=[(3,'follow_up','متابعة أولى: تحقق من الرد وراجع الاحتياج.'),(7,'value_followup','متابعة ثانية: أضف قيمة مرتبطة بالخدمة المطلوبة دون وعود غير موثقة.'),(14,'final_followup','متابعة أخيرة: اطلب قرارًا أو موعدًا مناسبًا للعودة.')]
 for days,kind,note in steps:execute('INSERT INTO sales_followups(opportunity_id,kind,due_at,status,notes,created_by,created_at) VALUES(?,?,?,?,?,?,?)',(oid,kind,now+datetime.timedelta(days=days),'open',note,s['user_id'],now))
 log(s['user_id'],'create_followup_sequence','opportunity',oid,'3-step human-approved follow-up sequence created');return RedirectResponse('/sales-workspace/'+str(oid),303)
@router.get('/sales-performance')
def performance(request:Request):
 auth(request);total=one("SELECT COUNT(*) n FROM opportunities WHERE stage<>'test'")['n'];qualified=one("SELECT COUNT(*) n FROM opportunities WHERE stage IN ('qualified','proposal','contacted','negotiation','won')")['n'];sent=one("SELECT COUNT(DISTINCT opportunity_id) n FROM outbound_messages WHERE status='sent'")['n'];won=one("SELECT COUNT(*) n FROM opportunities WHERE stage='won'")['n'];lost=one("SELECT COUNT(*) n FROM opportunities WHERE stage='lost'")['n'];rate=(won/(won+lost)*100) if won+lost else 0;vals=rows("SELECT currency,COALESCE(SUM(realized_value),0) value,COUNT(*) deals FROM sales_outcomes WHERE outcome='won' GROUP BY currency ORDER BY currency");v=''.join('<div class="k">إيراد محقق '+esc(x['currency'])+'<b>'+format(x['value'],',.2f')+'</b><span>'+str(x['deals'])+' صفقة</span></div>' for x in vals) or '<div class="k">الإيراد المحقق<b>0</b></div>'
 funnel=rows("SELECT stage,COUNT(*) count FROM opportunities WHERE stage<>'test' GROUP BY stage ORDER BY stage");fr=''.join('<tr><td>'+esc(x['stage'])+'</td><td>'+str(x['count'])+'</td></tr>' for x in funnel)
 return shell(nav()+'<h1>Conversion & Revenue</h1><div class="grid"><div class="k">إجمالي الفرص<b>'+str(total)+'</b></div><div class="k">مؤهلة وما بعدها<b>'+str(qualified)+'</b></div><div class="k">تم التواصل معها<b>'+str(sent)+'</b></div><div class="k">Won<b>'+str(won)+'</b></div><div class="k">Lost<b>'+str(lost)+'</b></div><div class="k">Win Rate<b>'+format(rate,'.1f')+'%</b></div>'+v+'</div><div class="card"><h2>قمع المبيعات</h2><table><tr><th>المرحلة</th><th>العدد</th></tr>'+fr+'</table></div><div class="card muted">القيم المحققة مفصولة حسب العملة ولا يتم جمع العملات المختلفة في رقم واحد.</div>')
@router.get('/api/v7/sales-performance')
def api(request:Request):
 auth(request);return {'funnel':rows("SELECT stage,COUNT(*) count FROM opportunities WHERE stage<>'test' GROUP BY stage"),'realized_revenue':rows("SELECT currency,SUM(realized_value) value FROM sales_outcomes WHERE outcome='won' GROUP BY currency"),'followups':{'overdue':one("SELECT COUNT(*) n FROM sales_followups WHERE status='open' AND due_at<NOW()")['n'],'today':one("SELECT COUNT(*) n FROM sales_followups WHERE status='open' AND due_at>=CURRENT_DATE AND due_at<CURRENT_DATE+INTERVAL '1 day'")['n']}}
