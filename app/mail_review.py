"""Source-backed, manual-only mailbox review work. Never sends or qualifies leads.

A reviewed association is deliberately separate from the exact-thread link used
by official_sales to authorize reply drafts. Delivery notices are provider claims,
not proof of delivery, a customer reply, or authorization to retry.
"""
import datetime as dt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.storage import db, rows, one, utcnow
from app.social_content import e, page
from app.social_publishing import hidden_csrf

router = APIRouter()
LIMIT = 200
LABELS = {
    'delivery_failed': 'إشعار فشل تسليم من خادم البريد',
    'delivery_delayed': 'إشعار تأخر تسليم من خادم البريد',
    'delivery_notice': 'إشعار بريد يحتاج تحققًا',
    'linked_reply': 'رد مرتبط بمرجع المحادثة',
    'unlinked_review': 'وارد يحتاج مراجعة الربط',
    'waiting_reply': 'مراجعة انتظار الرد بعد قبول مزود البريد',
    'stopped': 'طلب إيقاف التواصل؛ لا ترسل متابعة',
}


def init():
    with db() as c:
        for name in ('body_format', 'notice_kind', 'notice_recipient', 'notice_message_id'):
            c.execute('ALTER TABLE spacemail_inbox ADD COLUMN IF NOT EXISTS '+name+' TEXT')
        c.execute('ALTER TABLE spacemail_inbox ADD COLUMN IF NOT EXISTS content_version INTEGER NOT NULL DEFAULT 0')
        c.execute('''CREATE TABLE IF NOT EXISTS official_mail_reviews(
            id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id),
            inbox_id BIGINT UNIQUE REFERENCES spacemail_inbox(id),
            outbound_id BIGINT UNIQUE REFERENCES outbound_messages(id),
            related_outbound_id BIGINT REFERENCES outbound_messages(id),
            status TEXT NOT NULL CHECK(status IN ('open','done')),
            due_at TIMESTAMPTZ, notes TEXT NOT NULL DEFAULT '',
            updated_by BIGINT NOT NULL REFERENCES users(id), updated_at TIMESTAMPTZ NOT NULL,
            CHECK((inbox_id IS NOT NULL) <> (outbound_id IS NOT NULL)))''')


def allowed(s):
    from app.fine_permissions import has_permission
    return s.get('role') == 'admin' and has_permission(s, 'manage_gmail')


