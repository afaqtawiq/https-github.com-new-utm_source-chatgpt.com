import os,html,urllib.parse,datetime
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
def shell(t,b): return '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(t)+'</title><style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}.w{max-width:1250px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav a,.btn{display:inline-block;padding:10px 14px;border-radius:10px;background:#18384d;color:white;text-decoration:none;border:0;font-weight:700}.btn{background:#22c55e;color:#04130a;cursor:pointer}.danger{background:#ef4444;color:white}.muted{color:#9fb4c4}input,textarea{width:100%;box-sizing:border-box;padding:12px;margin:6px 0;border-radius:9px;border:1px solid #36586e;background:#081925;color:white}textarea{min-height:180px}table{width:100%;border-collapse:collapse}td,th{padding:11px;border-bottom:1px solid #28475d;text-align:right}.scroll{overflow:auto}</style><body><div class="w">'+b+'</div></body></html>'
def nav(): return '<div class="nav"><a href="/sales-center">مركز المبيعات</a><a href="/sales-today">مهام اليوم</a><a href="/sales-copilot">Sales Copilot</a><a href="/outbound">العروض والرسائل</a><a href="/approvals">الموافقات</a><a href="/settings/email">إعداد البريد</a></div>'
def gmail_ready(uid):
 c=connection(uid);return bool(c and c.get('status')=='connected' and os.getenv('ENABLE_EXTERNAL_ACTIONS','0')=='1')
@router.get('/outbound',response_class=HTMLResponse)
def home(request:Request):
 s=auth(request);data=rows('SELECT m.*,o.company_name FROM outbound_messages m JOIN opportunities o ON o.id=m.opportunity_id ORDER BY m.id DESC');ready=gmail_ready(s['user_id']);trs=''.join('<tr><td>'+esc(m['company_name'])+'</td><td>'+esc(m['recipient'])+'</td><td>'+esc(m['status'])+'</td><td><a class="btn" href="/outbound/'+str(m['id'])+'">فتح</a></td></tr>' for m in data);return HTMLResponse(shell('الرسائل',nav()+'<h1>العروض والرسائل</h1><div class="card">Gmail: '+('جاهز' if ready else 'غير جاهز')+' — كل إرسال يتطلب موافقة بشرية.</div><div class="card scroll"><table>'+trs+'</table></div>'))
@router.post('/outbound/from-opportunity/{oid}')
def create_from_opportunity(oid:int,request:Request):
 s=auth(request);op=one('SELECT * FROM opportunities WHERE id=?',(oid,));intel=one('SELECT * FROM opportunity_intelligence WHERE opportunity_id=?',(oid,))
 if not op or not intel: raise HTTPException(400,'Generate Sales Copilot first')
 body='السادة/ '+op['company_name']+'\n\nتحية طيبة،\nنود من آفاق طويق مناقشة احتياجكم المرتبط بـ '+(intel.get('services') or 'الخدمات اللوجستية')+'.\nيسعدنا دراسة نطاق العمل وتقديم الحل التشغيلي المناسب بعد التحقق من المتطلبات.\n\nمع التحية،\nآفاق طويق';mid=execute('INSERT INTO outbound_messages(opportunity_id,channel,subject,body,proposal_text,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(oid,'email','عرض خدمات لوجستية — آفاق طويق',body,intel.get('proposal_draft'),'draft',s['user_id'],utcnow(),utcnow()));log(s['user_id'],'create_outbound_draft','outbound_message',mid,'Draft created; not sent');return RedirectResponse('/outbound/'+str(mid),303)
@router.get('/outbound/{mid}',response_class=HTMLResponse)
def detail(mid:int,request:Request):
 s=auth(request);m=one('SELECT m.*,o.company_name FROM outbound_messages m JOIN opportunities o ON o.id=m.opportunity_id WHERE m.id=?',(mid,))
 if not m: raise HTTPException(404)
 if m['status']=='draft':edit='<form method="post" action="/outbound/'+str(mid)+'/update"><input name="recipient" type="email" value="'+esc(m.get('recipient'))+'" placeholder="البريد الموثق" required><input name="subject" value="'+esc(m['subject'])+'" required><textarea name="body">'+esc(m['body'])+'</textarea><textarea name="proposal_text">'+esc(m.get('proposal_text'))+'</textarea><button class="btn">حفظ</button></form><form method="post" action="/outbound/'+str(mid)+'/request-approval"><button class="btn">طلب الموافقة</button></form>'
 elif m['status']=='pending_approval':edit='<div class="card">بانتظار الموافقة البشرية.</div>'+('<form method="post" action="/outbound/'+str(mid)+'/approve"><button class="btn">موافقة</button></form><form method="post" action="/outbound/'+str(mid)+'/reject"><button class="btn danger">رفض</button></form>' if s.get('role')=='admin' else '')
 elif m['status']=='approved':edit='<form method="post" action="/outbound/'+str(mid)+'/send"><button class="btn">إرسال الرسالة المعتمدة</button></form>'
 else:edit='<div class="card">الحالة: '+esc(m['status'])+'</div>'
 return HTMLResponse(shell('رسالة',nav()+'<h1>'+esc(m['company_name'])+'</h1><div class="card"><b>الحالة:</b> '+esc(m['status'])+'<br><b>إلى:</b> '+esc(m.get('recipient'))+'<br><b>العنوان:</b> '+esc(m.get('subject'))+'<pre style="white-space:pre-wrap">'+esc(m.get('body'))+'</pre></div>'+edit))
@router.post('/outbound/{mid}/update')
async def update(mid:int,request:Request):
 s=auth(request);m=one('SELECT * FROM outbound_messages WHERE id=?',(mid,));
 if not m or m['status']!='draft': raise HTTPException(409)
 d=parse(await request.body());execute('UPDATE outbound_messages SET recipient=?,subject=?,body=?,proposal_text=?,updated_at=? WHERE id=?',(d.get('recipient','').strip(),d.get('subject',''),d.get('body',''),d.get('proposal_text',''),utcnow(),mid));log(s['user_id'],'edit_outbound_draft','outbound_message',mid,'Draft edited; not sent');return RedirectResponse('/outbound/'+str(mid),303)
@router.post('/outbound/{mid}/request-approval')
def request_approval(mid:int,request:Request):
 s=auth(request);m=one('SELECT * FROM outbound_messages WHERE id=?',(mid,));
 if not m or m['status']!='draft' or not m.get('recipient'): raise HTTPException(409)
 aid=execute('INSERT INTO approvals(kind,entity_type,entity_id,status,requested_by,notes,created_at) VALUES(?,?,?,?,?,?,?)',('external_send','outbound_message',mid,'pending',s['user_id'],'Approve exact recipient, subject, body and proposal before send',utcnow()));execute('UPDATE outbound_messages SET status=?,approval_id=?,updated_at=? WHERE id=?',('pending_approval',aid,utcnow(),mid));log(s['user_id'],'request_send_approval','outbound_message',mid,'Human approval requested');return RedirectResponse('/outbound/'+str(mid),303)
@router.post('/outbound/{mid}/approve')
def approve(mid:int,request:Request):
 s=auth(request)
 if s.get('role')!='admin':raise HTTPException(403)
 m=one('SELECT * FROM outbound_messages WHERE id=?',(mid,));
 if not m or m['status']!='pending_approval':raise HTTPException(409)
 now=utcnow();execute('UPDATE approvals SET status=?,decided_by=?,decided_at=? WHERE id=?',('approved',s['user_id'],now,m['approval_id']));execute('UPDATE outbound_messages SET status=?,approved_by=?,approved_at=?,updated_at=? WHERE id=?',('approved',s['user_id'],now,now,mid));log(s['user_id'],'approve_external_send','outbound_message',mid,'Approved exact outbound content');return RedirectResponse('/outbound/'+str(mid),303)
@router.post('/outbound/{mid}/reject')
def reject(mid:int,request:Request):
 s=auth(request)
 if s.get('role')!='admin':raise HTTPException(403)
 m=one('SELECT * FROM outbound_messages WHERE id=?',(mid,));now=utcnow();execute('UPDATE approvals SET status=?,decided_by=?,decided_at=? WHERE id=?',('rejected',s['user_id'],now,m['approval_id']));execute('UPDATE outbound_messages SET status=?,updated_at=? WHERE id=?',('rejected',now,mid));return RedirectResponse('/outbound/'+str(mid),303)
@router.post('/outbound/{mid}/send')
def send(mid:int,request:Request):
 s=auth(request);m=one('SELECT * FROM outbound_messages WHERE id=?',(mid,));
 if not m or m['status']!='approved':raise HTTPException(409,'Message is not approved')
 a=one('SELECT * FROM approvals WHERE id=?',(m['approval_id'],));
 if not a or a['status']!='approved':raise HTTPException(409,'Approval missing')
 try:
  provider_id=send_gmail(s['user_id'],m['recipient'],m['subject'],m['body']+'\n\n'+(m.get('proposal_text') or ''));now=utcnow();execute('UPDATE outbound_messages SET status=?,provider=?,provider_message_id=?,sent_at=?,updated_at=?,last_error=NULL WHERE id=?',('sent','gmail',provider_id,now,now,mid));execute('UPDATE opportunities SET stage=?,updated_at=? WHERE id=? AND stage NOT IN (?,?)',('contacted',now,m['opportunity_id'],'won','lost'));existing=one("SELECT COUNT(*) n FROM sales_followups WHERE opportunity_id=? AND status='open'",(m['opportunity_id'],))['n'];
  if not existing:execute('INSERT INTO sales_followups(opportunity_id,kind,due_at,status,notes,created_by,created_at) VALUES(?,?,?,?,?,?,?)',(m['opportunity_id'],'follow_up',now+datetime.timedelta(days=3),'open','متابعة تلقائية بعد الإرسال: تحقق من الرد وحدد الإجراء التالي.',s['user_id'],now))
  log(s['user_id'],'send_approved_message','outbound_message',mid,'Approved Gmail sent; follow-up scheduled')
 except Exception as e:
  safe=str(e)[:500];execute('UPDATE outbound_messages SET last_error=?,updated_at=? WHERE id=?',(safe,utcnow(),mid));raise HTTPException(503,safe)
 return RedirectResponse('/outbound/'+str(mid),303)
@router.get('/api/v7/outbound')
def api(request:Request):
 s=auth(request);c=connection(s['user_id']);return {'external_actions_enabled':os.getenv('ENABLE_EXTERNAL_ACTIONS','0')=='1','gmail_connected':bool(c and c.get('status')=='connected'),'messages':rows('SELECT id,opportunity_id,recipient,subject,status,provider_message_id,sent_at,last_error FROM outbound_messages ORDER BY id DESC')}
