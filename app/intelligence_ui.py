import html
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import get_session,rows,one,execute,log,utcnow
from app.intelligence import analyze

router=APIRouter()

def esc(v): return html.escape(str(v or ''))
def session(request):
    s=get_session(request.cookies.get('gla_session'))
    if not s: raise HTTPException(401)
    return s

def shell(title,body):
    return '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title><style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}.w{max-width:1250px;margin:auto;padding:24px}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav a,.btn{display:inline-block;padding:10px 14px;border-radius:10px;background:#18384d;color:white;text-decoration:none;border:0;font-weight:700}.btn{background:#22c55e;color:#04130a;cursor:pointer}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.pill{padding:5px 9px;border-radius:999px;background:#18384d}.muted{color:#9fb4c4}table{width:100%;border-collapse:collapse}td,th{padding:11px;border-bottom:1px solid #28475d;text-align:right;vertical-align:top}.scroll{overflow:auto}pre{white-space:pre-wrap;font-family:Arial;line-height:1.8}</style><body><div class="w">'+body+'</div></body></html>'
def nav(): return '<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/discovery">الاكتشاف</a><a href="/intelligence">الذكاء</a><a href="/opportunities">CRM الفرص</a><a href="/pipeline">Pipeline</a></div>'

@router.get('/intelligence-v2',response_class=HTMLResponse)
def intelligence_v2(request:Request):
    s=session(request)
    data=rows('''SELECT o.*,i.priority,i.intent,i.services,i.next_action,i.follow_up_status,i.generated_at
                 FROM opportunities o LEFT JOIN opportunity_intelligence i ON i.opportunity_id=o.id
                 ORDER BY o.score DESC,o.id DESC''')
    trs=''
    for x in data:
        trs+='<tr><td>'+esc(x.get('priority') or '—')+'</td><td>'+esc(x['company_name'])+'</td><td>'+esc(x['score'])+'</td><td>'+esc(x.get('intent') or '—')+'</td><td>'+esc(x.get('services') or '—')+'</td><td>'+esc(x.get('follow_up_status') or 'لم يُحلل')+'</td><td><form method="post" action="/intelligence-v2/'+str(x['id'])+'/generate"><button class="btn">تحليل وتوليد</button></form> <a class="btn" href="/intelligence-v2/'+str(x['id'])+'">فتح</a></td></tr>'
    body=nav()+'<h1>Opportunity Intelligence</h1><div class="card"><b>مساحة تأهيل الفرص وصناعة مسودة العرض.</b><div class="muted">كل المخرجات داخلية ولا يتم إرسال أي رسالة أو عرض خارجيًا.</div></div><div class="card scroll"><table><tr><th>الأولوية</th><th>الجهة</th><th>Score</th><th>النية</th><th>الخدمات</th><th>المتابعة</th><th>إجراء</th></tr>'+trs+'</table></div>'
    return HTMLResponse(shell('Opportunity Intelligence',body))

@router.post('/intelligence-v2/{opportunity_id}/generate')
def generate(opportunity_id:int,request:Request):
    s=session(request);op=one('SELECT * FROM opportunities WHERE id=?',(opportunity_id,))
    if not op: raise HTTPException(404)
    z=analyze(op);now=utcnow();services=', '.join(z['services'])
    execute('''INSERT INTO opportunity_intelligence(opportunity_id,priority,intent,services,evidence,next_action,proposal_draft,follow_up_status,generated_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET priority=EXCLUDED.priority,intent=EXCLUDED.intent,services=EXCLUDED.services,evidence=EXCLUDED.evidence,next_action=EXCLUDED.next_action,proposal_draft=EXCLUDED.proposal_draft,updated_at=EXCLUDED.updated_at''',(opportunity_id,z['priority'],z['intent'],services,z['evidence'],z['next_action'],z['proposal_draft'],'draft',now,now))
    log(s['user_id'],'generate_intelligence','opportunity',opportunity_id,'Generated internal intelligence and proposal draft; no external send')
    return RedirectResponse('/intelligence-v2/'+str(opportunity_id),303)

@router.get('/intelligence-v2/{opportunity_id}',response_class=HTMLResponse)
def detail(opportunity_id:int,request:Request):
    session(request);op=one('SELECT * FROM opportunities WHERE id=?',(opportunity_id,));intel=one('SELECT * FROM opportunity_intelligence WHERE opportunity_id=?',(opportunity_id,))
    if not op: raise HTTPException(404)
    if not intel: return HTMLResponse(shell('الفرصة',nav()+'<div class="card"><h1>'+esc(op['company_name'])+'</h1><p>لم يتم إنشاء التحليل بعد.</p><form method="post" action="/intelligence-v2/'+str(opportunity_id)+'/generate"><button class="btn">إنشاء التحليل الآن</button></form></div>'))
    source='<a class="btn" target="_blank" href="'+esc(op.get('source_url'))+'">فتح الدليل العام</a>' if op.get('source_url') else '—'
    body=nav()+'<h1>'+esc(op['company_name'])+'</h1><div class="grid"><div class="card"><span class="pill">'+esc(intel['priority'])+'</span><h3>نية الشراء</h3>'+esc(intel['intent'])+'</div><div class="card"><h3>Score</h3>'+esc(op['score'])+'/100</div><div class="card"><h3>الخدمات المطابقة</h3>'+esc(intel['services'])+'</div><div class="card"><h3>الحالة</h3>'+esc(intel['follow_up_status'])+'</div></div><div class="card"><h2>الدليل</h2><p>'+esc(intel['evidence'])+'</p>'+source+'</div><div class="card"><h2>الإجراء التالي</h2><p>'+esc(intel['next_action'])+'</p></div><div class="card"><h2>مسودة عرض داخلية</h2><pre>'+esc(intel['proposal_draft'])+'</pre><div class="muted">غير مرسلة — تتطلب تحققًا وموافقة بشرية قبل أي استخدام خارجي.</div></div>'
    return HTMLResponse(shell('تفاصيل الفرصة',body))