def review_items(uid, include_done=False):
    """Bounded read model. GET never materializes tasks or changes CRM state."""
    inbox = rows('''SELECT i.id,i.subject,i.sender,i.sender_address,i.imported_at,i.body_format,
        i.notice_kind,i.notice_recipient,i.notice_message_id,
        l.status link_status,l.matched_outbound_id,l.prospect_id,l.opportunity_id,
        p.company_name,p.status prospect_status,
        r.status review_status,r.due_at,r.notes,r.related_outbound_id
        FROM spacemail_inbox i
        LEFT JOIN official_mail_links l ON l.inbox_id=i.id AND l.user_id=i.user_id
        LEFT JOIN sales_prospects p ON p.id=l.prospect_id AND p.mail_user_id=i.user_id
        LEFT JOIN official_mail_reviews r ON r.inbox_id=i.id AND r.user_id=i.user_id
        WHERE i.user_id=? AND i.duplicate_of IS NULL
          AND COALESCE(i.sender_address,'')<>'afaq@shodai.cc'
          AND (? OR COALESCE(r.status,'open')<>'done')
        ORDER BY COALESCE(r.due_at,i.imported_at),i.id LIMIT ?''', (uid,include_done,LIMIT+1))
    sent = rows('''SELECT m.id,m.prospect_id,m.sent_at,m.recipient,p.company_name,p.status prospect_status,
        r.status review_status,r.due_at,r.notes
        FROM sales_prospects p JOIN outbound_messages m ON m.prospect_id=p.id AND m.mail_user_id=p.mail_user_id
        LEFT JOIN official_mail_reviews r ON r.outbound_id=m.id AND r.user_id=m.mail_user_id
        WHERE p.mail_user_id=? AND p.status='contacted' AND m.purpose='intro_prospect' AND m.status='sent'
          AND (? OR COALESCE(r.status,'open')<>'done')
        ORDER BY COALESCE(r.due_at,m.sent_at+INTERVAL '3 days'),m.id LIMIT ?''', (uid,include_done,LIMIT+1))
    truncated = len(inbox)>LIMIT or len(sent)>LIMIT
    data = []
    for item in inbox[:LIMIT]:
        kind = item.get('notice_kind') or 'none'
        if kind == 'none':
            kind = ('stopped' if item.get('prospect_status')=='stopped' else
                    'linked_reply' if item.get('link_status')=='linked' else 'unlinked_review')
        related = item.get('matched_outbound_id') if item.get('link_status')=='linked' else None
        basis = 'exact_thread' if related else None
        if kind.startswith('delivery_'):
            related, basis = None, None
        # DSN linkage is a source reference ONLY and never authorizes a reply.
        if kind.startswith('delivery_') and item.get('notice_message_id') and item.get('notice_recipient'):
            matches = rows('''SELECT m.id FROM outbound_messages m JOIN approvals a ON a.id=m.approval_id
                AND a.kind='external_send' AND a.entity_type='outbound_message' AND a.entity_id=m.id AND a.status='approved'
                WHERE m.mail_user_id=? AND m.provider='spacemail' AND m.status='sent'
                  AND m.provider_message_id=? AND LOWER(m.recipient)=?''',
                (uid,item['notice_message_id'],item['notice_recipient']))
            if len(matches)==1:
                related, basis = matches[0]['id'], 'delivery_notice_reference'
        if item.get('related_outbound_id'):
            related, basis = item['related_outbound_id'], 'manual_review_reference'
        data.append({**item,'source_kind':'inbox','kind':kind,'source_url':'/official-inbox/'+str(item['id']),
                     'related_outbound_id':related,'association_basis':basis,
                     'due_at':item.get('due_at') or item['imported_at'],
                     'review_status':item.get('review_status') or 'open'})
    for item in sent[:LIMIT]:
        data.append({**item,'source_kind':'outbound','kind':'waiting_reply',
                     'source_url':'/outbound/'+str(item['id']), 'related_outbound_id':None,
                     'association_basis':None,'due_at':item.get('due_at') or item['sent_at']+dt.timedelta(days=3),
                     'review_status':item.get('review_status') or 'open'})
    data.sort(key=lambda x:(x['due_at'],x['source_kind'],x['id']))
    return data,truncated


def summary(s, limit=20):
    if not allowed(s):
        return ''
    data, truncated = review_items(s['user_id'])
    now = utcnow()
    due = sum(x['due_at']<=now for x in data)
    body = '<div class="card"><h2>مراجعات سارة من البريد الفعلي</h2><p>مستحقة الآن: '+str(due)+' · إجمالي ظاهر: '+str(len(data))+'</p>'
    body += '<p>هذه مهام مراجعة داخلية. لا توجد متابعة مرسلة تلقائيًا. قبول SMTP لا يثبت الوصول؛ إشعارات الخادم لا تُعد رد عميل. إغلاق المراجعة لا يؤهّل العميل ولا يؤكد التسليم.</p>'
    if truncated:
        body += '<p role="alert">القائمة محدودة بأقدم 200 وارد مفتوح و200 تعريف ينتظر الرد؛ قد توجد عناصر إضافية.</p>'
    for item in data[:limit]:
        title = item.get('company_name') or item.get('subject') or item.get('sender') or item.get('recipient')
        body += '<p><a href="/sales-review/'+item['source_kind']+'/'+str(item['id'])+'">'+e(LABELS[item['kind']])+': '+e(title)+'</a> · موعد المراجعة '+e(item['due_at'])+' · <a href="'+item['source_url']+'">المصدر الأصلي</a>'
        if item.get('related_outbound_id'):
            label = 'مرجع مراجعة يدوي فقط' if item['association_basis']=='manual_review_reference' else 'مرجع إشعار الخادم' if item['association_basis']=='delivery_notice_reference' else 'مرجع محادثة مطابق'
            body += ' · <a href="/outbound/'+str(item['related_outbound_id'])+'">'+label+' #'+str(item['related_outbound_id'])+'</a>'
        body += '</p>'
    if not data:
        body += '<p>لا توجد مراجعات بريد مفتوحة ضمن نطاق هذه القائمة؛ هذا لا يثبت اكتمال المبيعات.</p>'
    return body+'<a href="/sales-review">كل المراجعات والقرارات اليدوية</a></div>'


