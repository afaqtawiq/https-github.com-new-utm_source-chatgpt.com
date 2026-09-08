import html
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import get_session,rows,one,execute,log,utcnow
from app.intelligence import analyze

router=APIRouter()
def esc(v): return html.escape(str(v or ''))
def auth(r):
    s=get_session(r.cookies.get('gla_session'))
    if not s: raise HTTPException(401)
    return s

def nav(): return '<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/discovery">الاكتشاف</a><a href="/opportunities">CRM</a><a href="/intelligence-v2">Intelligence</a><a href="/sales-copilot">Sales Copilot</a><a href="/pipeline">Pipeline</a></div>'
def shell(title,body):
    return '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title><style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}.w{max-width:1280px;margin:auto;padding:24px}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav a,.btn{display:inline-block;padding:10px 14px;border-radius:10px;background:#18384d;color:#fff;text-decoration:none;border:0;font-weight:700}.btn{background:#22c55e;color:#04130a;cursor:pointer}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}.muted{color:#9fb4c4}.pill{padding:5px 9px;border-radius:999px;background:#18384d}table{width:100%;border-collapse:collapse}td,th{padding:11px;border-bottom:1px solid #28475d;text-align:right;vertical-align:top}.scroll{overflow:auto}pre{white-space:pre-wrap;font-family:Arial;line-height:1.8}</style><body><div class="w">'+body+'</div></body></html>'

def playbook(op,z):
    services='، '.join(z['services']) or 'حل لوجستي متكامل'
    fit='مرتفع' if z['priority']=='P1' else ('جيد' if z['priority']=='P2' else 'يحتاج تأهيل')
    need='توجد إشارة عامة مرتبطة بـ '+services+'. يجب التحقق من نطاق العمل والموعد والجهة قبل التواصل.'
    value='آفاق طويق تستطيع تقديم '+services+' مع متابعة تشغيلية داخل السعودية والخليج، ويجب تخصيص الوعد التجاري بعد التحقق من متطلبات الجهة.'
    proposal=('مسودة داخلية — غير مرسلة\n\nالسادة/ '+str(op['company_name'])+'\n\nتحية طيبة،\nرصدنا احتياجًا عامًا قد يرتبط بخدمات '+services+'. '
              'تستطيع آفاق طويق دراسة المتطلبات وتقديم تصور تشغيلي مناسب يشمل نطاق الخدمة ومراحل التنفيذ والمتابعة.\n\n'
              'قبل إصدار أي عرض نهائي نوصي بمراجعة المصدر العام والتحقق من المتطلبات والمواعيد والكميات ونقاط الاستلام والتسليم.\n\nآفاق طويق\nالتخليص الجمركي | النقل | الشحن | التخزين | الباب إلى الباب')
    follow=('1) مراجعة الدليل العام والتحقق من أن الفرصة ما زالت قائمة.\n'
            '2) تثبيت اسم الجهة ومتخذ القرار من مصادر عامة فقط.\n'
            '3) تحديد نطاق الخدمة والكميات والمسارات والموعد النهائي.\n'
            '4) إعداد عرض سعر/حل تشغيلي بعد اكتمال البيانات.\n'
            '5) طلب موافقة بشرية قبل أي تواصل خارجي.')
    return {'fit':fit,'need':need,'value':value,'proposal':proposal,'follow':follow}

@router.get('/sales-copilot',response_class=HTMLResponse)
def home(request:Request):
    auth(request)
    data=rows('''SELECT o.*,i.priority,i.intent,i.services,i.follow_up_status FROM opportunities o LEFT JOIN opportunity_intelligence i ON i.opportunity_id=o.id ORDER BY CASE WHEN i.priority='P1' THEN 1 WHEN i.priority='P2' THEN 2 ELSE 3 END,o.score DESC,o.id DESC''')
    trs=''
    for x in data:
        trs+='<tr><td>'+esc(x.get('priority') or '—')+'</td><td>'+esc(x['company_name'])+'</td><td>'+esc(x['score'])+'</td><td>'+esc(x.get('intent') or '—')+'</td><td>'+esc(x.get('services') or '—')+'</td><td><form method="post" action="/sales-copilot/'+str(x['id'])+'/prepare"><button class="btn">إعداد ملف البيع</button></form> <a class="btn" href="/sales-copilot/'+str(x['id'])+'">فتح</a></td></tr>'
    return HTMLResponse(shell('Sales Copilot',nav()+'<h1>Sales Copilot — آفاق طويق</h1><div class="card"><b>من فرصة مكتشفة إلى ملف بيع قابل للتنفيذ.</b><div class="muted">لا يوجد إرسال خارجي. كل مسودة تتطلب تحققًا وموافقة بشرية.</div></div><div class="card scroll"><table><tr><th>الأولوية</th><th>الجهة</th><th>Score</th><th>نية الشراء</th><th>الخدمات</th><th>الإجراء</th></tr>'+trs+'</table></div>'))

