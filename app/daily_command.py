import datetime
import html
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.intelligence import analyze
from app.sales_copilot import playbook
from app.storage import db, execute, get_session, log, one, rows, utcnow

router = APIRouter()


def ensure_schema():
    with db() as connection:
        connection.execute('''CREATE TABLE IF NOT EXISTS daily_sales_queue(
            id BIGSERIAL PRIMARY KEY,
            queue_date DATE NOT NULL,
            opportunity_id BIGINT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
            rank_no INTEGER NOT NULL,
            reason TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_by BIGINT,
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE(queue_date, opportunity_id)
        )''')


ensure_schema()


def esc(value):
    return html.escape(str(value or ''))


def auth(request):
    session = get_session(request.cookies.get('gla_session'))
    if not session:
        return None
    if session.get('role') not in ('admin', 'sales', 'transport'):
        raise HTTPException(403, 'Sales, transport or admin role required')
    return session


def shell(body):
    return HTMLResponse('''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مركز العمل اليومي</title><style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}.w{max-width:1450px;margin:auto;padding:24px}.hero,.card,.k{background:#102536;border:1px solid #28475d;border-radius:16px;padding:18px;margin:12px 0}.hero{background:linear-gradient(135deg,#12344a,#0b1d2b)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.k b{font-size:26px;display:block;margin-top:8px}.btn{display:inline-block;padding:9px 12px;border:0;border-radius:9px;background:#22c55e;color:#04130a;text-decoration:none;font-weight:bold;cursor:pointer}.secondary{background:#18384d;color:white}.warn{color:#fde68a}.good{color:#86efac}.muted{color:#9fb4c4}.scroll{overflow:auto}table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #28475d;text-align:right;vertical-align:top}.nav{display:flex;gap:10px;flex-wrap:wrap}.nav a{color:white}</style><body><div class="w">'''+body+'</div></body></html>')


def nav():
    return '<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/daily-command">مركز العمل اليومي</a><a href="/discovery">الاكتشاف</a><a href="/sales-center">المبيعات</a><a href="/outbound">الرسائل</a><a href="/quote-workflow">العروض</a><a href="/operations">العمليات</a><a href="/drivers">السائقون</a><a href="/approvals">الموافقات</a></div>'


def account_score(account):
    text = str(account.get('notes') or '')
    match = re.search(r'درجة التوافق:\s*(\d+)', text)
    if match:
        return max(0, min(100, int(match.group(1))))
    status = str(account.get('status') or '').lower()
    return 85 if status in ('مهتم', 'interested') else 80 if status in ('عرض سعر', 'proposal') else 70 if status in ('تم التواصل', 'contacted') else 55


def prepare_sales_assets(opportunity_id, user_id):
    opportunity = one('SELECT * FROM opportunities WHERE id=?', (opportunity_id,))
    if not opportunity:
        raise HTTPException(404, 'Opportunity not found')
    result = analyze(opportunity)
    guide = playbook(opportunity, result)
    now = utcnow()
    services = ', '.join(result['services'])
    execute('''INSERT INTO opportunity_intelligence(opportunity_id,priority,intent,services,evidence,next_action,proposal_draft,follow_up_status,generated_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET priority=EXCLUDED.priority,intent=EXCLUDED.intent,services=EXCLUDED.services,evidence=EXCLUDED.evidence,next_action=EXCLUDED.next_action,proposal_draft=EXCLUDED.proposal_draft,follow_up_status=EXCLUDED.follow_up_status,updated_at=EXCLUDED.updated_at''', (opportunity_id,result['priority'],result['intent'],services,result['evidence'],guide['follow'],guide['proposal'],'sales_ready_draft',now,now))
    message = one("SELECT id FROM outbound_messages WHERE opportunity_id=? AND status IN ('draft','pending_approval','approved','sent') ORDER BY id DESC LIMIT 1", (opportunity_id,))
    if not message:
        contact = one('SELECT email FROM sales_contacts WHERE opportunity_id=? AND verified=1 AND email IS NOT NULL ORDER BY id DESC LIMIT 1', (opportunity_id,))
        body = 'السادة/ '+opportunity['company_name']+'\n\nتحية طيبة،\nنود من آفاق طويق مناقشة احتياجكم المرتبط بـ '+(services or 'الخدمات اللوجستية')+'.\nيسعدنا دراسة نطاق العمل وتقديم الحل التشغيلي المناسب بعد التحقق من المتطلبات.\n\nمع التحية،\nآفاق طويق'
        message_id = execute('INSERT INTO outbound_messages(opportunity_id,channel,recipient,subject,body,proposal_text,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)', (opportunity_id,'email',(contact or {}).get('email'),'عرض خدمات لوجستية — آفاق طويق',body,guide['proposal'],'draft',user_id,now,now))
    else:
        message_id = message['id']
    execute("UPDATE daily_sales_queue SET status='prepared' WHERE queue_date=CURRENT_DATE AND opportunity_id=?", (opportunity_id,))
    log(user_id, 'daily_sales_prepare', 'opportunity', opportunity_id, 'Sales intelligence and outbound draft prepared; no external send')
    return message_id


