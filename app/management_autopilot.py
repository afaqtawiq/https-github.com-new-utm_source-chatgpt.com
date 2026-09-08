import html
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse
from app.storage import get_session,rows,one,utcnow
router=APIRouter()
def e(v):return html.escape(str(v or ''))
def auth(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s
def shell(b):return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Management Autopilot</title><style>body{font-family:Arial;background:#050f18;color:#edf7fb;margin:0}.w{max-width:1500px;margin:auto;padding:24px}.hero,.card,.k{background:#102536;border:1px solid #28475d;border-radius:16px;padding:18px;margin:12px 0}.hero{background:linear-gradient(135deg,#102c3d,#0b1b28)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.k b{display:block;font-size:25px;margin-top:8px}table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #28475d;text-align:right}.btn{padding:8px 11px;border-radius:8px;background:#22c55e;color:#04130a;text-decoration:none;font-weight:bold}.nav a{color:white;margin-left:12px}.red{color:#fca5a5}.amber{color:#fde68a}.green{color:#86efac}.muted{color:#9fb4c4}</style><body><div class="w">'+b+'</div></body></html>')
def nav():return '<div class="nav"><a href="/management-autopilot">Management Autopilot</a><a href="/ceo">CEO</a><a href="/revenue-growth">Growth</a><a href="/customer-success">Customer Success</a><a href="/control-tower">Operations</a></div>'
def priorities():
 now=utcnow();items=[]
 for x in rows("SELECT a.id,a.kind,a.entity_type,a.entity_id,a.notes,a.created_at FROM approvals a WHERE a.status='pending' ORDER BY a.created_at"):
  items.append({'priority':95,'area':'Approval','title':'اعتماد معلق: '+x['kind'],'detail':x.get('notes') or x['entity_type']+' #'+str(x['entity_id']),'url':'/approvals'})
 for x in rows("SELECT e.shipment_id,e.severity,e.summary,s.reference FROM shipment_exceptions e JOIN shipments s ON s.id=e.shipment_id WHERE e.status='open'"):
  p=100 if x['severity']=='high' else 85 if x['severity']=='medium' else 65;items.append({'priority':p,'area':'Operations','title':'استثناء تشغيلي '+x['reference'],'detail':x.get('summary') or x['severity'],'url':'/control-tower/'+str(x['shipment_id'])})
 for x in rows("SELECT t.shipment_id,t.title,t.owner,t.due_at,s.reference FROM operations_tasks t JOIN shipments s ON s.id=t.shipment_id WHERE t.status='open' AND t.due_at<? ORDER BY t.due_at",(now,)):
  items.append({'priority':92,'area':'Operations','title':'مهمة متأخرة '+x['reference'],'detail':x['title']+' — '+(x.get('owner') or 'غير مسند'),'url':'/control-tower/'+str(x['shipment_id'])})
 for x in rows("SELECT f.opportunity_id,f.kind,f.due_at,f.notes,o.company_name FROM sales_followups f JOIN opportunities o ON o.id=f.opportunity_id WHERE f.status='open' AND f.due_at<=? ORDER BY f.due_at LIMIT 30",(now,)):
  items.append({'priority':82,'area':'Sales','title':'متابعة مستحقة: '+x['company_name'],'detail':x.get('notes') or x['kind'],'url':'/sales-center'})
 for x in rows("SELECT q.id,q.quote_number,q.commercial_status,q.sell_price,q.currency,o.company_name FROM sales_quotes q JOIN opportunities o ON o.id=q.opportunity_id WHERE COALESCE(q.commercial_status,'draft') IN ('draft','pending') ORDER BY q.updated_at LIMIT 20"):
  items.append({'priority':78,'area':'Quote','title':'عرض يحتاج قرار: '+x['quote_number'],'detail':x['company_name']+' — '+format(float(x['sell_price'] or 0),',.2f')+' '+x['currency'],'url':'/quote-workflow/'+str(x['id'])})
 for x in rows("SELECT o.id,o.company_name,o.score,o.estimated_value,o.currency FROM opportunities o WHERE o.stage NOT IN ('won','lost','test') AND o.score>=70 ORDER BY o.score DESC,o.estimated_value DESC LIMIT 20"):
  items.append({'priority':min(90,int(x['score'])),'area':'Growth','title':'فرصة عالية: '+x['company_name'],'detail':'Score '+str(x['score'])+' — '+format(float(x['estimated_value'] or 0),',.2f')+' '+x['currency'],'url':'/sales-center'})
 return sorted(items,key=lambda x:-x['priority'])
@router.get('/management-autopilot')
def page(request:Request):
 auth(request);p=priorities();critical=sum(1 for x in p if x['priority']>=90);sales=sum(1 for x in p if x['area'] in ('Sales','Growth','Quote'));ops=sum(1 for x in p if x['area']=='Operations');approval=sum(1 for x in p if x['area']=='Approval');tr=''.join('<tr><td class="'+('red' if x['priority']>=90 else 'amber' if x['priority']>=75 else 'green')+'"><b>'+str(x['priority'])+'</b></td><td>'+e(x['area'])+'</td><td>'+e(x['title'])+'</td><td>'+e(x['detail'])+'</td><td><a class="btn" href="'+x['url']+'">تنفيذ</a></td></tr>' for x in p[:60]);top=p[:5];brief=''.join('<li><b>'+e(x['title'])+'</b> — '+e(x['detail'])+'</li>' for x in top) or '<li>لا توجد أولويات حرجة مسجلة حاليًا.</li>'
 return shell(nav()+'<div class="hero"><h1>AI Management Autopilot — آفاق طويق</h1><p class="muted">قائمة يومية قابلة للتفسير لما يحتاج انتباه الإدارة. المحرك يوصي ويرتب فقط ولا ينفذ تواصلًا خارجيًا أو اعتمادًا تلقائيًا.</p><h2>موجز الإدارة اليوم</h2><ol>'+brief+'</ol></div><div class="grid"><div class="k">حرجة الآن<b>'+str(critical)+'</b></div><div class="k">مبيعات ونمو<b>'+str(sales)+'</b></div><div class="k">تشغيل<b>'+str(ops)+'</b></div><div class="k">اعتمادات<b>'+str(approval)+'</b></div><div class="k">إجمالي الأولويات<b>'+str(len(p))+'</b></div></div><div class="card"><h2>ماذا يجب أن نفعل اليوم؟</h2><table><tr><th>Priority</th><th>المجال</th><th>القرار/المهمة</th><th>التفاصيل</th><th></th></tr>'+tr+'</table></div>')
@router.get('/api/v7/management-autopilot')
def api(request:Request):
 auth(request);return {'generated_at':utcnow().isoformat(),'priorities':priorities(),'policy':{'recommend_only':True,'auto_approve':False,'auto_send':False,'human_approval_required':True}}
