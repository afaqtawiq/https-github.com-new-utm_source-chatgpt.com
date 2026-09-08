import html,datetime
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import get_session,rows,one,execute,log,utcnow,db
router=APIRouter()

def ensure_schema():
    with db() as c:
        for sql in [
            "ALTER TABLE sales_quotes ADD COLUMN IF NOT EXISTS version_no INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE sales_quotes ADD COLUMN IF NOT EXISTS parent_quote_id BIGINT REFERENCES sales_quotes(id) ON DELETE SET NULL",
            "ALTER TABLE sales_quotes ADD COLUMN IF NOT EXISTS commercial_approval_id BIGINT REFERENCES approvals(id) ON DELETE SET NULL",
            "ALTER TABLE sales_quotes ADD COLUMN IF NOT EXISTS commercial_status TEXT NOT NULL DEFAULT 'draft'",
            "ALTER TABLE sales_quotes ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ",
            "ALTER TABLE sales_quotes ADD COLUMN IF NOT EXISTS rejected_reason TEXT"]:
            c.execute(sql)
        c.execute('''CREATE TABLE IF NOT EXISTS quote_change_log(id BIGSERIAL PRIMARY KEY,quote_id BIGINT NOT NULL REFERENCES sales_quotes(id) ON DELETE CASCADE,version_no INTEGER NOT NULL,change_type TEXT NOT NULL,old_sell_price DOUBLE PRECISION,new_sell_price DOUBLE PRECISION,old_margin_percent DOUBLE PRECISION,new_margin_percent DOUBLE PRECISION,notes TEXT,changed_by BIGINT,changed_at TIMESTAMPTZ NOT NULL)''')
ensure_schema()

def esc(v):return html.escape(str(v or ''))
def auth(r):
    s=get_session(r.cookies.get('gla_session'))
    if not s:raise HTTPException(401)
    return s