def source(uid, kind, sid):
    if kind == 'inbox':
        row = one('SELECT id,subject,sender,body,duplicate_of FROM spacemail_inbox WHERE id=? AND user_id=?',(sid,uid))
    elif kind == 'outbound':
        row = one("SELECT id,subject,recipient,body FROM outbound_messages WHERE id=? AND mail_user_id=? AND prospect_id IS NOT NULL AND purpose='intro_prospect' AND status='sent'",(sid,uid))
    else:
        raise HTTPException(404)
    if not row:
        raise HTTPException(404)
    if row.get('duplicate_of'):
        raise HTTPException(409,'Review the original message, not the duplicate')
    return row


@router.get('/sales-review',response_class=HTMLResponse)
def dashboard(request:Request):
    from app.spacemail import admin
    s=admin(request)
    body='<h1>مراجعات سارة اليدوية</h1><a href="/sales-today">مهام اليوم</a> · <a href="/official-inbox">الوارد الرسمي</a>'+summary(s,400)
    closed=rows('''SELECT inbox_id,outbound_id,notes,updated_at FROM official_mail_reviews
        WHERE user_id=? AND status='done' ORDER BY updated_at DESC LIMIT 50''',(s['user_id'],))
    body+='<div class="card"><h2>آخر المراجعات المغلقة</h2>'
    for row in closed:
        kind='inbox' if row['inbox_id'] else 'outbound';sid=row['inbox_id'] or row['outbound_id']
        body+='<p><a href="/sales-review/'+kind+'/'+str(sid)+'">مراجعة #'+str(sid)+'</a> · '+e(row['notes'])+' · '+e(row['updated_at'])+'</p>'
    return HTMLResponse(page(body+'</div>'),headers={'Cache-Control':'no-store'})


@router.get('/sales-review/{kind}/{sid}',response_class=HTMLResponse)
def detail(kind:str,sid:int,request:Request):
    from app.spacemail import admin
    s=admin(request);item=source(s['user_id'],kind,sid)
    review=one('SELECT * FROM official_mail_reviews WHERE user_id=? AND '+kind+'_id=?',(s['user_id'],sid)) or {}
    body='<h1>مراجعة يدوية من مصدر محفوظ</h1><a href="/sales-review">كل المراجعات</a> · <a href="'+('/official-inbox/' if kind=='inbox' else '/outbound/')+str(sid)+'">المصدر الأصلي</a>'
    body+='<h2>'+e(item.get('subject'))+'</h2><p>'+e(item.get('sender') or item.get('recipient'))+'</p><pre style="white-space:pre-wrap">'+e(item.get('body'))+'</pre>'
    body+='<p>حفظ مراجعة داخلية فقط، دون إرسال أو إعادة محاولة أو تغيير حالة العميل أو إثبات التسليم. الربط اليدوي هنا مرجع للمراجعة ولا يفتح صلاحية الرد. الرد يحتاج ربط المحادثة الآمن ثم اعتماد النص والمستلم.</p>'
    body+='<form method="post">'+hidden_csrf(s)+'<label>القرار<select name="status"><option value="open">مفتوحة</option><option value="done" '+('selected' if review.get('status')=='done' else '')+'>راجعت المصدر وأغلقت المهمة</option></select></label>'
    due=review.get('due_at');due_text=due.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M') if due else ''
    body+='<label>موعد مراجعة داخلي (UTC، اختياري)<input name="due_at" type="datetime-local" value="'+e(due_text)+'"></label><label>ما الذي راجعته أو الخطوة التالية؟<textarea name="notes" maxlength="2000" required>'+e(review.get('notes'))+'</textarea></label>'
    if kind=='inbox':
        body+='<label>رسالة صادرة كمرجع مراجعة يدوي فقط (اختياري)<select name="related_outbound_id"><option value="">دون مرجع يدوي</option>'
        candidates=rows("SELECT m.id,m.recipient,m.subject FROM outbound_messages m JOIN approvals a ON a.id=m.approval_id AND a.entity_type='outbound_message' AND a.entity_id=m.id AND a.kind='external_send' AND a.status='approved' WHERE m.mail_user_id=? AND m.provider='spacemail' AND m.status='sent' ORDER BY m.id DESC LIMIT 200",(s['user_id'],))
        # Keep an older saved selection visible when it falls outside the newest
        # 200 choices; editing a note must not silently discard its reference.
        if review.get('related_outbound_id') and not any(x['id']==review['related_outbound_id'] for x in candidates):
            current=one("SELECT m.id,m.recipient,m.subject FROM outbound_messages m JOIN approvals a ON a.id=m.approval_id AND a.entity_type='outbound_message' AND a.entity_id=m.id AND a.kind='external_send' AND a.status='approved' WHERE m.id=? AND m.mail_user_id=? AND m.provider='spacemail' AND m.status='sent'",(review['related_outbound_id'],s['user_id']))
            if current:
                candidates.append(current)
        for candidate in candidates:
            selected=' selected' if candidate['id']==review.get('related_outbound_id') else ''
            body+='<option value="'+str(candidate['id'])+'"'+selected+'>#'+str(candidate['id'])+' '+e(candidate['recipient'])+' · '+e(candidate['subject'])+'</option>'
        body+='</select></label>'
    body+='<button>حفظ المراجعة الداخلية فقط</button></form>'
    return HTMLResponse(page(body),headers={'Cache-Control':'no-store'})