@router.post('/sales-copilot/{oid}/prepare')
def prepare(oid:int,request:Request):
    s=auth(request);op=one('SELECT * FROM opportunities WHERE id=?',(oid,))
    if not op: raise HTTPException(404)
    z=analyze(op);p=playbook(op,z);now=utcnow();services=', '.join(z['services'])
    execute('''INSERT INTO opportunity_intelligence(opportunity_id,priority,intent,services,evidence,next_action,proposal_draft,follow_up_status,generated_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET priority=EXCLUDED.priority,intent=EXCLUDED.intent,services=EXCLUDED.services,evidence=EXCLUDED.evidence,next_action=EXCLUDED.next_action,proposal_draft=EXCLUDED.proposal_draft,follow_up_status=EXCLUDED.follow_up_status,updated_at=EXCLUDED.updated_at''',(oid,z['priority'],z['intent'],services,z['evidence'],p['follow'],p['proposal'],'sales_ready_draft',now,now))
    log(s['user_id'],'prepare_sales_copilot','opportunity',oid,'Prepared internal Afaaq Tuwaiq sales playbook; external send disabled')
    return RedirectResponse('/sales-copilot/'+str(oid),303)

@router.get('/sales-copilot/{oid}',response_class=HTMLResponse)
def detail(oid:int,request:Request):
    auth(request);op=one('SELECT * FROM opportunities WHERE id=?',(oid,))
    if not op: raise HTTPException(404)
    z=analyze(op);p=playbook(op,z);intel=one('SELECT * FROM opportunity_intelligence WHERE opportunity_id=?',(oid,))
    source='<a class="btn" target="_blank" rel="noopener" href="'+esc(op.get('source_url'))+'">فتح المصدر العام</a>' if op.get('source_url') else '—'
    body=nav()+'<h1>'+esc(op['company_name'])+'</h1><div class="grid"><div class="card"><span class="pill">'+esc(z['priority'])+'</span><h3>ملاءمة آفاق طويق</h3>'+esc(p['fit'])+'</div><div class="card"><h3>نية الشراء</h3>'+esc(z['intent'])+'</div><div class="card"><h3>Score</h3>'+esc(op['score'])+'/100</div><div class="card"><h3>الخدمات</h3>'+esc('، '.join(z['services']))+'</div></div><div class="card"><h2>لماذا قد تحتاج الجهة آفاق طويق؟</h2><p>'+esc(p['need'])+'</p><h3>عرض القيمة</h3><p>'+esc(p['value'])+'</p></div><div class="card"><h2>الدليل</h2><p>'+esc(z['evidence'])+'</p>'+source+'</div><div class="card"><h2>خطة المندوب</h2><pre>'+esc(p['follow'])+'</pre></div><div class="card"><h2>مسودة العرض التجاري</h2><pre>'+esc((intel or {}).get('proposal_draft') or p['proposal'])+'</pre><div class="muted">مسودة داخلية فقط — لا ترسل تلقائيًا.</div></div><form method="post" action="/sales-copilot/'+str(oid)+'/prepare"><button class="btn">تحديث ملف البيع وحفظه</button></form>'
    return HTMLResponse(shell('Sales Copilot',body))

@router.get('/api/v7/sales-copilot')
def api_list(request:Request):
    auth(request)
    return {'external_actions':False,'opportunities':rows('''SELECT o.id,o.company_name,o.score,o.stage,i.priority,i.intent,i.services,i.next_action,i.follow_up_status FROM opportunities o LEFT JOIN opportunity_intelligence i ON i.opportunity_id=o.id ORDER BY o.score DESC,o.id DESC''')}