def nav():return '<div class="nav"><a href="/quotes">عروض الأسعار</a><a href="/quote-workflow">اعتمادات العروض</a><a href="/sales-center">مركز المبيعات</a><a href="/shipments">الشحنات</a></div>'
def shell(b):return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}.w{max-width:1250px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:18px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.btn{display:inline-block;padding:9px 12px;border:0;border-radius:9px;background:#22c55e;color:#04130a;text-decoration:none;font-weight:bold;cursor:pointer}.danger{background:#ef4444;color:#fff}.warn{background:#f59e0b;color:#231500}table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #28475d;text-align:right}.nav a{color:white;margin-left:12px}.muted{color:#9fb4c4}</style><body><div class="w">'+b+'</div></body></html>')
def pricing_ready(q):
    if q.get('requires_manager_approval') and q.get('pricing_approval_id'):
        a=one('SELECT status FROM approvals WHERE id=?',(q['pricing_approval_id'],));return bool(a and a['status']=='approved')
    return not bool(q.get('requires_manager_approval'))
@router.get('/quote-workflow')
def home(request:Request):
    auth(request);data=rows('''SELECT q.*,o.company_name FROM sales_quotes q JOIN opportunities o ON o.id=q.opportunity_id ORDER BY q.id DESC LIMIT 200''')
    trs=''.join('<tr><td>'+esc(x['quote_number'])+' v'+str(x.get('version_no') or 1)+'</td><td>'+esc(x['company_name'])+'</td><td>'+format(x.get('total_with_vat') or x.get('sell_price') or 0,',.2f')+' '+esc(x['currency'])+'</td><td>'+esc(x.get('commercial_status') or 'draft')+'</td><td><a class="btn" href="/quote-workflow/'+str(x['id'])+'">فتح</a></td></tr>' for x in data)
    return shell(nav()+'<h1>Quotation Approval Workflow</h1><div class="card muted">اعتماد تجاري مستقل عن اعتماد إرسال البريد، مع نسخ V1/V2 وسجل تغييرات وقبول يحول الصفقة إلى Won وينشئ شحنة تشغيلية.</div><div class="card"><table><tr><th>العرض</th><th>العميل</th><th>القيمة</th><th>الحالة التجارية</th><th></th></tr>'+trs+'</table></div>')
@router.get('/quote-workflow/{qid}')
def detail(qid:int,request:Request):
    s=auth(request);q=one('SELECT q.*,o.company_name FROM sales_quotes q JOIN opportunities o ON o.id=q.opportunity_id WHERE q.id=?',(qid,));
    if not q:raise HTTPException(404)
    a=one('SELECT * FROM approvals WHERE id=?',(q.get('commercial_approval_id'),)) if q.get('commercial_approval_id') else None;history=rows('SELECT * FROM quote_change_log WHERE quote_id=? ORDER BY id DESC',(qid,));h=''.join('<tr><td>'+str(x['version_no'])+'</td><td>'+esc(x['change_type'])+'</td><td>'+esc(x.get('old_sell_price'))+' → '+esc(x.get('new_sell_price'))+'</td><td>'+esc(x.get('old_margin_percent'))+'% → '+esc(x.get('new_margin_percent'))+'%</td><td>'+esc(x['changed_at'])+'</td></tr>' for x in history)
    actions=''
    if q.get('commercial_status') in ('draft','revised','rejected'):
        actions+='<form method="post" action="/quotes/'+str(qid)+'/request-commercial-approval"><button class="btn">طلب الاعتماد التجاري</button></form>'
    if a and a['status']=='pending' and s.get('role')=='admin':
        actions+='<form method="post" action="/quotes/'+str(qid)+'/approve-commercial"><button class="btn">اعتماد تجاري</button></form><form method="post" action="/quotes/'+str(qid)+'/reject-commercial"><button class="btn danger">رفض</button></form>'
    if q.get('commercial_status')=='approved':
        actions+='<form method="post" action="/quotes/'+str(qid)+'/accept"><button class="btn">تسجيل قبول العميل وتحويلها Won</button></form>'
    if q.get('commercial_status') in ('approved','rejected','sent'):
        actions+='<form method="post" action="/quotes/'+str(qid)+'/revise"><button class="btn warn">إنشاء Revision جديدة</button></form>'
    b=nav()+'<h1>'+esc(q['quote_number'])+' — V'+str(q.get('version_no') or 1)+'</h1><div class="grid"><div class="card"><b>العميل</b><h2>'+esc(q['company_name'])+'</h2></div><div class="card"><b>الحالة التجارية</b><h2>'+esc(q.get('commercial_status'))+'</h2></div><div class="card"><b>القيمة</b><h2>'+format(q.get('total_with_vat') or q.get('sell_price') or 0,',.2f')+' '+esc(q['currency'])+'</h2></div><div class="card"><b>الهامش</b><h2>'+format(q.get('margin_percent') or 0,'.2f')+'%</h2></div></div><div class="card">'+actions+'</div><div class="card"><a class="btn" href="/quotes/'+str(qid)+'/pricing">التسعير</a> <a class="btn" href="/quotes/'+str(qid)+'/print" target="_blank">نسخة الطباعة</a></div><div class="card"><h2>سجل تغييرات العرض</h2><table><tr><th>الإصدار</th><th>النوع</th><th>السعر</th><th>الهامش</th><th>الوقت</th></tr>'+h+'</table></div>'
    return shell(b)
@router.post('/quotes/{qid}/request-commercial-approval')
def request_approval(qid:int,request:Request):
    s=auth(request);q=one('SELECT * FROM sales_quotes WHERE id=?',(qid,));
    if not q:raise HTTPException(404)
    if not pricing_ready(q):raise HTTPException(409,'Pricing approval must be completed first')
    aid=execute('INSERT INTO approvals(kind,entity_type,entity_id,status,requested_by,notes,created_at) VALUES(?,?,?,?,?,?,?)',('commercial_quote','sales_quote',qid,'pending',s['user_id'],'Commercial approval for quote '+q['quote_number']+' V'+str(q.get('version_no') or 1),utcnow()));execute('UPDATE sales_quotes SET commercial_approval_id=?,commercial_status=?,updated_at=? WHERE id=?',(aid,'pending_approval',utcnow(),qid));log(s['user_id'],'request_commercial_quote_approval','sales_quote',qid,'Commercial quote approval requested');return RedirectResponse('/quote-workflow/'+str(qid),303)
@router.post('/quotes/{qid}/approve-commercial')
def approve(qid:int,request:Request):
    s=auth(request)
    if s.get('role')!='admin':raise HTTPException(403)
    q=one('SELECT * FROM sales_quotes WHERE id=?',(qid,));
    if not q or not q.get('commercial_approval_id'):raise HTTPException(409)
    now=utcnow();execute('UPDATE approvals SET status=?,decided_by=?,decided_at=? WHERE id=?',('approved',s['user_id'],now,q['commercial_approval_id']));execute('UPDATE sales_quotes SET commercial_status=?,status=?,updated_at=? WHERE id=?',('approved','approved',now,qid));log(s['user_id'],'approve_commercial_quote','sales_quote',qid,'Commercial quote approved');return RedirectResponse('/quote-workflow/'+str(qid),303)
@router.post('/quotes/{qid}/reject-commercial')
def reject(qid:int,request:Request):
    s=auth(request)
    if s.get('role')!='admin':raise HTTPException(403)
    q=one('SELECT * FROM sales_quotes WHERE id=?',(qid,));
    if not q or not q.get('commercial_approval_id'):raise HTTPException(409)
    now=utcnow();execute('UPDATE approvals SET status=?,decided_by=?,decided_at=? WHERE id=?',('rejected',s['user_id'],now,q['commercial_approval_id']));execute('UPDATE sales_quotes SET commercial_status=?,status=?,updated_at=? WHERE id=?',('rejected','rejected',now,qid));log(s['user_id'],'reject_commercial_quote','sales_quote',qid,'Commercial quote rejected');return RedirectResponse('/quote-workflow/'+str(qid),303)
@router.post('/quotes/{qid}/revise')
def revise(qid:int,request:Request):
    s=auth(request);q=one('SELECT * FROM sales_quotes WHERE id=?',(qid,));
    if not q:raise HTTPException(404)
    now=utcnow();newv=(q.get('version_no') or 1)+1;newnum=q['quote_number'].split('-V')[0]+'-V'+str(newv)
    nid=execute('''INSERT INTO sales_quotes(opportunity_id,response_action_id,quote_number,status,service_type,origin,destination,cargo_description,quantity,currency,base_cost,margin_percent,sell_price,valid_until,assumptions,exclusions,created_by,created_at,updated_at,vat_percent,total_before_vat,vat_amount,total_with_vat,min_margin_percent,requires_manager_approval,version_no,parent_quote_id,commercial_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(q['opportunity_id'],q.get('response_action_id'),newnum,'draft',q['service_type'],q.get('origin'),q.get('destination'),q.get('cargo_description'),q.get('quantity'),q['currency'],q.get('base_cost') or 0,q.get('margin_percent') or 0,q.get('sell_price') or 0,q.get('valid_until'),q.get('assumptions'),q.get('exclusions'),s['user_id'],now,now,q.get('vat_percent') or 0,q.get('total_before_vat') or 0,q.get('vat_amount') or 0,q.get('total_with_vat') or 0,q.get('min_margin_percent') or 0,q.get('requires_manager_approval') or 0,newv,qid,'revised'))
    for x in rows('SELECT * FROM quote_cost_items WHERE quote_id=? ORDER BY id',(qid,)):execute('INSERT INTO quote_cost_items(quote_id,item_type,description,quantity,unit_cost,total_cost,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)',(nid,x['item_type'],x.get('description'),x['quantity'],x['unit_cost'],x['total_cost'],s['user_id'],now))
    execute('INSERT INTO quote_change_log(quote_id,version_no,change_type,old_sell_price,new_sell_price,old_margin_percent,new_margin_percent,notes,changed_by,changed_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(nid,newv,'revision_created',q.get('sell_price'),q.get('sell_price'),q.get('margin_percent'),q.get('margin_percent'),'Revision created from '+q['quote_number'],s['user_id'],now));log(s['user_id'],'revise_sales_quote','sales_quote',nid,'Revision created from quote '+str(qid));return RedirectResponse('/quote-workflow/'+str(nid),303)
@router.post('/quotes/{qid}/accept')
def accept(qid:int,request:Request):
    s=auth(request);q=one('SELECT * FROM sales_quotes WHERE id=?',(qid,));
    if not q or q.get('commercial_status')!='approved':raise HTTPException(409,'Commercial approval required')
    now=utcnow();execute('UPDATE sales_quotes SET commercial_status=?,status=?,accepted_at=?,updated_at=? WHERE id=?',('accepted','accepted',now,now,qid));execute('UPDATE opportunities SET stage=?,estimated_value=?,currency=?,updated_at=? WHERE id=?',('won',q.get('total_with_vat') or q.get('sell_price') or 0,q['currency'],now,q['opportunity_id']))
    existing=one('SELECT id FROM sales_outcomes WHERE opportunity_id=?',(q['opportunity_id'],));val=q.get('total_with_vat') or q.get('sell_price') or 0
    if existing:execute('UPDATE sales_outcomes SET outcome=?,realized_value=?,currency=?,recorded_by=?,recorded_at=? WHERE opportunity_id=?',('won',val,q['currency'],s['user_id'],now,q['opportunity_id']))
    else:execute('INSERT INTO sales_outcomes(opportunity_id,outcome,reason,realized_value,currency,recorded_by,recorded_at) VALUES(?,?,?,?,?,?,?)',(q['opportunity_id'],'won','Accepted approved quotation '+q['quote_number'],val,q['currency'],s['user_id'],now))
    ref='AT-SHP-Q'+str(qid)+'-'+now.strftime('%Y%m%d%H%M%S');execute('INSERT INTO shipments(account_id,reference,service_type,origin,destination,status,revenue,cost,currency,created_at,updated_at) SELECT account_id,?,?,?,?,?,?,?,?,?,? FROM opportunities WHERE id=?',(ref,q['service_type'],q.get('origin'),q.get('destination'),'new',val,q.get('base_cost') or 0,q['currency'],now,now,q['opportunity_id']))
    log(s['user_id'],'accept_quote_and_create_shipment','sales_quote',qid,'Approved quote accepted; opportunity won and shipment created');return RedirectResponse('/quote-workflow/'+str(qid),303)
@router.get('/api/v7/quote-workflow')
def api(request:Request):
    auth(request);return {'quotes':rows('SELECT id,opportunity_id,quote_number,version_no,commercial_status,total_with_vat,currency,accepted_at,parent_quote_id FROM sales_quotes ORDER BY id DESC'),'changes':rows('SELECT quote_id,version_no,change_type,old_sell_price,new_sell_price,old_margin_percent,new_margin_percent,changed_at FROM quote_change_log ORDER BY id DESC LIMIT 500')}
