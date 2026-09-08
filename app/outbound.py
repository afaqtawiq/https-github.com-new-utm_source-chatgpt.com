import os,html,urllib.parse
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import get_session,rows,one,execute,log,utcnow
from app.gmail_oauth import send_gmail,connection

router=APIRouter()

def esc(v): return html.escape(str(v or ''))
def auth(r):
    s=get_session(r.cookies.get('gla_session'))
    if not s: raise HTTPException(401)
    return s
def parse(raw): return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def shell(t,b): return '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(t)+'</title><style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}.w{max-width:1250px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav a,.btn{display:inline-block;padding:10px 14px;border-radius:10px;background:#18384d;color:white;text-decoration:none;border:0;font-weight:700}.btn{background:#22c55e;color:#04130a;cursor:pointer}.danger{background:#ef4444;color:white}.muted{color:#9fb4c4}input,textarea{width:100%;box-sizing:border-box;padding:12px;margin:6px 0;border-radius:9px;border:1px solid #36586e;background:#081925;color:white}textarea{min-height:180px}table{width:100%;border-collapse:collapse}td,th{padding:11px;border-bottom:1px solid #28475d;text-align:right;vertical-align:top}.scroll{overflow:auto}</style><body><div class="w">'+b+'</div></body></html>'
def nav(): return '<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/sales-copilot">Sales Copilot</a><a href="/outbound">العروض والرسائل</a><a href="/outbound/test">اختبار Gmail</a><a href="/approvals">الموافقات</a><a href="/settings/email">إعداد البريد</a><a href="/activity">السجل</a></div>'

def gmail_ready(uid):
    c=connection(uid)
    return bool(c and c.get('status')=='connected' and os.getenv('ENABLE_EXTERNAL_ACTIONS','0')=='1')

@router.get('/outbound',response_class=HTMLResponse)
def home(request:Request):
    s=auth(request);data=rows('SELECT m.*,o.company_name FROM outbound_messages m JOIN opportunities o ON o.id=m.opportunity_id ORDER BY m.id DESC');ready=gmail_ready(s['user_id'])
    trs=''.join('<tr><td>'+esc(m['company_name'])+'</td><td>'+esc(m['channel'])+'</td><td>'+esc(m['recipient'])+'</td><td>'+esc(m['status'])+'</td><td><a class="btn" href="/outbound/'+str(m['id'])+'">فتح</a></td></tr>' for m in data)
    return HTMLResponse(shell('العروض والرسائل',nav()+'<h1>العروض والرسائل</h1><div class="card">إنشاء → مراجعة → طلب موافقة → موافقة بشرية → إرسال عبر Gmail.<br><span class="muted">Gmail: '+('جاهز' if ready else 'غير مفعّل للإرسال')+'</span></div><div class="card scroll"><table><tr><th>الجهة</th><th>القناة</th><th>المستلم</th><th>الحالة</th><th></th></tr>'+trs+'</table></div>'))

@router.get('/outbound/test',response_class=HTMLResponse)
def test_page(request:Request):
    s=auth(request)
    if s.get('role')!='admin': raise HTTPException(403)
    recipient=os.getenv('TEST_EMAIL_RECIPIENT','').strip();ready=gmail_ready(s['user_id']) and bool(recipient)
    body=nav()+'<h1>اختبار Gmail داخل النظام</h1><div class="card"><b>المستلم المعتمد للاختبار:</b> '+esc(recipient or 'غير مضبوط')+'<br><b>Gmail:</b> '+('جاهز' if ready else 'غير جاهز')+'<p class="muted">سيُنشئ النظام فرصة اختبار ورسالة Outbound فقط. بعد ذلك ستراجع الرسالة وتوافق عليها يدويًا ثم تضغط إرسال.</p></div>'
    if ready: body+='<form method="post" action="/outbound/test/start"><button class="btn">إنشاء اختبار داخل CRM</button></form>'
    return HTMLResponse(shell('اختبار Gmail',body))

@router.post('/outbound/test/start')
def test_start(request:Request):
    s=auth(request)
    if s.get('role')!='admin': raise HTTPException(403)
    recipient=os.getenv('TEST_EMAIL_RECIPIENT','').strip()
    if not recipient or not gmail_ready(s['user_id']): raise HTTPException(409,'Gmail test is not ready')
    now=utcnow()
    oid=execute('INSERT INTO opportunities(company_name,source_url,signal,score,stage,estimated_value,currency,owner,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',('Afaaq Tuwaiq Internal Gmail Test','internal://gmail-integration-test','Controlled internal test of CRM approval and Gmail API delivery',100,'test',0,'SAR',s['email'],now,now))
    execute('INSERT INTO opportunity_intelligence(opportunity_id,priority,intent,services,evidence,next_action,proposal_draft,follow_up_status,generated_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(oid,'P1','Internal integration test','Gmail outbound','Controlled operator-approved test recipient','Review, approve, then send','اختبار تقني داخلي فقط. لا يتضمن عرضًا تجاريًا.','test',now,now))
    subject='اختبار داخلي كامل – آفاق طويق';body='مرحبًا،\n\nهذه رسالة اختبار تكامل كاملة من داخل Gulf Logistics AI للتحقق من مسار CRM → الموافقة → Gmail API → التسجيل.\n\nلا تتطلب هذه الرسالة أي إجراء.\n\nآفاق طويق'
    mid=execute('INSERT INTO outbound_messages(opportunity_id,channel,recipient,subject,body,proposal_text,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(oid,'email',recipient,subject,body,'اختبار تقني داخلي فقط.','draft',s['user_id'],now,now))
    log(s['user_id'],'create_outbound_test','outbound_message',mid,'Controlled integration test draft created')
    return RedirectResponse('/outbound/'+str(mid),303)

@router.post('/outbound/from-opportunity/{oid}')
def create_from_opportunity(oid:int,request:Request):
    s=auth(request);op=one('SELECT * FROM opportunities WHERE id=?',(oid,));intel=one('SELECT * FROM opportunity_intelligence WHERE opportunity_id=?',(oid,))
    if not op or not intel: raise HTTPException(400,'Generate Sales Copilot first')
    body='السادة/ '+op['company_name']+'\n\nتحية طيبة،\nنود من آفاق طويق مناقشة احتياجكم المرتبط بـ '+(intel.get('services') or 'الخدمات اللوجستية')+'.\nيسعدنا دراسة نطاق العمل وتقديم الحل التشغيلي المناسب بعد التحقق من المتطلبات.\n\nمع التحية،\nآفاق طويق'
    mid=execute('INSERT INTO outbound_messages(opportunity_id,channel,subject,body,proposal_text,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(oid,'email','عرض خدمات لوجستية — آفاق طويق',body,intel.get('proposal_draft'),'draft',s['user_id'],utcnow(),utcnow()))
    log(s['user_id'],'create_outbound_draft','outbound_message',mid,'Draft created; not sent')
    return RedirectResponse('/outbound/'+str(mid),303)

@router.get('/outbound/{mid}',response_class=HTMLResponse)
def detail(mid:int,request:Request):
    s=auth(request);m=one('SELECT m.*,o.company_name FROM outbound_messages m JOIN opportunities o ON o.id=m.opportunity_id WHERE m.id=?',(mid,))
    if not m: raise HTTPException(404)
    if m['status']=='draft':
        edit='<form method="post" action="/outbound/'+str(mid)+'/update"><input name="recipient" type="email" value="'+esc(m.get('recipient'))+'" placeholder="البريد الموثق للجهة" required><input name="subject" value="'+esc(m['subject'])+'" required><textarea name="body">'+esc(m['body'])+'</textarea><textarea name="proposal_text">'+esc(m.get('proposal_text'))+'</textarea><button class="btn">حفظ</button></form><form method="post" action="/outbound/'+str(mid)+'/request-approval"><button class="btn">طلب الموافقة</button></form>'
    elif m['status']=='pending_approval':
        edit='<div class="card">بانتظار الموافقة البشرية.</div>'
        if s.get('role')=='admin': edit+='<form method="post" action="/outbound/'+str(mid)+'/approve"><button class="btn">موافقة</button></form><form method="post" action="/outbound/'+str(mid)+'/reject"><button class="btn danger">رفض</button></form>'
    elif m['status']=='approved': edit='<form method="post" action="/outbound/'+str(mid)+'/send"><button class="btn">إرسال الرسالة المعتمدة</button></form>'
    else: edit='<div class="card">الحالة: '+esc(m['status'])+'</div>'
    preview='<div class="card"><b>إلى:</b> '+esc(m.get('recipient'))+'<br><b>العنوان:</b> '+esc(m.get('subject'))+'<pre style="white-space:pre-wrap">'+esc(m.get('body'))+'</pre></div>'
    return HTMLResponse(shell('رسالة',nav()+'<h1>'+esc(m['company_name'])+'</h1><div class="card"><b>الحالة:</b> '+esc(m['status'])+'</div>'+preview+edit))

@router.post('/outbound/{mid}/update')
async def update(mid:int,request:Request):
    s=auth(request);m=one('SELECT * FROM outbound_messages WHERE id=?',(mid,))
    if not m or m['status']!='draft': raise HTTPException(409,'Only drafts can be edited')
    d=parse(await request.body());execute('UPDATE outbound_messages SET recipient=?,subject=?,body=?,proposal_text=?,updated_at=? WHERE id=?',(d.get('recipient','').strip(),d.get('subject',''),d.get('body',''),d.get('proposal_text',''),utcnow(),mid));log(s['user_id'],'edit_outbound_draft','outbound_message',mid,'Draft edited; not sent');return RedirectResponse('/outbound/'+str(mid),303)

@router.post('/outbound/{mid}/request-approval')
def request_approval(mid:int,request:Request):
    s=auth(request);m=one('SELECT * FROM outbound_messages WHERE id=?',(mid,))
    if not m or m['status']!='draft' or not m.get('recipient'): raise HTTPException(409,'Complete draft and recipient first')
    aid=execute('INSERT INTO approvals(kind,entity_type,entity_id,status,requested_by,notes,created_at) VALUES(?,?,?,?,?,?,?)',('external_send','outbound_message',mid,'pending',s['user_id'],'Approve exact recipient, subject, body and proposal before send',utcnow()));execute('UPDATE outbound_messages SET status=?,approval_id=?,updated_at=? WHERE id=?',('pending_approval',aid,utcnow(),mid));log(s['user_id'],'request_send_approval','outbound_message',mid,'Human approval requested');return RedirectResponse('/outbound/'+str(mid),303)

@router.post('/outbound/{mid}/approve')
def approve(mid:int,request:Request):
    s=auth(request)
    if s.get('role')!='admin': raise HTTPException(403)
    m=one('SELECT * FROM outbound_messages WHERE id=?',(mid,))
    if not m or m['status']!='pending_approval' or not m.get('approval_id'): raise HTTPException(409)
    now=utcnow();execute('UPDATE approvals SET status=?,decided_by=?,decided_at=? WHERE id=?',('approved',s['user_id'],now,m['approval_id']));execute('UPDATE outbound_messages SET status=?,approved_by=?,approved_at=?,updated_at=? WHERE id=?',('approved',s['user_id'],now,now,mid));log(s['user_id'],'approve_external_send','outbound_message',mid,'Approved exact outbound content');return RedirectResponse('/outbound/'+str(mid),303)

@router.post('/outbound/{mid}/reject')
def reject(mid:int,request:Request):
    s=auth(request)
    if s.get('role')!='admin': raise HTTPException(403)
    m=one('SELECT * FROM outbound_messages WHERE id=?',(mid,))
    if not m or m['status']!='pending_approval': raise HTTPException(409)
    now=utcnow();execute('UPDATE approvals SET status=?,decided_by=?,decided_at=? WHERE id=?',('rejected',s['user_id'],now,m['approval_id']));execute('UPDATE outbound_messages SET status=?,updated_at=? WHERE id=?',('rejected',now,mid));log(s['user_id'],'reject_external_send','outbound_message',mid,'Outbound rejected');return RedirectResponse('/outbound/'+str(mid),303)

@router.post('/outbound/{mid}/send')
def send(mid:int,request:Request):
    s=auth(request);m=one('SELECT * FROM outbound_messages WHERE id=?',(mid,))
    if not m or m['status']!='approved': raise HTTPException(409,'Message is not approved')
    a=one('SELECT * FROM approvals WHERE id=?',(m['approval_id'],))
    if not a or a['status']!='approved': raise HTTPException(409,'Approval missing')
    try:
        provider_id=send_gmail(s['user_id'],m['recipient'],m['subject'],m['body']+'\n\n'+(m.get('proposal_text') or ''));now=utcnow();execute('UPDATE outbound_messages SET status=?,provider=?,provider_message_id=?,sent_at=?,updated_at=?,last_error=NULL WHERE id=?',('sent','gmail',provider_id,now,now,mid));log(s['user_id'],'send_approved_message','outbound_message',mid,'Approved message sent via Gmail API')
    except Exception as e:
        safe=str(e)[:500];execute('UPDATE outbound_messages SET last_error=?,updated_at=? WHERE id=?',(safe,utcnow(),mid));raise HTTPException(503,safe)
    return RedirectResponse('/outbound/'+str(mid),303)

@router.get('/api/v7/outbound')
def api(request:Request):
    s=auth(request);c=connection(s['user_id']);return {'external_actions_enabled':os.getenv('ENABLE_EXTERNAL_ACTIONS','0')=='1','gmail_connected':bool(c and c.get('status')=='connected'),'messages':rows('SELECT id,opportunity_id,channel,recipient,subject,status,approval_id,provider,provider_message_id,sent_at,last_error FROM outbound_messages ORDER BY id DESC')}