@router.get('/daily-command')
def home(request: Request):
    session = auth(request)
    if not session:
        return RedirectResponse('/login', 303)
    queue = rows('''SELECT q.*,o.company_name,o.score,o.stage,i.priority,i.services,m.id message_id,m.status message_status,
        (SELECT MIN(f.due_at) FROM sales_followups f WHERE f.opportunity_id=o.id AND f.status='open') next_followup
        FROM daily_sales_queue q JOIN opportunities o ON o.id=q.opportunity_id
        LEFT JOIN opportunity_intelligence i ON i.opportunity_id=o.id
        LEFT JOIN LATERAL (SELECT id,status FROM outbound_messages x WHERE x.opportunity_id=o.id ORDER BY x.id DESC LIMIT 1) m ON TRUE
        WHERE q.queue_date=CURRENT_DATE ORDER BY q.rank_no''')
    overdue = one("SELECT COUNT(*) n FROM sales_followups WHERE status='open' AND due_at<=NOW()")['n']
    pending = one("SELECT COUNT(*) n FROM approvals WHERE status='pending'")['n']
    drafts = one("SELECT COUNT(*) n FROM outbound_messages WHERE status='draft'")['n']
    active_shipments = one("SELECT COUNT(*) n FROM shipments WHERE status NOT IN ('delivered','closed')")['n']
    unassigned = rows("""SELECT s.id,s.reference,s.origin,s.destination,s.service_type
        FROM shipments s LEFT JOIN shipment_operations x ON x.shipment_id=s.id
        WHERE s.status NOT IN ('delivered','closed') AND COALESCE(x.driver_name,'')='' ORDER BY s.id DESC LIMIT 20""")
    candidates = one("SELECT COUNT(*) n FROM drivers WHERE availability='متاح' AND offer_consent=1")['n']
    qrows = ''.join('<tr><td>'+str(x['rank_no'])+'</td><td><a href="/sales-workspace/'+str(x['opportunity_id'])+'" style="color:white"><b>'+esc(x['company_name'])+'</b></a><br><span class="muted">'+esc(x['reason'])+'</span></td><td>'+str(x['score'])+'</td><td>'+esc(x.get('priority') or 'غير مجهز')+'</td><td>'+esc(x.get('services') or '—')+'</td><td>'+esc(x.get('message_status') or 'لا توجد')+'</td><td>'+esc(x.get('next_followup') or '—')+'</td><td>'+('<form method="post" action="/daily-command/'+str(x['opportunity_id'])+'/prepare"><button class="btn">تجهيز البيع والمسودة</button></form>' if not x.get('message_id') else '<a class="btn" href="/outbound/'+str(x['message_id'])+'">فتح المسودة</a>')+' <a class="btn secondary" href="/quotes/new/'+str(x['opportunity_id'])+'">عرض سعر</a></td></tr>' for x in queue) or '<tr><td colspan="8" class="muted">اضغط «إنشاء قائمة اليوم» لاختيار أفضل 10 فرص.</td></tr>'
    srows = ''.join('<tr><td>'+esc(x['reference'])+'</td><td>'+esc(x['service_type'])+'</td><td>'+esc(x['origin'])+' ← '+esc(x['destination'])+'</td><td><a class="btn" href="/daily-command/shipment/'+str(x['id'])+'/drivers">ترشيح السائقين</a></td></tr>' for x in unassigned) or '<tr><td colspan="4" class="good">لا توجد شحنات نشطة بلا سائق.</td></tr>'
    body = nav()+'<div class="hero"><h1>مركز العمل اليومي — آفاق طويق</h1><p>قائمة واحدة تنقل العمل من اكتشاف العميل إلى العرض والتشغيل. الإنشاء الداخلي آلي، لكن الموافقة والإرسال الخارجي يظلان بقرار بشري.</p><form method="post" action="/daily-command/build"><button class="btn">إنشاء قائمة اليوم من أفضل 10 فرص</button></form></div>'
    body += '<div class="grid"><div class="k">فرص اليوم<b>'+str(len(queue))+'/10</b></div><div class="k">مسودات للمراجعة<b>'+str(drafts)+'</b></div><div class="k">متابعات مستحقة<b>'+str(overdue)+'</b></div><div class="k">اعتمادات معلقة<b>'+str(pending)+'</b></div><div class="k">شحنات نشطة<b>'+str(active_shipments)+'</b></div><div class="k">سائقون متاحون وموافقون<b>'+str(candidates)+'</b></div></div>'
    body += '<div class="card scroll"><h2>أفضل 10 فرص اليوم</h2><table><tr><th>#</th><th>العميل</th><th>Score</th><th>الأولوية</th><th>الخدمة</th><th>الرسالة</th><th>المتابعة</th><th>الإجراء التالي</th></tr>'+qrows+'</table></div>'
    body += '<div class="card scroll"><h2>شحنات تحتاج سائقًا</h2><table><tr><th>المرجع</th><th>الخدمة</th><th>المسار</th><th>الإجراء</th></tr>'+srows+'</table></div><div class="card warn">إرسال البريد يحتاج اعتمادًا صريحًا وMFA. إرسال عروض السائقين عبر واتساب غير مفعّل حتى اكتمال ربط WhatsApp Business API؛ الترشيح الحالي داخلي فقط.</div>'
    return shell(body)