@router.post('/sales-review/{kind}/{sid}')
async def save(kind:str,sid:int,request:Request):
    from app.spacemail import admin,form
    s=admin(request);data=await form(request,s)
    if kind not in ('inbox','outbound'):
        raise HTTPException(404)
    notes=str(data.get('notes') or '').strip();status=data.get('status')
    if not notes or len(notes)>2000 or status not in ('open','done'):
        raise HTTPException(400,'A review decision and note are required')
    due=None
    if data.get('due_at'):
        try:
            due=dt.datetime.fromisoformat(data['due_at'])
            due=due.replace(tzinfo=dt.timezone.utc) if due.tzinfo is None else due.astimezone(dt.timezone.utc)
        except (ValueError,OverflowError):
            raise HTTPException(400,'Invalid UTC review date') from None
    related=None
    if data.get('related_outbound_id'):
        try:related=int(data['related_outbound_id'])
        except (ValueError,TypeError):raise HTTPException(400) from None
        if kind!='inbox':raise HTTPException(400)
    with db() as c:
        source(s['user_id'],kind,sid)
        if related and not c.execute("SELECT m.id FROM outbound_messages m JOIN approvals a ON a.id=m.approval_id AND a.entity_type='outbound_message' AND a.entity_id=m.id AND a.kind='external_send' AND a.status='approved' WHERE m.id=%s AND m.mail_user_id=%s AND m.status='sent' AND m.provider='spacemail'",(related,s['user_id'])).fetchone():
            raise HTTPException(409,'Owned approved official sent message required')
        row=c.execute('''INSERT INTO official_mail_reviews(user_id,inbox_id,outbound_id,related_outbound_id,status,due_at,notes,updated_by,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT('''+kind+'''_id) DO UPDATE SET
            related_outbound_id=excluded.related_outbound_id,status=excluded.status,due_at=excluded.due_at,
            notes=excluded.notes,updated_by=excluded.updated_by,updated_at=excluded.updated_at
            WHERE official_mail_reviews.user_id=excluded.user_id RETURNING id''',
            (s['user_id'],sid if kind=='inbox' else None,sid if kind=='outbound' else None,related,status,due,notes,s['user_id'],utcnow())).fetchone()
        if not row:raise HTTPException(409)
        c.execute('INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at) VALUES(%s,%s,%s,%s,%s,%s)',
                  (s['user_id'],'review_official_mail','official_mail_review',row['id'],'Internal review '+status+'; no send or CRM stage change; source '+kind+' #'+str(sid),utcnow()))
    return RedirectResponse('/sales-review/'+kind+'/'+str(sid),303)


@router.get('/api/v7/sales-review')
def api(request:Request):
    from app.spacemail import admin
    s=admin(request);data,truncated=review_items(s['user_id'])
    return {'automatic_followup':False,'delivery_confirmed_by_smtp':False,'items':data,'truncated':truncated}
