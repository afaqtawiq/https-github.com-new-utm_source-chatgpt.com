import html,datetime
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse
from app.storage import get_session,rows,one,utcnow
router=APIRouter()
def e(v):return html.escape(str(v or ''))
def auth(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s
def shell(b):return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Arial;background:#06121d;color:#eef6fb;margin:0}.w{max-width:1450px;margin:auto;padding:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.card,.k{background:#102536;border:1px solid #28475d;border-radius:15px;padding:18px;margin:12px 0}.k b{display:block;font-size:24px;margin-top:8px}table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #28475d;text-align:right}.btn{padding:8px 11px;border-radius:8px;background:#22c55e;color:#04130a;text-decoration:none;font-weight:bold}.nav a{color:white;margin-left:12px}.muted{color:#9fb4c4}.green{color:#86efac}.amber{color:#fde68a}</style><body><div class="w">'+b+'</div></body></html>')
def nav():return '<div class="nav"><a href="/revenue-growth">Revenue Growth</a><a href="/customer-success">Customer Success</a><a href="/customers360">Customer 360</a><a href="/ceo">CEO Command</a></div>'
def engine():
 now=utcnow();acc=rows('SELECT * FROM accounts');out=[]
 for a in acc:
  ships=rows('SELECT s.*,x.actual_cost FROM shipments s LEFT JOIN shipment_operations x ON x.shipment_id=s.id WHERE s.account_id=? ORDER BY s.created_at DESC',(a['id'],));opps=rows('SELECT * FROM opportunities WHERE account_id=?',(a['id'],));
  if not ships and not opps:continue
  bycur={};services=set()
  for s in ships:
   services.add(str(s['service_type']).lower());d=bycur.setdefault(s['currency'],{'rev':0,'cost':0,'jobs':0});d['rev']+=float(s['revenue'] or 0);d['cost']+=float(s.get('actual_cost') or 0);d['jobs']+=1
  last=ships[0]['created_at'] if ships else None;days=(now-last).days if last else 999;score=min(100,(len(ships)*8)+(20 if days<45 else 5)+(15 if len(services)<3 and ships else 0)+(15 if any(x['stage']=='won' for x in opps) else 0));kind='repeat_order' if days>30 and ships else ('cross_sell' if ships and len(services)<3 else 'upsell');action={'repeat_order':'تحقق من دورة إعادة الطلب وأنشئ متابعة داخلية','cross_sell':'راجع خدمة إضافية مناسبة لهذا العميل','upsell':'راجع توسيع حجم الخدمة أو نطاقها'}[kind]
  for cur,d in bycur.items():
   avg=d['rev']/d['jobs'] if d['jobs'] else 0;prob=.65 if score>=70 else .45 if score>=45 else .25;forecast=avg*prob;out.append({'id':a['id'],'name':a['name'],'currency':cur,'jobs':d['jobs'],'revenue':d['rev'],'profit':d['rev']-d['cost'],'score':score,'kind':kind,'probability':int(prob*100),'forecast':forecast,'next_action':action})
 return sorted(out,key=lambda x:(-x['score'],-x['forecast']))
@router.get('/revenue-growth')
def page(request:Request):
 auth(request);data=engine();cur={}
 for x in data:
  d=cur.setdefault(x['currency'],{'forecast':0,'revenue':0,'profit':0});d['forecast']+=x['forecast'];d['revenue']+=x['revenue'];d['profit']+=x['profit']
 cards=''.join('<div class="k">'+e(c)+' Growth Forecast<b>'+format(v['forecast'],',.2f')+'</b><span class="muted">Historical revenue '+format(v['revenue'],',.2f')+'</span></div>' for c,v in cur.items()) or '<div class="k">لا توجد بيانات كافية بعد</div>';tr=''.join('<tr><td><a href="/customers360/'+str(x['id'])+'">'+e(x['name'])+'</a></td><td>'+e(x['kind'])+'</td><td>'+str(x['score'])+'</td><td>'+str(x['probability'])+'%</td><td>'+format(x['forecast'],',.2f')+' '+e(x['currency'])+'</td><td>'+format(x['profit'],',.2f')+'</td><td>'+e(x['next_action'])+'</td></tr>' for x in data)
 return shell(nav()+'<h1>AI Revenue Growth Engine — آفاق طويق</h1><p class="muted">Forecast احتمالي داخلي مبني على بيانات النظام التاريخية وقواعد قابلة للتفسير، وليس التزامًا ماليًا أو توقعًا مضمونًا.</p><div class="grid">'+cards+'</div><div class="card"><h2>Growth Opportunity Ranking</h2><table><tr><th>العميل</th><th>نوع النمو</th><th>Growth Score</th><th>احتمال</th><th>Forecast</th><th>الربح التاريخي</th><th>Next Best Action</th></tr>'+tr+'</table></div>')
@router.get('/api/v7/revenue-growth')
def api(request:Request):
 auth(request);return {'growth_opportunities':engine(),'method':'rule_based_explainable_probability','external_actions':'human_approval_required'}
