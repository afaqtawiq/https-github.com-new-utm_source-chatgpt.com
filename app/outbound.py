import os,html,urllib.parse,datetime
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import get_session,rows,one,execute,log,utcnow
from app.gmail_oauth import send_gmail,connection
from app.opportunity_quality import verify_public_request
router=APIRouter()
def esc(v): return html.escape(str(v or ''))
def auth(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s: raise HTTPException(401)
 return s
def parse(raw): return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def shell(t,b): return '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(t)+'</title><style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}.w{max-width:1250px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav a,.btn{display:inline-block;padding:10px 14px;border-radius:10px;background:#18384d;color:white;text-decoration:none;border:0;font-weight:700}.btn{background:#22c55e;color:#04130a;cursor:pointer}.danger{background:#ef4444;color:white}.muted{color:#9fb4c4}input,textarea{width:100%;box-sizing:border-box;padding:12px;margin:6px 0;border-radius:9px;border:1px solid #36586e;background:#081925;color:white}textarea{min-height:180px}table{width:100%;border-collapse:collapse}td,th{padding:11px;border-bottom:1px solid #28475d;text-align:right}.scroll{overflow:auto}</style><body><div class="w">'+b+'</div></body></html>'
def nav(): return '<div class="nav"><a href="/sales-center">مركز المبيعات</a><a href="/sales-today">مهام اليوم</a><a href="/sales-copilot">Sales Copilot</a><a href="/outbound">العروض والرسائل</a><a href="/sales-prospects">العملاء المحتملون</a><a href="/approvals">الموافقات</a><a href="/settings/email">إعداد البريد</a></div>'
def gmail_ready(uid):
 c=connection(uid);return bool(c and c.get('status')=='connected' and os.getenv('ENABLE_EXTERNAL_ACTIONS','0')=='1')
@router.post('/outbound/from-opportunity/{oid}')
def create_from_opportunity(oid:int,request:Request):
 s=auth(request);op=one('SELECT * FROM opportunities WHERE id=?',(oid,));intel=one('SELECT * FROM opportunity_intelligence WHERE opportunity_id=?',(oid,))
 if not op or not intel: raise HTTPException(400,'Generate Sales Copilot first')
 try: verify_public_request(op.get('source_url'))
 except Exception as exc: raise HTTPException(409,str(exc))
 body='السادة/ '+op['company_name']+'\n\nتحية طيبة،\nنود من آفاق طويق مناقشة احتياجكم المرتبط بـ '+(intel.get('services') or 'الخدمات اللوجستية')+'.\nيسعدنا دراسة نطاق العمل وتقديم الحل التشغيلي المناسب بعد التحقق من المتطلبات.\n\nمع التحية،\nآفاق طويق';mid=execute('INSERT INTO outbound_messages(opportunity_id,channel,subject,body,proposal_text,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(oid,'email','عرض خدمات لوجستية — آفاق طويق',body,intel.get('proposal_draft'),'draft',s['user_id'],utcnow(),utcnow()));log(s['user_id'],'create_outbound_draft','outbound_message',mid,'Draft created; not sent');return RedirectResponse('/outbound/'+str(mid),303)

from starlette.concurrency import run_in_threadpool
from app.storage import db
from app.social_publishing import hidden_csrf, csrf
from app.fine_permissions import has_permission
from app.official_sales import authorize, validate_reply
from app.mail_threads import address


def can_read_official(s):
 return s.get('role')=='admin' and has_permission(s,'manage_gmail')


def visible(s):
 return rows('''SELECT m.*,COALESCE(p.company_name,o.company_name) company_name FROM outbound_messages m LEFT JOIN opportunities o ON o.id=m.opportunity_id LEFT JOIN sales_prospects p ON p.id=m.prospect_id
    WHERE (m.reply_inbox_id IS NULL AND m.prospect_id IS NULL) OR (m.mail_user_id=? AND ?) ORDER BY m.id DESC''',
    (s['user_id'],can_read_official(s)))


def locked(c,mid,s):
 m=c.execute('SELECT * FROM outbound_messages WHERE id=%s FOR UPDATE',(mid,)).fetchone()
 if not m:raise HTTPException(404)
 authorize(s,m)
 return m


async def checked_form(request,s):
 raw=await request.body()
 if len(raw)>100000:raise HTTPException(413)
 d=parse(raw);csrf(s,d);return d


@router.get('/outbound',response_class=HTMLResponse)
def home(request:Request):
 s=auth(request);data=visible(s);c=connection(s['user_id']);ready=gmail_ready(s['user_id'])
 trs=''.join('<tr><td>'+esc(m['company_name'])+'</td><td>'+esc(m['recipient'])+'</td><td>'+esc(m['status'])+'</td><td><a class="btn" href="/outbound/'+str(m['id'])+'">فتح</a></td></tr>' for m in data)
 provider='البريد الرسمي' if (c or {}).get('provider')=='spacemail' else 'Gmail'
 return HTMLResponse(shell('الرسائل',nav()+'<h1>العروض والرسائل</h1><div class="card">'+provider+': '+('جاهز' if ready else 'غير جاهز')+' — كل إرسال يتطلب موافقة بشرية.</div><div class="card scroll"><table>'+trs+'</table></div>'))


@router.get('/outbound/{mid}',response_class=HTMLResponse)
def detail(mid:int,request:Request):
 s=auth(request);m=one('SELECT m.*,COALESCE(p.company_name,o.company_name) company_name FROM outbound_messages m LEFT JOIN opportunities o ON o.id=m.opportunity_id LEFT JOIN sales_prospects p ON p.id=m.prospect_id WHERE m.id=?',(mid,))
 if not m:raise HTTPException(404)
 authorize(s,m);token=hidden_csrf(s);base='/outbound/'+str(mid)
 if m['status']=='draft':
  fixed=' readonly' if m.get('reply_inbox_id') or m.get('prospect_id') else ''
  proposal='' if m.get('reply_inbox_id') or m.get('prospect_id') else '<textarea name="proposal_text">'+esc(m.get('proposal_text'))+'</textarea>'
  edit='<form method="post" action="'+base+'/update">'+token+'<input name="recipient" type="email" value="'+esc(m.get('recipient'))+'" required'+fixed+'><input name="subject" value="'+esc(m['subject'])+'" required><textarea name="body" required>'+esc(m['body'])+'</textarea>'+proposal+'<button class="btn">حفظ</button></form><form method="post" action="'+base+'/request-approval">'+token+'<button class="btn">طلب الموافقة</button></form>'
 elif m['status']=='pending_approval':
  edit='<div class="card">بانتظار الموافقة البشرية.</div>'+('<form method="post" action="'+base+'/approve">'+token+'<button class="btn">موافقة</button></form><form method="post" action="'+base+'/reject">'+token+'<button class="btn danger">رفض</button></form>' if s.get('role')=='admin' else '')
 elif m['status']=='approved':
  edit='<form method="post" action="'+base+'/send">'+token+'<button class="btn">إرسال الرسالة المعتمدة</button></form>'
 else:
  edit='<div class="card">الحالة: '+esc(m['status'])+(' — لا تعد الإرسال قبل التحقق من سجل البريد' if m['status'] in ('sending','uncertain') else '')+'</div>'
 context='<p>رد عبر البريد الرسمي داخل المحادثة الأصلية · <a href="/official-inbox">العودة إلى الوارد</a></p>' if m.get('reply_inbox_id') else ''
 if m.get('prospect_id'):context+='<p>تعريف أو رد لعميل محتمل، وليس طلب خدمة مؤكدًا · <a href="/sales-prospects/'+str(m['prospect_id'])+'">سجل العميل المحتمل</a></p>'
 if m['status']=='sent':context+='<p>قبل مزود البريد الرسالة؛ التسليم إلى صندوق المستلم غير مؤكد.</p>'
 return HTMLResponse(shell('رسالة',nav()+'<h1>'+esc(m['company_name'])+'</h1>'+context+'<div class="card"><b>الحالة:</b> '+esc(m['status'])+'<br><b>إلى:</b> '+esc(m.get('recipient'))+'<br><b>العنوان:</b> '+esc(m.get('subject'))+'<pre style="white-space:pre-wrap">'+esc(m.get('body'))+'</pre></div>'+edit),headers={'Cache-Control':'no-store'})


@router.post('/outbound/{mid}/update')
async def update(mid:int,request:Request):
 s=auth(request);d=await checked_form(request,s)
 with db() as c:
  m=locked(c,mid,s)
  if m['status']!='draft':raise HTTPException(409)
  recipient=d.get('recipient','').strip();subject=d.get('subject','').strip();body=d.get('body','')
  if not address(recipient) or not subject or len(subject)>1000 or any(v in subject for v in '\r\n'):raise HTTPException(400)
  if (m.get('reply_inbox_id') or m.get('prospect_id')) and recipient!=m['recipient']:raise HTTPException(409,'Reply recipient is fixed')
  proposal='' if m.get('reply_inbox_id') or m.get('prospect_id') else d.get('proposal_text','')
  c.execute('UPDATE outbound_messages SET recipient=%s,subject=%s,body=%s,proposal_text=%s,updated_at=%s WHERE id=%s',(recipient,subject,body,proposal,utcnow(),mid))
 log(s['user_id'],'edit_outbound_draft','outbound_message',mid,'Draft edited; not sent')
 return RedirectResponse('/outbound/'+str(mid),303)


@router.post('/outbound/{mid}/request-approval')
async def request_approval(mid:int,request:Request):
 s=auth(request);await checked_form(request,s)
 with db() as c:
  m=locked(c,mid,s)
  if m['status']!='draft' or not address(m.get('recipient')) or not m.get('body','').strip():raise HTTPException(409)
  if m.get('reply_inbox_id'):validate_reply(c,m,s['user_id'])
  elif m.get('purpose')=='intro_prospect':
   from app.prospect_outreach import validate_intro
   validate_intro(c,m,s['user_id'],verify=False)
  a=c.execute('INSERT INTO approvals(kind,entity_type,entity_id,status,requested_by,notes,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id',('external_send','outbound_message',mid,'pending',s['user_id'],'Approve exact recipient, subject, body and proposal before send',utcnow())).fetchone()
  c.execute("UPDATE outbound_messages SET status='pending_approval',approval_id=%s,updated_at=%s WHERE id=%s",(a['id'],utcnow(),mid))
 log(s['user_id'],'request_send_approval','outbound_message',mid,'Human approval requested')
 return RedirectResponse('/outbound/'+str(mid),303)


async def decide(mid,request,approved):
 s=auth(request)
 if s.get('role')!='admin':raise HTTPException(403)
 await checked_form(request,s)
 with db() as c:
  m=locked(c,mid,s)
  if m['status']!='pending_approval':raise HTTPException(409)
  a=c.execute("SELECT * FROM approvals WHERE id=%s AND entity_type='outbound_message' AND entity_id=%s AND kind='external_send' AND status='pending' FOR UPDATE",(m['approval_id'],mid)).fetchone()
  if not a:raise HTTPException(409,'Approval identity mismatch')
  digest=None
  if approved and m.get('prospect_id'):
   from app.prospect_outreach import content_digest,validate_intro
   if m.get('reply_inbox_id'):validate_reply(c,m,s['user_id'])
   else:validate_intro(c,m,s['user_id'],verify=False)
   digest=content_digest(m)
  now=utcnow();state='approved' if approved else 'rejected'
  c.execute('UPDATE approvals SET status=%s,decided_by=%s,decided_at=%s WHERE id=%s',(state,s['user_id'],now,a['id']))
  c.execute('UPDATE outbound_messages SET status=%s,approved_by=%s,approved_at=%s,approval_digest=%s,updated_at=%s WHERE id=%s',(state,s['user_id'] if approved else None,now if approved else None,digest,now,mid))
 log(s['user_id'],'approve_external_send' if approved else 'reject_external_send','outbound_message',mid,'Exact outbound content decision')
 return RedirectResponse('/outbound/'+str(mid),303)


@router.post('/outbound/{mid}/approve')
async def approve(mid:int,request:Request):
 return await decide(mid,request,True)


@router.post('/outbound/{mid}/reject')
async def reject(mid:int,request:Request):
 return await decide(mid,request,False)


@router.post('/outbound/{mid}/send')
async def send(mid:int,request:Request):
 s=auth(request);await checked_form(request,s)
 return await run_in_threadpool(send_approved,mid,s)


def send_approved(mid,s):
 if os.getenv('ENABLE_EXTERNAL_ACTIONS','0')!='1':raise HTTPException(409,'External actions are disabled')
 if not has_permission(s,'send_email'):raise HTTPException(403)
 from app.mfa_stepup import recent_stepup
 if not recent_stepup(s['id']):raise HTTPException(428)
 selected=connection(s['user_id'])
 if not selected or selected.get('status')!='connected':raise HTTPException(409,'Email is not connected')
 parent=None
 with db() as c:
  m=locked(c,mid,s)
  if m['status']!='approved':raise HTTPException(409,'Message is not approved or was already attempted')
  a=c.execute("SELECT id FROM approvals WHERE id=%s AND entity_type='outbound_message' AND entity_id=%s AND kind='external_send' AND status='approved' FOR UPDATE",(m['approval_id'],mid)).fetchone()
  if not a:raise HTTPException(409,'Approval missing or mismatched')
  if m.get('prospect_id'):
   from app.prospect_outreach import content_digest
   import hmac
   if not m.get('approval_digest') or not hmac.compare_digest(m['approval_digest'],content_digest(m)):raise HTTPException(409,'Approved prospect content changed')
   if selected.get('provider')!='spacemail' or selected.get('sender_email')!='afaq@shodai.cc':raise HTTPException(409,'Official mailbox is required')
  if m.get('reply_inbox_id'):
   if selected.get('provider')!='spacemail':raise HTTPException(409,'Official mailbox is required')
   parent=validate_reply(c,m,s['user_id'])
  elif m.get('purpose')=='intro_prospect':
   from app.prospect_outreach import validate_intro
   validate_intro(c,m,s['user_id'])
  else:
   op=c.execute('SELECT source_url FROM opportunities WHERE id=%s',(m['opportunity_id'],)).fetchone()
   try:verify_public_request((op or {}).get('source_url'),m.get('recipient'))
   except Exception as exc:raise HTTPException(409,str(exc))
  c.execute("UPDATE outbound_messages SET status='sending',mail_user_id=%s,updated_at=%s WHERE id=%s",(s['user_id'],utcnow(),mid))
 try:
  if parent:
   from app.spacemail import send as official_send
   provider_id=official_send(s['user_id'],m['recipient'],m['subject'],m['body'],in_reply_to=parent['message_id'],references=parent.get('message_references'))
   provider='spacemail'
  elif m.get('purpose')=='intro_prospect':
   from app.spacemail import send as official_send
   provider_id=official_send(s['user_id'],m['recipient'],m['subject'],m['body'])
   provider='spacemail'
  else:
   result=send_gmail(s['user_id'],m['recipient'],m['subject'],m['body']+'\n\n'+(m.get('proposal_text') or ''),return_metadata=True)
   provider_id,provider=result['message_id'],result['provider']
  if not provider_id:raise RuntimeError('Missing provider receipt')
 except Exception:
  execute("UPDATE outbound_messages SET status='uncertain',last_error=?,updated_at=? WHERE id=? AND status='sending'",('تعذر تأكيد الإرسال؛ تحقق من البريد قبل أي محاولة أخرى.',utcnow(),mid))
  raise HTTPException(503,'تعذر تأكيد الإرسال؛ لن يُعاد تلقائيًا. راجع سجل البريد.') from None
 now=utcnow()
 with db() as c:
  c.execute("UPDATE outbound_messages SET status='sent',provider=%s,provider_message_id=%s,sent_at=%s,updated_at=%s,last_error=NULL WHERE id=%s AND status='sending'",(provider,provider_id,now,now,mid))
  # A reply does not invent a new outreach cadence or overwrite the sales stage.
  if m.get('purpose')=='intro_prospect':
   c.execute("UPDATE sales_prospects SET status='contacted',updated_at=%s WHERE id=%s AND status='prospect_verified'",(now,m['prospect_id']))
  elif not parent:
   c.execute("UPDATE opportunities SET stage='contacted',updated_at=%s WHERE id=%s AND stage NOT IN ('won','lost')",(now,m['opportunity_id']))
   existing=c.execute("SELECT id FROM sales_followups WHERE opportunity_id=%s AND status='open' LIMIT 1",(m['opportunity_id'],)).fetchone()
   if not existing:c.execute("INSERT INTO sales_followups(opportunity_id,outbound_message_id,kind,due_at,status,notes,created_by,created_at) VALUES(%s,%s,'follow_up',%s,'open',%s,%s,%s)",(m['opportunity_id'],mid,now+datetime.timedelta(days=3),'متابعة بعد الإرسال: تحقق من الرد وحدد الإجراء التالي.',s['user_id'],now))
 if provider=='spacemail':
  from app.official_sales import ingest
  ingest(s['user_id'],True)
 log(s['user_id'],'send_approved_message','outbound_message',mid,'Approved '+provider+' accepted by provider; delivery unconfirmed')
 return RedirectResponse('/outbound/'+str(mid),303)


@router.get('/api/v7/outbound')
def api(request:Request):
 s=auth(request);c=connection(s['user_id']);data=visible(s)
 keys=('id','purpose','prospect_id','opportunity_id','recipient','subject','status','provider','provider_message_id','sent_at','last_error')
 return {'external_actions_enabled':os.getenv('ENABLE_EXTERNAL_ACTIONS','0')=='1','gmail_connected':bool(c and c.get('status')=='connected'),'provider':(c or {}).get('provider'),'messages':[{k:m.get(k) for k in keys} for m in data]}
