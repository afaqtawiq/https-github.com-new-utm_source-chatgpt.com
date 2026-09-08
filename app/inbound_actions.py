import html,datetime
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import get_session,one,rows,execute,log,utcnow
router=APIRouter()
def esc(v):return html.escape(str(v or ''))
def auth(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s
def nav():return '<div><a href="/sales-inbox" style="color:white;margin-left:12px">ردود العملاء</a><a href="/sales-actions" style="color:white;margin-left:12px">إجراءات الردود</a><a href="/sales-center" style="color:white;margin-left:12px">مركز المبيعات</a><a href="/outbound" style="color:white">الرسائل</a></div>'
def shell(b):return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}.w{max-width:1200px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:18px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.btn{display:inline-block;padding:10px 14px;border:0;border-radius:9px;background:#22c55e;color:#04130a;text-decoration:none;font-weight:bold}.muted{color:#9fb4c4}pre{white-space:pre-wrap;font-family:Arial;line-height:1.7}table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #28475d;text-align:right;vertical-align:top}</style><body><div class="w">'+b+'</div></body></html>')
def build_action(reply,op,intel):
 cls=reply['classification'];services=(intel or {}).get('services') or 'الخدمات اللوجستية';company=op['company_name'];sender=reply['sender'];subj=reply.get('subject') or 'طلبكم لدى آفاق طويق'
 common='الخدمة المطلوبة: '+services+'\nالجهة: '+company+'\nالبريد: '+sender
 if cls=='quote_request':
  req=common+'\n\nالمطلوب للتحقق قبل التسعير:\n- نوع الخدمة والمسار (من/إلى)\n- نوع البضاعة ووصفها\n- الكمية/الوزن/الحجم أو عدد الحاويات/الشاحنات\n- المنفذ أو الميناء إن وجد\n- الموعد المتوقع\n- أي متطلبات جمركية أو تخزين خاصة'
  body='مرحبًا،\n\nشكرًا لتواصلكم مع آفاق طويق وطلب عرض السعر.\n\nحتى نعد عرضًا دقيقًا ومناسبًا، نرجو تزويدنا بنطاق الخدمة والمسار، نوع البضاعة، الكمية أو الوزن/الحجم، الموعد المتوقع، وأي متطلبات جمركية أو تخزين خاصة.\n\nبعد استلام التفاصيل سنراجعها ونجهز العرض المناسب.\n\nمع التحية،\nآفاق طويق'
  notes='لا يتم إدخال سعر تلقائي. يجب مراجعة النطاق والتكلفة التشغيلية واعتماد العرض قبل الإرسال.';action='prepare_quote'
 elif cls=='meeting_request':
  req=common+'\n\nالمطلوب: تحديد هدف الاجتماع، المشاركين، والوقت المناسب.';body='مرحبًا،\n\nشكرًا لتواصلكم. يسعد فريق آفاق طويق ترتيب اجتماع لمناقشة احتياجكم اللوجستي وتحديد نطاق العمل.\n\nنرجو مشاركة الوقت المناسب لكم، وسنؤكد الموعد بعد المراجعة.\n\nمع التحية،\nآفاق طويق';notes='يجب التأكد من توفر الفريق قبل اعتماد الموعد.';action='schedule_meeting'
 elif cls=='not_interested':
  req=common+'\n\nلا توجد متابعة بيعية مطلوبة إلا إذا طلب العميل ذلك لاحقًا.';body='مرحبًا،\n\nشكرًا لتوضيحكم. نحترم قراركم ولن نتابع بخصوص هذا العرض.\n\nيسعدنا خدمتكم مستقبلًا عند الحاجة.\n\nمع التحية،\nآفاق طويق';notes='راجع قبل الإرسال؛ يمكن إغلاق الفرصة بدل إرسال رد إذا كان الأنسب.';action='close_or_acknowledge'
 else:
  req=common+'\n\nالمطلوب: مراجعة رد العميل وتحديد نطاق الخدمة والخطوة التالية.';body='مرحبًا،\n\nشكرًا لتواصلكم مع آفاق طويق. اطلعنا على رسالتكم وسنراجع احتياجكم ونعود لكم بالخطوة المناسبة بعد التحقق من نطاق العمل.\n\nمع التحية،\nآفاق طويق';notes='تخصيص الرد حسب محتوى العميل قبل طلب الموافقة.';action='qualify_and_reply'
 return action,req,body,notes,('Re: '+subj if not subj.lower().startswith('re:') else subj)
@router.get('/sales-actions')
def queue(request:Request):
 auth(request);data=rows('''SELECT r.id,r.sender,r.subject,r.classification,r.confidence,r.status,r.received_at,o.company_name,a.id action_id,a.action_type,a.outbound_message_id FROM inbound_replies r LEFT JOIN opportunities o ON o.id=r.opportunity_id LEFT JOIN sales_response_actions a ON a.inbound_reply_id=r.id ORDER BY r.received_at DESC,r.id DESC LIMIT 200''')
 trs=''
 for x in data:
  if x.get('action_id'):act='<a class="btn" href="/sales-action/'+str(x['action_id'])+'">فتح الإجراء</a>'
  else:act='<form method="post" action="/sales-inbox/'+str(x['id'])+'/prepare-action"><button class="btn">تجهيز الإجراء المقترح</button></form>'
  trs+='<tr><td>'+esc(x.get('company_name'))+'</td><td>'+esc(x['sender'])+'</td><td>'+esc(x['classification'])+' '+str(x['confidence'])+'%</td><td>'+esc(x['status'])+'</td><td>'+act+'</td></tr>'
 return shell(nav()+'<h1>إجراءات ردود العملاء</h1><div class="card muted">يحوّل رد العميل إلى إجراء بيعي ومسودة رد فقط. لا يتم إرسال أي شيء دون مراجعة وموافقة بشرية.</div><div class="card"><table><tr><th>العميل</th><th>المرسل</th><th>التصنيف</th><th>الحالة</th><th>الإجراء</th></tr>'+trs+'</table></div>')
@router.post('/sales-inbox/{rid}/prepare-action')
def prepare(rid:int,request:Request):
 s=auth(request);r=one('SELECT * FROM inbound_replies WHERE id=?',(rid,))
 if not r or not r.get('opportunity_id'):raise HTTPException(404)
 existing=one('SELECT * FROM sales_response_actions WHERE inbound_reply_id=?',(rid,))
 if existing:return RedirectResponse('/sales-action/'+str(existing['id']),303)
 op=one('SELECT * FROM opportunities WHERE id=?',(r['opportunity_id'],));intel=one('SELECT * FROM opportunity_intelligence WHERE opportunity_id=?',(r['opportunity_id'],));action,req,body,notes,subject=build_action(r,op,intel);now=utcnow()
 mid=execute('INSERT INTO outbound_messages(opportunity_id,channel,recipient,subject,body,proposal_text,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(r['opportunity_id'],'email',r['sender'],subject,body,notes,'draft',s['user_id'],now,now))
 aid=execute('INSERT INTO sales_response_actions(inbound_reply_id,opportunity_id,action_type,requirements,suggested_response,proposal_notes,outbound_message_id,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(rid,r['opportunity_id'],action,req,body,notes,mid,'prepared',s['user_id'],now,now))
 execute('UPDATE inbound_replies SET status=?,updated_at=? WHERE id=?',('action_prepared',now,rid));due=now+datetime.timedelta(days=1);execute('INSERT INTO sales_followups(opportunity_id,kind,due_at,status,notes,created_by,created_at) VALUES(?,?,?,?,?,?,?)',(r['opportunity_id'],'inbound_action',due,'open','مراجعة رد العميل وتجهيز الإجراء/العرض المقترح.',s['user_id'],now));log(s['user_id'],'prepare_inbound_sales_action','sales_response_action',aid,'Prepared action and outbound draft; no external send');return RedirectResponse('/sales-action/'+str(aid),303)
@router.get('/sales-action/{aid}')
def detail(aid:int,request:Request):
 auth(request);a=one('''SELECT a.*,r.sender,r.subject,r.body_text,r.classification,o.company_name FROM sales_response_actions a JOIN inbound_replies r ON r.id=a.inbound_reply_id JOIN opportunities o ON o.id=a.opportunity_id WHERE a.id=?''',(aid,))
 if not a:raise HTTPException(404)
 b=nav()+'<h1>إجراء مبيعات مقترح — '+esc(a['company_name'])+'</h1><div class="grid"><div class="card"><b>تصنيف الرد</b><h2>'+esc(a['classification'])+'</h2></div><div class="card"><b>الإجراء</b><h2>'+esc(a['action_type'])+'</h2></div><div class="card"><b>الحالة</b><h2>'+esc(a['status'])+'</h2></div></div><div class="card"><h2>متطلبات التأهيل/التسعير</h2><pre>'+esc(a['requirements'])+'</pre></div><div class="card"><h2>الرد المقترح</h2><pre>'+esc(a['suggested_response'])+'</pre></div><div class="card"><h2>ضوابط العرض</h2><pre>'+esc(a['proposal_notes'])+'</pre></div><div class="card"><a class="btn" href="/outbound/'+str(a['outbound_message_id'])+'">فتح مسودة الرد للمراجعة والموافقة</a> <a class="btn" href="/sales-workspace/'+str(a['opportunity_id'])+'">ملف العميل</a></div><div class="card muted">لم يتم إرسال أي شيء للعميل. المسودة تمر بمراجعة وموافقة بشرية قبل Gmail.</div>'
 return shell(b)
@router.get('/api/v7/sales-actions')
def api(request:Request):
 auth(request);return {'actions':rows('SELECT id,inbound_reply_id,opportunity_id,action_type,status,outbound_message_id,created_at FROM sales_response_actions ORDER BY id DESC')}
