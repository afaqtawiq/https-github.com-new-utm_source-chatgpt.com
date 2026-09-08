import html,datetime
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse
from app.storage import get_session,rows,one,utcnow
router=APIRouter()
SERVICES=['customs_clearance','transport','shipping','warehousing','door_to_door']
def e(v):return html.escape(str(v or ''))
def auth(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s
def shell(b):return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Arial;background:#06121d;color:#eef6fb;margin:0}.w{max-width:1450px;margin:auto;padding:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.card,.k{background:#102536;border:1px solid #28475d;border-radius:15px;padding:18px;margin:12px 0}.k b{display:block;font-size:24px;margin-top:8px}table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #28475d;text-align:right}.btn{padding:8px 11px;border-radius:8px;background:#22c55e;color:#04130a;text-decoration:none;font-weight:bold}.nav a{color:white;margin-left:12px}.red{color:#fca5a5}.amber{color:#fde68a}.green{color:#86efac}.muted{color:#9fb4c4}</style><body><div class="w">'+b+'</div></body></html>')
def nav():return '<div class="nav"><a href="/customer-success">Customer Success</a><a href="/customers360">Customer 360</a><a href="/ceo">CEO Command</a><a href="/sales-center">المبيعات</a></div>'
def intelligence():
 now=utcnow();accounts=rows('SELECT * FROM accounts ORDER BY name');out=[]
 for a in accounts:
  ships=rows('SELECT s.*,x.actual_cost FROM shipments s LEFT JOIN shipment_operations x ON x.shipment_id=s.id WHERE s.account_id=? ORDER BY s.created_at DESC',(a['id'],));opps=rows('SELECT * FROM opportunities WHERE account_id=? ORDER BY created_at DESC',(a['id'],));
  if not ships and not opps:continue
  last_ship=ships[0]['created_at'] if ships else None;days=(now-last_ship).days if last_ship else 999;used={str(x['service_type']).lower() for x in ships};missing=[s for s in SERVICES if s not in used];rev=sum(float(x['revenue'] or 0) for x in ships);cost=sum(float(x.get('actual_cost') or 0) for x in ships);margin=((rev-cost)/rev*100) if rev else 0;won=sum(1 for x in opps if x['stage']=='won');lost=sum(1 for x in opps if x['stage']=='lost');risk=0;reasons=[]
  if days>90:risk+=45;reasons.append('لا توجد عملية منذ أكثر من 90 يومًا')
  elif days>45:risk+=25;reasons.append('انخفاض النشاط منذ أكثر من 45 يومًا')
  if ships and margin<10:risk+=30;reasons.append('هامش الربحية أقل من 10%')
  if lost>won and lost>0:risk+=20;reasons.append('الفرص الخاسرة أعلى من الفائزة')
  if risk>=50:segment='at_risk';action='مراجعة الحساب والتواصل لإعادة التنشيط بعد موافقة بشرية'
  elif missing and ships:segment='growth';action='مراجعة فرصة Cross-sell: '+', '.join(missing[:2])
  elif days>30:segment='reorder';action='التحقق من موعد إعادة الطلب المتوقع'
  else:segment='healthy';action='الحفاظ على الخدمة ومراجعة فرص التوسع'
  out.append({'id':a['id'],'name':a['name'],'country':a.get('country'),'shipments':len(ships),'days':days,'revenue':rev,'cost':cost,'margin':round(margin,1),'risk':min(risk,100),'segment':segment,'next_action':action,'reasons':'؛ '.join(reasons) or 'لا توجد إشارة خطر قوية','missing':missing})
 return sorted(out,key=lambda x:(-x['risk'],-x['revenue']))
@router.get('/customer-success')
def page(request:Request):
 auth(request);data=intelligence();atrisk=sum(1 for x in data if x['segment']=='at_risk');growth=sum(1 for x in data if x['segment']=='growth');reorder=sum(1 for x in data if x['segment']=='reorder');tr=''.join('<tr><td><a href="/customers360/'+str(x['id'])+'">'+e(x['name'])+'</a></td><td class="'+('red' if x['segment']=='at_risk' else 'green' if x['segment']=='healthy' else 'amber')+'">'+e(x['segment'])+'</td><td>'+str(x['risk'])+'</td><td>'+str(x['shipments'])+'</td><td>'+('—' if x['days']==999 else str(x['days']))+'</td><td>'+str(x['margin'])+'%</td><td>'+e(x['next_action'])+'</td><td>'+e(x['reasons'])+'</td></tr>' for x in data)
 return shell(nav()+'<h1>Customer Success & Retention Engine — آفاق طويق</h1><p class="muted">تحليل داخلي فقط؛ لا يتم إرسال أي تواصل خارجي تلقائيًا.</p><div class="grid"><div class="k">حسابات تحتاج تدخل<b>'+str(atrisk)+'</b></div><div class="k">فرص Cross-sell<b>'+str(growth)+'</b></div><div class="k">مرشحة لإعادة الطلب<b>'+str(reorder)+'</b></div><div class="k">إجمالي الحسابات المحللة<b>'+str(len(data))+'</b></div></div><div class="card"><h2>Next Best Action</h2><table><tr><th>العميل</th><th>التصنيف</th><th>Risk</th><th>العمليات</th><th>أيام منذ آخر عملية</th><th>الهامش</th><th>الإجراء المقترح</th><th>السبب</th></tr>'+tr+'</table></div>')
@router.get('/api/v7/customer-success')
def api(request:Request):
 auth(request);return {'customers':intelligence(),'policy':{'external_actions':'human_approval_required','auto_send':False}}
