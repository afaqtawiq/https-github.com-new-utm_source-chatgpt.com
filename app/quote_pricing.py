import os,html,urllib.parse
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import get_session,rows,one,execute,log,utcnow,db
router=APIRouter()

def ensure_schema():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS quote_cost_items(id BIGSERIAL PRIMARY KEY,quote_id BIGINT NOT NULL REFERENCES sales_quotes(id) ON DELETE CASCADE,item_type TEXT NOT NULL,description TEXT,quantity DOUBLE PRECISION NOT NULL DEFAULT 1,unit_cost DOUBLE PRECISION NOT NULL DEFAULT 0,total_cost DOUBLE PRECISION NOT NULL DEFAULT 0,created_by BIGINT,created_at TIMESTAMPTZ NOT NULL)''')
        for sql in [
            "ALTER TABLE sales_quotes ADD COLUMN IF NOT EXISTS vat_percent DOUBLE PRECISION NOT NULL DEFAULT 0",
            "ALTER TABLE sales_quotes ADD COLUMN IF NOT EXISTS total_before_vat DOUBLE PRECISION NOT NULL DEFAULT 0",
            "ALTER TABLE sales_quotes ADD COLUMN IF NOT EXISTS vat_amount DOUBLE PRECISION NOT NULL DEFAULT 0",
            "ALTER TABLE sales_quotes ADD COLUMN IF NOT EXISTS total_with_vat DOUBLE PRECISION NOT NULL DEFAULT 0",
            "ALTER TABLE sales_quotes ADD COLUMN IF NOT EXISTS min_margin_percent DOUBLE PRECISION NOT NULL DEFAULT 0",
            "ALTER TABLE sales_quotes ADD COLUMN IF NOT EXISTS requires_manager_approval INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE sales_quotes ADD COLUMN IF NOT EXISTS pricing_approval_id BIGINT REFERENCES approvals(id) ON DELETE SET NULL"]:
            c.execute(sql)
ensure_schema()

def esc(v):return html.escape(str(v or ''))
def auth(r):
    s=get_session(r.cookies.get('gla_session'))
    if not s:raise HTTPException(401)
    return s
def parse(raw):return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def nav():return '<div class="nav"><a href="/quotes">عروض الأسعار</a><a href="/sales-center">مركز المبيعات</a><a href="/approvals">الموافقات</a></div>'
def shell(b):return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}.w{max-width:1200px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:18px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}.btn{display:inline-block;padding:9px 12px;border:0;border-radius:9px;background:#22c55e;color:#04130a;text-decoration:none;font-weight:bold;cursor:pointer}.danger{background:#ef4444;color:#fff}.warn{background:#f59e0b;color:#231500}input,select,textarea{width:100%;box-sizing:border-box;padding:10px;margin:5px 0;background:#081925;color:white;border:1px solid #36586e;border-radius:8px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #28475d;text-align:right}.muted{color:#9fb4c4}.nav a{color:white;margin-left:12px}</style><body><div class="w">'+b+'</div></body></html>')
def calc(qid):
    q=one('SELECT * FROM sales_quotes WHERE id=?',(qid,))
    if not q:raise HTTPException(404)
    total=one('SELECT COALESCE(SUM(total_cost),0) v FROM quote_cost_items WHERE quote_id=?',(qid,))['v']
    if total<=0:total=q.get('base_cost') or 0
    margin=q.get('margin_percent') or 0;sell=round(total*(1+margin/100),2);vatp=q.get('vat_percent') or 0;vat=round(sell*vatp/100,2);grand=round(sell+vat,2);minm=float(os.getenv('MIN_QUOTE_MARGIN_PERCENT','10'));need=1 if margin<minm else 0
    execute('UPDATE sales_quotes SET base_cost=?,sell_price=?,total_before_vat=?,vat_amount=?,total_with_vat=?,min_margin_percent=?,requires_manager_approval=?,updated_at=? WHERE id=?',(total,sell,sell,vat,grand,minm,need,utcnow(),qid));return one('SELECT * FROM sales_quotes WHERE id=?',(qid,))
@router.get('/quotes/{qid}/pricing')
def pricing(qid:int,request:Request):
    s=auth(request);q=calc(qid);o=one('SELECT company_name FROM opportunities WHERE id=?',(q['opportunity_id'],));items=rows('SELECT * FROM quote_cost_items WHERE quote_id=? ORDER BY id',(qid,));approval=one('SELECT * FROM approvals WHERE id=?',(q.get('pricing_approval_id'),)) if q.get('pricing_approval_id') else None
    trs=''.join('<tr><td>'+esc(x['item_type'])+'</td><td>'+esc(x['description'])+'</td><td>'+format(x['quantity'],'.2f')+'</td><td>'+format(x['unit_cost'],',.2f')+'</td><td>'+format(x['total_cost'],',.2f')+'</td><td><form method="post" action="/quotes/'+str(qid)+'/cost/'+str(x['id'])+'/delete"><button class="btn danger">حذف</button></form></td></tr>' for x in items)
    gate=''
    if q['requires_manager_approval']:
        if approval and approval['status']=='approved':gate='<div class="card">✅ تمت الموافقة الإدارية على الهامش المنخفض.</div>'
        elif approval and approval['status']=='pending':gate='<div class="card warn">بانتظار موافقة الإدارة على هامش أقل من الحد الأدنى.</div>'+('<form method="post" action="/quotes/'+str(qid)+'/approve-pricing"><button class="btn">اعتماد الهامش المنخفض</button></form>' if s.get('role')=='admin' else '')
        else:gate='<form method="post" action="/quotes/'+str(qid)+'/request-pricing-approval"><button class="btn warn">طلب موافقة الإدارة على الهامش</button></form>'
    b=nav()+'<h1>التسعير والهوامش — '+esc(q['quote_number'])+'</h1><p>'+esc((o or {}).get('company_name'))+'</p><div class="grid"><div class="card"><b>إجمالي التكلفة الداخلية</b><h2>'+format(q['base_cost'],',.2f')+' '+esc(q['currency'])+'</h2></div><div class="card"><b>الهامش</b><h2>'+format(q['margin_percent'],'.2f')+'%</h2><span class="muted">الحد الأدنى '+format(q['min_margin_percent'],'.2f')+'%</span></div><div class="card"><b>قبل الضريبة</b><h2>'+format(q['total_before_vat'],',.2f')+'</h2></div><div class="card"><b>VAT</b><h2>'+format(q['vat_amount'],',.2f')+'</h2></div><div class="card"><b>الإجمالي للعميل</b><h2>'+format(q['total_with_vat'],',.2f')+' '+esc(q['currency'])+'</h2></div></div>'+gate
    b+='<div class="card"><h2>بنود التكلفة الداخلية</h2><form method="post" action="/quotes/'+str(qid)+'/cost"><div class="grid"><select name="item_type"><option>تخليص جمركي</option><option>نقل</option><option>شحن</option><option>مناولة</option><option>تخزين</option><option>رسوم طرف ثالث</option><option>أخرى</option></select><input name="description" placeholder="وصف البند"><input name="quantity" type="number" min="0" step="0.01" value="1" required><input name="unit_cost" type="number" min="0" step="0.01" placeholder="تكلفة الوحدة" required></div><button class="btn">إضافة بند تكلفة</button></form><table><tr><th>البند</th><th>الوصف</th><th>الكمية</th><th>تكلفة الوحدة</th><th>الإجمالي</th><th></th></tr>'+trs+'</table><p class="muted">هذه التكاليف داخلية ولا تظهر في النسخة التجارية للعميل.</p></div>'
    b+='<div class="card"><form method="post" action="/quotes/'+str(qid)+'/pricing-settings"><div class="grid"><input name="margin_percent" type="number" min="0" step="0.01" value="'+str(q['margin_percent'])+'"><select name="vat_percent"><option value="0"'+(' selected' if q['vat_percent']==0 else '')+'>بدون VAT</option><option value="15"'+(' selected' if q['vat_percent']==15 else '')+'>VAT 15%</option></select></div><button class="btn">إعادة حساب التسعير</button></form></div><a class="btn" href="/quotes/'+str(qid)+'/print" target="_blank">عرض تجاري للطباعة / حفظ PDF</a> <a class="btn" href="/quotes/'+str(qid)+'">العودة للعرض</a>'
    return shell(b)
@router.post('/quotes/{qid}/cost')
async def add_cost(qid:int,request:Request):
    s=auth(request);d=parse(await request.body());qty=float(d.get('quantity') or 0);unit=float(d.get('unit_cost') or 0);execute('INSERT INTO quote_cost_items(quote_id,item_type,description,quantity,unit_cost,total_cost,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)',(qid,d.get('item_type','أخرى'),d.get('description'),qty,unit,round(qty*unit,2),s['user_id'],utcnow()));calc(qid);log(s['user_id'],'add_quote_cost','sales_quote',qid,'Quote cost item added');return RedirectResponse('/quotes/'+str(qid)+'/pricing',303)
@router.post('/quotes/{qid}/cost/{cid}/delete')
def del_cost(qid:int,cid:int,request:Request):
    s=auth(request);execute('DELETE FROM quote_cost_items WHERE id=? AND quote_id=?',(cid,qid));calc(qid);log(s['user_id'],'delete_quote_cost','sales_quote',qid,'Quote cost item deleted');return RedirectResponse('/quotes/'+str(qid)+'/pricing',303)
@router.post('/quotes/{qid}/pricing-settings')
async def settings(qid:int,request:Request):
    s=auth(request);d=parse(await request.body());margin=float(d.get('margin_percent') or 0);vat=float(d.get('vat_percent') or 0);execute('UPDATE sales_quotes SET margin_percent=?,vat_percent=?,pricing_approval_id=NULL,updated_at=? WHERE id=?',(margin,vat,utcnow(),qid));calc(qid);log(s['user_id'],'update_quote_pricing','sales_quote',qid,'Margin/VAT updated');return RedirectResponse('/quotes/'+str(qid)+'/pricing',303)
@router.post('/quotes/{qid}/request-pricing-approval')
def req(qid:int,request:Request):
    s=auth(request);q=calc(qid)
    if not q['requires_manager_approval']:return RedirectResponse('/quotes/'+str(qid)+'/pricing',303)
    aid=execute('INSERT INTO approvals(kind,entity_type,entity_id,status,requested_by,notes,created_at) VALUES(?,?,?,?,?,?,?)',('low_margin_quote','sales_quote',qid,'pending',s['user_id'],'Margin '+str(q['margin_percent'])+'% is below minimum '+str(q['min_margin_percent'])+'%',utcnow()));execute('UPDATE sales_quotes SET pricing_approval_id=?,updated_at=? WHERE id=?',(aid,utcnow(),qid));log(s['user_id'],'request_low_margin_approval','sales_quote',qid,'Low margin approval requested');return RedirectResponse('/quotes/'+str(qid)+'/pricing',303)
@router.post('/quotes/{qid}/approve-pricing')
def approve(qid:int,request:Request):
    s=auth(request)
    if s.get('role')!='admin':raise HTTPException(403)
    q=one('SELECT * FROM sales_quotes WHERE id=?',(qid,))
    if not q or not q.get('pricing_approval_id'):raise HTTPException(409)
    execute('UPDATE approvals SET status=?,decided_by=?,decided_at=? WHERE id=?',('approved',s['user_id'],utcnow(),q['pricing_approval_id']));log(s['user_id'],'approve_low_margin_quote','sales_quote',qid,'Low margin quote approved');return RedirectResponse('/quotes/'+str(qid)+'/pricing',303)
@router.get('/quotes/{qid}/print')
def print_quote(qid:int,request:Request):
    auth(request);q=calc(qid);o=one('SELECT company_name FROM opportunities WHERE id=?',(q['opportunity_id'],));items=rows('SELECT item_type,description,quantity FROM quote_cost_items WHERE quote_id=? ORDER BY id',(qid,));trs=''.join('<tr><td>'+esc(x['item_type'])+'</td><td>'+esc(x['description'])+'</td><td>'+format(x['quantity'],'.2f')+'</td></tr>' for x in items)
    return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><title>'+esc(q['quote_number'])+'</title><style>body{font-family:Arial;margin:40px;color:#111}header{border-bottom:3px solid #111;padding-bottom:15px;margin-bottom:20px}table{width:100%;border-collapse:collapse;margin:20px 0}td,th{border:1px solid #aaa;padding:9px;text-align:right}.total{font-size:22px;font-weight:bold}.no-print{margin:20px 0}@media print{.no-print{display:none}}</style><body><header><h1>آفاق طويق</h1><div>التخليص الجمركي | النقل | الشحن | التخزين | الباب إلى الباب</div></header><h2>عرض تجاري '+esc(q['quote_number'])+'</h2><p><b>العميل:</b> '+esc((o or {}).get('company_name'))+'</p><p><b>الخدمة:</b> '+esc(q['service_type'])+' | <b>المسار:</b> '+esc(q.get('origin'))+' → '+esc(q.get('destination'))+'</p><table><tr><th>الخدمة/البند</th><th>الوصف</th><th>الكمية</th></tr>'+trs+'</table><p>القيمة قبل VAT: '+format(q['total_before_vat'],',.2f')+' '+esc(q['currency'])+'</p><p>VAT: '+format(q['vat_amount'],',.2f')+' '+esc(q['currency'])+'</p><p class="total">الإجمالي: '+format(q['total_with_vat'],',.2f')+' '+esc(q['currency'])+'</p><p><b>صلاحية العرض:</b> '+esc(q.get('valid_until') or 'غير محدد')+'</p><h3>الافتراضات</h3><p>'+esc(q.get('assumptions'))+'</p><h3>الاستثناءات</h3><p>'+esc(q.get('exclusions'))+'</p><div class="no-print"><button onclick="window.print()">طباعة / حفظ PDF</button></div></body></html>')