@router.post('/daily-command/build')
def build_queue(request: Request):
    session = auth(request)
    if not session:
        return RedirectResponse('/login', 303)
    now = utcnow()
    accounts = rows("""SELECT a.* FROM accounts a WHERE NOT EXISTS(SELECT 1 FROM opportunities o WHERE o.account_id=a.id)
        ORDER BY CASE a.status WHEN 'عرض سعر' THEN 1 WHEN 'مهتم' THEN 2 WHEN 'تم التواصل' THEN 3 ELSE 4 END,a.id LIMIT 30""")
    for account in accounts:
        score = account_score(account)
        signal = 'عميل محتمل من قاعدة العملاء. الموقع: '+str(account.get('country') or 'غير محدد')+'. القطاع: '+str(account.get('domain') or 'غير محدد')+'. '+str(account.get('notes') or '')
        execute('''INSERT INTO opportunities(account_id,company_name,source_url,signal,score,stage,estimated_value,currency,owner,created_at,updated_at)
            SELECT ?,?,NULL,?,?, 'new',0,'SAR',NULL,?,? WHERE NOT EXISTS(SELECT 1 FROM opportunities WHERE account_id=?)''', (account['id'],account['name'],signal,score,now,now,account['id']))
    top = rows("""SELECT o.id,o.company_name,o.score,o.stage FROM opportunities o
        WHERE o.stage NOT IN ('won','lost','test')
        ORDER BY o.score DESC,o.updated_at DESC,o.id DESC LIMIT 10""")
    with db() as connection:
        connection.execute('DELETE FROM daily_sales_queue WHERE queue_date=CURRENT_DATE')
        for rank, item in enumerate(top, 1):
            reason = 'Score '+str(item['score'])+'؛ المرحلة '+str(item['stage'])
            connection.execute('INSERT INTO daily_sales_queue(queue_date,opportunity_id,rank_no,reason,status,created_by,created_at) VALUES(CURRENT_DATE,%s,%s,%s,%s,%s,%s)', (item['id'],rank,reason,'open',session['user_id'],now))
    log(session['user_id'], 'build_daily_sales_queue', 'daily_sales_queue', None, 'Top '+str(len(top))+' opportunities selected; no external actions')
    return RedirectResponse('/daily-command', 303)


