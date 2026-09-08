import base64,datetime,html,re,email.utils
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import get_session,rows,one,execute,log,utcnow
from app.gmail_oauth import connection,has_reply_read_scope,gmail_get
router=APIRouter()
def esc(v):return html.escape(str(v or ''))
def auth(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s
def shell(b):return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}.w{max-width:1300px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:18px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.btn{display:inline-block;padding:9px 12px;border:0;border-radius:9px;background:#22c55e;color:#04130a;text-decoration:none;font-weight:bold}.muted{color:#9fb4c4}.pill{display:inline-block;padding:5px 9px;background:#18384d;border-radius:999px}table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #28475d;text-align:right;vertical-align:top}.nav a{color:white;margin-left:12px}</style><body><div class="w">'+b+'</div></body></html>')
def nav():return '<div class="nav"><a href="/sales-center">مركز المبيعات</a><a href="/sales-today">مهام اليوم</a><a href="/sales-inbox">ردود العملاء</a><a href="/sales-performance">Conversion & Revenue</a><a href="/settings/email">إعداد Gmail</a></div>'
def hdrs(msg):return {x.get('name','').lower():x.get('value','') for x in (msg.get('payload',{}).get('headers') or [])}
def b64(s):
 try:return base64.urlsafe_b64decode(s+'='*((4-len(s)%4)%4)).decode('utf-8','replace')
 except:return ''
def body_text(payload):
 if payload.get('mimeType')=='text/plain' and payload.get('body',{}).get('data'):return b64(payload['body']['data'])
 for p in payload.get('parts') or []:
  t=body_text(p)
  if t:return t
 return ''
def classify(text):
 t=(text or '').lower()
 rules=[('quote_request',['عرض سعر','السعر','تكلفة','quotation','quote','pricing','price']),('meeting_request',['اجتماع','موعد','مكالمة','meeting','call','schedule']),('interested',['مهتم','نرغب','نود','يرجى التواصل','interested','please contact','sounds good']),('not_interested',['غير مهتم','لا نرغب','لا حاجة','not interested','no thanks','do not contact']),('more_info',['تفاصيل','معلومات','ارسل','send details','more information','details'])]
 for label,terms in rules:
  hits=sum(1 for x in terms if x in t)
  if hits:return label,min(95,65+hits*10)
 return 'needs_review',40
def parse_received(v):
 try:return email.utils.parsedate_to_datetime(v).astimezone(datetime.timezone.utc)
 except:return utcnow()
def sender_email(v):
 m=re.search(r'<([^>]+)>',v or '')
 return (m.group(1) if m else (v or '')).strip().lower()
def sync_replies(uid):
 c=connection(uid)
 if not c or not has_reply_read_scope(c):raise RuntimeError('أعد ربط Gmail ووافق على صلاحية قراءة الردود أولًا')
 sent=rows("SELECT m.*,o.company_name FROM outbound_messages m JOIN opportunities o ON o.id=m.opportunity_id WHERE m.status='sent' AND m.provider='gmail' AND m.provider_message_id IS NOT NULL ORDER BY m.sent_at DESC LIMIT 100")
 added=0;checked=0
 own=(c.get('sender_email') or '').lower()
 for m in sent:
  try:
   meta=gmail_get(uid,'/messages/'+m['provider_message_id'],{'format':'metadata'});tid=meta.get('threadId')
   if not tid:continue
   thread=gmail_get(uid,'/threads/'+tid,{'format':'full'});checked+=1
   for gm in thread.get('messages') or []:
    gid=gm.get('id');h=hdrs(gm);frm=sender_email(h.get('from',''))
    if not gid or not frm or frm==own:continue
    recv=parse_received(h.get('date',''))
    if m.get('sent_at') and recv<=m['sent_at']:continue
    if one('SELECT id FROM inbound_replies WHERE gmail_message_id=?',(gid,)):continue
    txt=body_text(gm.get('payload') or {})[:12000];cl,conf=classify(txt or gm.get('snippet',''))
    rid=execute('INSERT INTO inbound_replies(gmail_message_id,gmail_thread_id,opportunity_id,matched_outbound_id,sender,subject,snippet,body_text,classification,confidence,status,received_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(gid,tid,m['opportunity_id'],m['id'],frm,h.get('subject',''),gm.get('snippet',''),txt,cl,conf,'new',recv,utcnow(),utcnow()));added+=1
    execute("UPDATE opportunities SET stage=?,updated_at=? WHERE id=? AND stage NOT IN ('won','lost','test')",('responded',utcnow(),m['opportunity_id']))
    execute("UPDATE sales_followups SET status='done',completed_at=? WHERE opportunity_id=? AND status='open' AND kind IN ('follow_up','value_followup','final_followup')",(utcnow(),m['opportunity_id']))
    log(uid,'ingest_customer_reply','inbound_reply',rid,'Matched Gmail reply to opportunity; classified '+cl)
  except Exception:
   continue
 return checked,added
@router.get('/sales-inbox')
def inbox(request:Request):
 s=auth(request);c=connection(s['user_id']);read_ok=has_reply_read_scope(c);data=rows('SELECT r.*,o.company_name FROM inbound_replies r LEFT JOIN opportunities o ON o.id=r.opportunity_id ORDER BY r.received_at DESC,r.id DESC LIMIT 200')
 trs=''.join('<tr><td>'+esc(x.get('company_name'))+'</td><td>'+esc(x['sender'])+'</td><td>'+esc(x['subject'])+'</td><td><span class="pill">'+esc(x['classification'])+'</span> '+str(x['confidence'])+'%</td><td>'+esc(x['received_at'])+'</td><td><a class="btn" href="/sales-inbox/'+str(x['id'])+'">فتح</a></td></tr>' for x in data)
 notice=('<form method="post" action="/sales-inbox/sync"><button class="btn">مزامنة ردود العملاء الآن</button></form>' if read_ok else '<div class="card"><b>قراءة الردود غير مفعلة.</b><p>أعد ربط Gmail من إعداد البريد ووافق على صلاحية القراءة للردود.</p><a class="btn" href="/settings/email">إعداد Gmail</a></div>')
 return shell(nav()+'<h1>ردود العملاء</h1><div class="card"><b>الخصوصية:</b> النظام يتتبع فقط محادثات Gmail التي بدأها من رسائل مبيعات مسجلة في CRM، ولا ينفذ أي رد تلقائي.</div>'+notice+'<div class="card"><table><tr><th>العميل</th><th>المرسل</th><th>العنوان</th><th>التصنيف</th><th>الوصول</th><th></th></tr>'+trs+'</table></div>')
@router.post('/sales-inbox/sync')
def sync(request:Request):
 s=auth(request)
 try:checked,added=sync_replies(s['user_id']);log(s['user_id'],'sync_sales_inbox',summary=f'Checked {checked} threads; added {added} replies')
 except Exception as e:raise HTTPException(409,str(e)[:300])
 return RedirectResponse('/sales-inbox',303)
@router.get('/sales-inbox/{rid}')
def detail(rid:int,request:Request):
 auth(request);r=one('SELECT r.*,o.company_name FROM inbound_replies r LEFT JOIN opportunities o ON o.id=r.opportunity_id WHERE r.id=?',(rid,));
 if not r:raise HTTPException(404)
 actions={'quote_request':'تجهيز عرض سعر بعد التحقق من النطاق والكميات والمسارات.','meeting_request':'اقتراح موعد اجتماع أو مكالمة.','interested':'تأهيل الاحتياج وتحديد الخطوة التالية.','not_interested':'احترام الرفض وإغلاق أو تجميد المتابعة.','more_info':'تجهيز معلومات إضافية مخصصة.','needs_review':'مراجعة الرد يدويًا وتحديد النية.'};next_action=actions.get(r['classification'],'مراجعة يدوية')
 b=nav()+'<h1>'+esc(r.get('company_name') or r['sender'])+'</h1><div class="grid"><div class="card"><b>التصنيف</b><h2>'+esc(r['classification'])+'</h2><span>'+str(r['confidence'])+'%</span></div><div class="card"><b>الإجراء المقترح</b><p>'+esc(next_action)+'</p></div></div><div class="card"><b>من:</b> '+esc(r['sender'])+'<br><b>العنوان:</b> '+esc(r['subject'])+'<pre style="white-space:pre-wrap">'+esc(r['body_text'] or r['snippet'])+'</pre></div><div class="card"><a class="btn" href="/sales-workspace/'+str(r['opportunity_id'])+'">فتح ملف العميل</a> <a class="btn" href="/sales-copilot/'+str(r['opportunity_id'])+'">Sales Copilot</a></div><div class="card muted">لا يوجد رد تلقائي. أي رسالة جديدة تمر عبر مسودة وموافقة بشرية قبل الإرسال.</div>'
 return shell(b)
@router.get('/api/v7/inbound-replies')
def api(request:Request):
 auth(request);return {'replies':rows('SELECT id,opportunity_id,sender,subject,classification,confidence,status,received_at FROM inbound_replies ORDER BY received_at DESC,id DESC')}
