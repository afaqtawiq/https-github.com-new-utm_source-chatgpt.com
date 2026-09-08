import html
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import get_session,rows,one,execute,log,utcnow
router=APIRouter()
def esc(v):return html.escape(str(v or ''))
def auth(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s
def page(b):return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مركز المبيعات</title><style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}.w{max-width:1300px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:18px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.k{background:#0b1d2b;padding:18px;border-radius:12px}.k b{font-size:26px;display:block;margin-top:8px}.btn{display:inline-block;padding:9px 12px;border-radius:9px;background:#22c55e;color:#04130a;text-decoration:none;font-weight:700}.nav a{color:white;margin-left:12px}table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #28475d;text-align:right}.scroll{overflow:auto}.muted{color:#9fb4c4}</style><body><div class="w">'+b+'</div></body></html>')
def nav():return '<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/discovery">الاكتشاف</a><a href="/sales-copilot">Sales Copilot</a><a href="/outbound">الرسائل</a><a href="/approvals">الموافقات</a><a href="/activity">السجل</a></div>'
@router.get('/sales-center')
def sales_center(request:Request):
 auth(request)
 total=one("SELECT COUNT(*) n FROM opportunities WHERE stage<>'test'")['n'];hot=one("SELECT COUNT(*) n FROM opportunities WHERE score>=70 AND stage NOT IN ('won','lost','test')")['n'];pending=one("SELECT COUNT(*) n FROM outbound_messages WHERE status='pending_approval'")['n'];sent=one("SELECT COUNT(*) n FROM outbound_messages WHERE status='sent'")['n'];won=one("SELECT COUNT(*) n FROM opportunities WHERE stage='won'")['n'];overdue=one("SELECT COUNT(*) n FROM sales_followups WHERE status='open' AND due_at<NOW()")['n'];contacts=one('SELECT COUNT(*) n FROM sales_contacts WHERE verified=1')['n']
 data=rows("SELECT o.id,o.company_name,o.score,o.stage,i.priority,i.services,m.id message_id,m.status message_status,(SELECT MIN(f.due_at) FROM sales_followups f WHERE f.opportunity_id=o.id AND f.status='open') next_followup FROM opportunities o LEFT JOIN opportunity_intelligence i ON i.opportunity_id=o.id LEFT JOIN LATERAL (SELECT * FROM outbound_messages x WHERE x.opportunity_id=o.id ORDER BY x.id DESC LIMIT 1) m ON true WHERE o.stage<>'test' ORDER BY o.score DESC,o.id DESC LIMIT 100")
 trs=''.join('<tr><td><a href="/sales-workspace/'+str(x['id'])+'" style="color:white;font-weight:bold">'+esc(x['company_name'])+'</a></td><td>'+str(x['score'])+'</td><td>'+esc(x.get('priority'))+'</td><td>'+esc(x['stage'])+'</td><td>'+esc(x.get('services'))+'</td><td>'+esc(x.get('message_status') or 'لا توجد')+'</td><td>'+esc(x.get('next_followup') or '—')+'</td><td><a class="btn" href="/sales-workspace/'+str(x['id'])+'">ملف العميل</a></td></tr>' for x in data)
 b=nav()+'<h1>مركز مبيعات آفاق طويق</h1><p class="muted">من إشارة الشراء إلى Decision Maker والعرض والمتابعة وإغلاق الصفقة.</p><div class="grid"><div class="k">الفرص<b>'+str(total)+'</b></div><div class="k">فرص ساخنة 70+<b>'+str(hot)+'</b></div><div class="k">جهات اتصال موثقة<b>'+str(contacts)+'</b></div><div class="k">متابعات متأخرة<b>'+str(overdue)+'</b></div><div class="k">بانتظار الموافقة<b>'+str(pending)+'</b></div><div class="k">رسائل مرسلة<b>'+str(sent)+'</b></div><div class="k">صفقات فائزة<b>'+str(won)+'</b></div></div><div class="card scroll"><table><tr><th>الجهة</th><th>Score</th><th>الأولوية</th><th>المرحلة</th><th>الخدمات</th><th>التواصل</th><th>المتابعة التالية</th><th></th></tr>'+trs+'</table></div>'
 return page(b)
@router.post('/sales-center/{oid}/stage/{stage}')
def stage(oid:int,stage:str,request:Request):
 s=auth(request);allowed={'new','qualified','proposal','contacted','negotiation','won','lost'}
 if stage not in allowed:raise HTTPException(400,'Invalid stage')
 execute('UPDATE opportunities SET stage=?,updated_at=? WHERE id=?',(stage,utcnow(),oid));log(s['user_id'],'sales_stage_change','opportunity',oid,'Stage -> '+stage);return RedirectResponse('/sales-center',303)
@router.get('/api/v7/sales-center')
def api(request:Request):
 auth(request);return {'funnel':rows("SELECT stage,COUNT(*) count,COALESCE(SUM(estimated_value),0) value FROM opportunities WHERE stage<>'test' GROUP BY stage ORDER BY stage"),'outbound':rows("SELECT status,COUNT(*) count FROM outbound_messages GROUP BY status ORDER BY status"),'outcomes':rows("SELECT outcome,currency,COUNT(*) count,COALESCE(SUM(realized_value),0) realized_value FROM sales_outcomes GROUP BY outcome,currency"),'followups':{'overdue':one("SELECT COUNT(*) n FROM sales_followups WHERE status='open' AND due_at<NOW()")['n']}}