@router.post('/daily-command/{opportunity_id}/prepare')
def prepare(opportunity_id: int, request: Request):
    session = auth(request)
    if not session:
        return RedirectResponse('/login', 303)
    message_id = prepare_sales_assets(opportunity_id, session['user_id'])
    return RedirectResponse('/outbound/'+str(message_id), 303)


@router.get('/daily-command/shipment/{shipment_id}/drivers')
def recommend_drivers(shipment_id: int, request: Request):
    session = auth(request)
    if not session:
        return RedirectResponse('/login', 303)
    shipment = one('SELECT * FROM shipments WHERE id=?', (shipment_id,))
    if not shipment:
        raise HTTPException(404, 'Shipment not found')
    drivers = rows("SELECT * FROM drivers WHERE availability='متاح' AND offer_consent=1 ORDER BY driver_name")
    origin = str(shipment.get('origin') or '').lower()
    destination = str(shipment.get('destination') or '').lower()
    ranked = []
    for driver in drivers:
        haystack = ' '.join([str(driver.get('current_city') or ''),str(driver.get('preferred_routes') or ''),str(driver.get('vehicle_type') or '')]).lower()
        score = 50 + (25 if origin and origin in haystack else 0) + (20 if destination and destination in haystack else 0)
        ranked.append((score, driver))
    ranked.sort(key=lambda item: (-item[0], str(item[1].get('driver_name') or '')))
    table = ''.join('<tr><td>'+str(score)+'</td><td>'+esc(driver['driver_name'])+'</td><td>'+esc(driver['vehicle_type'])+'</td><td>'+esc(driver['current_city'])+'</td><td>'+esc(driver['preferred_routes'])+'</td><td>'+esc(driver['whatsapp_phone'])+'</td><td><a class="btn" href="/drivers/'+str(driver['id'])+'/edit">ملف السائق</a></td></tr>' for score,driver in ranked[:20]) or '<tr><td colspan="7">لا يوجد سائق متاح لديه موافقة استقبال عروض.</td></tr>'
    return shell(nav()+'<h1>السائقون المرشحون للشحنة '+esc(shipment['reference'])+'</h1><div class="card"><b>المسار:</b> '+esc(shipment.get('origin'))+' ← '+esc(shipment.get('destination'))+'<p class="muted">الترتيب داخلي بحسب تطابق المدينة والمسارات. تعيين السائق يتم من مركز العمليات، ولا تُرسل رسالة واتساب من هذه الصفحة.</p><a class="btn" href="/operations/'+str(shipment_id)+'">فتح الشحنة وتعيين السائق</a></div><div class="card scroll"><table><tr><th>الملاءمة</th><th>السائق</th><th>المركبة</th><th>المدينة</th><th>المسارات</th><th>واتساب</th><th></th></tr>'+table+'</table></div>')


@router.get('/api/v7/daily-command')
def api(request: Request):
    if not auth(request):
        raise HTTPException(401)
    return {
        'date': datetime.date.today().isoformat(),
        'queue': rows('SELECT q.*,o.company_name,o.score,o.stage FROM daily_sales_queue q JOIN opportunities o ON o.id=q.opportunity_id WHERE q.queue_date=CURRENT_DATE ORDER BY q.rank_no'),
        'policy': {'auto_prepare_internal': True, 'auto_send': False, 'human_approval_required': True},
    }
