import html
import urllib.parse
import datetime as dt
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.storage import execute, get_session, log, one, rows, utcnow

router = APIRouter()


def e(value):
    return html.escape(str(value or ""))


def parse(raw):
    return {key: value[0] for key, value in urllib.parse.parse_qs(raw.decode()).items()}


def auth(request):
    session = get_session(request.cookies.get("gla_session"))
    if not session:
        raise HTTPException(401)
    return session


def init_social_content():
    execute("""CREATE TABLE IF NOT EXISTS social_channels(
        id BIGSERIAL PRIMARY KEY, platform TEXT NOT NULL, account_name TEXT NOT NULL,
        profile_url TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'linked',
        created_by BIGINT, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
        UNIQUE(platform, profile_url))""")
    execute("""CREATE TABLE IF NOT EXISTS social_content(
        id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, platform TEXT NOT NULL,
        content_type TEXT NOT NULL DEFAULT 'post', body TEXT NOT NULL,
        media_url TEXT, scheduled_at TIMESTAMPTZ, status TEXT NOT NULL DEFAULT 'draft',
        approval_id BIGINT REFERENCES approvals(id) ON DELETE SET NULL,
        created_by BIGINT, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
        published_at TIMESTAMPTZ)""")
    now = utcnow()
    execute("UPDATE social_channels SET status='superseded' WHERE platform='TikTok' AND profile_url='https://www.tiktok.com/@afaqt79' AND created_by IS NULL")
    execute("""INSERT INTO social_channels(platform,account_name,profile_url,status,created_by,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(platform,profile_url) DO NOTHING""",
        ("YouTube","آفاق طويق — @afaqtaw","https://www.youtube.com/@afaqtaw","linked",None,now,now))
    execute("""INSERT INTO social_channels(platform,account_name,profile_url,status,created_by,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(platform,profile_url) DO NOTHING""",
        ("Instagram","آفاق طويق — @afaqwaiq","https://www.instagram.com/afaqwaiq/","linked",None,now,now))
    execute("""INSERT INTO social_channels(platform,account_name,profile_url,status,created_by,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(platform,profile_url) DO NOTHING""",
        ("TikTok","آفاق طويق — @afaqtawaiq6","https://www.tiktok.com/@afaqtawaiq6","saved",None,now,now))
    execute("""INSERT INTO social_channels(platform,account_name,profile_url,status,created_by,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(platform,profile_url) DO NOTHING""",
        ("LinkedIn","آفاق طويق — Afaq Tuwaiq","https://www.linkedin.com/in/%D8%A7%D9%81%D8%A7%D9%82-%D8%B7%D9%88%D9%8A%D9%82-afaqtawiq-8096bb434/","linked",None,now,now))


init_social_content()


STYLE = """<style>
:root{--gold:#e7b64b;--gold2:#ffd978;--line:rgba(148,184,205,.2);--muted:#a7bdcb}
*{box-sizing:border-box}body{margin:0;font-family:"Segoe UI",Tahoma,Arial,sans-serif;background:radial-gradient(circle at 90% 0,#173f56 0,transparent 32%),#07131f;color:#f4f8fb;line-height:1.65}.w{max-width:1400px;margin:auto;padding:26px}.nav{display:flex;gap:9px;overflow:auto;margin-bottom:18px}.nav a,.btn{display:inline-flex;align-items:center;justify-content:center;padding:10px 14px;border:0;border-radius:11px;background:#1a3d53;color:#fff;text-decoration:none;font-weight:750;cursor:pointer;white-space:nowrap}.btn{background:linear-gradient(135deg,var(--gold2),var(--gold));color:#152431}.hero,.card,.k{background:linear-gradient(145deg,rgba(18,45,64,.96),rgba(9,28,43,.98));border:1px solid var(--line);border-radius:20px;padding:21px;margin:14px 0;box-shadow:0 16px 45px rgba(0,0,0,.16)}.hero{border-color:rgba(231,182,75,.28)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:13px}.k b{display:block;font-size:28px;color:var(--gold2)}input,select,textarea{width:100%;padding:12px;border:1px solid #36586e;border-radius:10px;background:#081925;color:#fff;margin:5px 0}textarea{min-height:120px}.formgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse}th,td{padding:11px;text-align:right;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--gold2)}.muted{color:var(--muted)}.pill{display:inline-block;padding:4px 9px;border-radius:999px;background:#244b63}.actions{display:flex;gap:7px;flex-wrap:wrap}.danger{background:#753647;color:#fff}.ok{color:#64e39a}h1,h2{margin-top:0}@media(max-width:650px){.w{padding:15px}.card,.hero{padding:17px}.grid{grid-template-columns:1fr}}
</style>"""


def page(body):
    return '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مركز المحتوى</title>'+STYLE+'<body><div class="w">'+body+'</div></body></html>'


def safe_url(value):
    value = (value or "").strip()
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "رابط الحساب يجب أن يبدأ بـ https://")
    return value


@router.get("/content-center", response_class=HTMLResponse)
def content_center(request: Request):
    session = auth(request)
    channels = rows("SELECT * FROM social_channels WHERE status!='superseded' ORDER BY platform, id DESC")
    items = rows("""SELECT c.*,a.status approval_status FROM social_content c
        LEFT JOIN approvals a ON a.id=c.approval_id ORDER BY c.id DESC LIMIT 100""")
    draft_count = one("SELECT COUNT(*) n FROM social_content WHERE status='draft'")["n"]
    review_count = one("SELECT COUNT(*) n FROM social_content WHERE status='pending_approval'")["n"]
    approved_count = one("SELECT COUNT(*) n FROM social_content WHERE status='approved'")["n"]
    channel_cards = ''.join('<div class="k"><span class="pill">'+e(x['platform'])+'</span><b>'+e(x['account_name'])+'</b><a class="btn" target="_blank" rel="noopener" href="'+e(x['profile_url'])+'">فتح الحساب</a></div>' for x in channels)
    content_rows = ''
    for item in items:
        actions = '<a class="btn" href="/content-center/'+str(item['id'])+'">فتح</a>'
        content_rows += '<tr><td>'+str(item['id'])+'</td><td>'+e(item['title'])+'</td><td>'+e(item['platform'])+'</td><td><span class="pill">'+e(item['status'])+'</span></td><td>'+e(item.get('scheduled_at') or 'غير محدد')+'</td><td>'+actions+'</td></tr>'
    body = '<div class="nav"><a href="/dashboard">⌂ الرئيسية</a><a href="/content-center">مركز المحتوى</a><a href="/approvals">الموافقات</a>' + ('<a href="/settings/social">إعدادات النشر</a>' if session.get('role') == 'admin' else '') + '</div>'
    body += '<div class="hero"><h1>مركز صناعة ونشر المحتوى</h1><p class="muted">أنشئ المحتوى واحفظ حسابات المنصات وحدد موعد النشر. لن يتم أي نشر خارجي قبل موافقة الإدارة وربط واجهة المنصة.</p></div>'
    body += '<div class="grid"><div class="k">روابط الحسابات المحفوظة<b>'+str(len(channels))+'</b></div><div class="k">مسودات<b>'+str(draft_count)+'</b></div><div class="k">بانتظار الموافقة<b>'+str(review_count)+'</b></div><div class="k">جاهزة للمراجعة والجدولة<b>'+str(approved_count)+'</b></div></div>'
    body += '<div class="card"><h2>إضافة حساب تواصل اجتماعي</h2><form method="post" action="/social-channels"><div class="formgrid"><select name="platform"><option>Instagram</option><option>TikTok</option><option>Facebook</option><option>YouTube</option><option>Snapchat</option><option>LinkedIn</option><option>X</option></select><input name="account_name" placeholder="اسم الحساب" required><input name="profile_url" type="url" placeholder="https://..." required></div><button class="btn">حفظ رابط الحساب</button></form></div>'
    body += '<div class="grid">'+(channel_cards or '<div class="card muted">لم تتم إضافة روابط الحسابات بعد.</div>')+'</div>'
    body += '<div class="card"><h2>إنشاء مسودة محتوى</h2><form method="post" action="/content-center"><div class="formgrid"><input name="title" placeholder="عنوان داخلي للمحتوى" required><select name="platform"><option value="YouTube+TikTok">YouTube + TikTok — آفاق طويق</option><option>All</option><option>Instagram</option><option>TikTok</option><option>Facebook</option><option>YouTube</option><option>Snapchat</option><option>LinkedIn</option><option>X</option></select><select name="content_type"><option value="post">منشور</option><option value="reel">ريلز / فيديو قصير</option><option value="story">ستوري</option><option value="video">فيديو</option></select><label>موعد مقترح — بتوقيت الرياض<input name="scheduled_at" type="datetime-local"></label></div><textarea name="body" placeholder="اكتب نص المحتوى، الفكرة، الدعوة لاتخاذ إجراء والوسوم..." required></textarea><input name="media_url" type="url" placeholder="رابط الصورة أو الفيديو — اختياري"><button class="btn">حفظ المسودة</button></form></div>'
    body += '<div class="card scroll"><h2>تقويم ومسودات المحتوى</h2><table><tr><th>#</th><th>العنوان</th><th>المنصة</th><th>الحالة</th><th>موعد النشر</th><th></th></tr>'+(content_rows or '<tr><td colspan="6" class="muted">لا توجد مسودات بعد.</td></tr>')+'</table></div>'
    return HTMLResponse(page(body))


@router.post("/social-channels")
async def add_social_channel(request: Request):
    session = auth(request); data = parse(await request.body()); now = utcnow()
    url = safe_url(data.get("profile_url"))
    try:
        channel_id = execute("INSERT INTO social_channels(platform,account_name,profile_url,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (data.get("platform"),data.get("account_name"),url,"linked",session["user_id"],now,now))
    except Exception:
        raise HTTPException(409, "هذا الحساب مضاف مسبقًا")
    log(session["user_id"],"social_channel_added","social_channel",channel_id,data.get("platform"))
    return RedirectResponse("/content-center",303)


@router.post("/content-center")
async def create_content(request: Request):
    session = auth(request); data = parse(await request.body()); now = utcnow()
    scheduled = None
    if data.get('scheduled_at'):
        try:
            scheduled = dt.datetime.fromisoformat(data['scheduled_at'])
            if scheduled.tzinfo is None: scheduled = scheduled.replace(tzinfo=ZoneInfo('Asia/Riyadh'))
        except ValueError: raise HTTPException(400, 'موعد غير صحيح')
    content_id = execute("INSERT INTO social_content(title,platform,content_type,body,media_url,scheduled_at,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (data.get("title"),data.get("platform"),data.get("content_type"),data.get("body"),data.get("media_url") or None,scheduled,"draft",session["user_id"],now,now))
    log(session["user_id"],"social_content_created","social_content",content_id,data.get("title"))
    return RedirectResponse("/content-center/"+str(content_id),303)


@router.get("/content-center/{content_id}", response_class=HTMLResponse)
def content_detail(content_id: int, request: Request):
    session = auth(request)
    item = one("""SELECT c.*,a.status approval_status FROM social_content c LEFT JOIN approvals a ON a.id=c.approval_id WHERE c.id=?""",(content_id,))
    if not item: raise HTTPException(404)
    channel = one("SELECT * FROM social_channels WHERE platform=? ORDER BY id DESC LIMIT 1",(item['platform'],)) if item['platform'] != 'All' else None
    controls = ''
    if item['status'] == 'draft': controls = '<form method="post" action="/content-center/'+str(content_id)+'/request-approval"><button class="btn">إرسال إلى موافقة الإدارة</button></form>'
    elif item['status'] == 'pending_approval' and session.get('role') == 'admin': controls = '<form method="post" action="/content-center/'+str(content_id)+'/approve"><button class="btn">اعتماد المحتوى للنشر</button></form>'
    elif item['status'] == 'approved':
        open_link = '<a class="btn" target="_blank" rel="noopener" href="'+e(channel['profile_url'])+'">فتح '+e(item['platform'])+' للنشر</a>' if channel else '<span class="muted">أضف رابط حساب المنصة أولًا.</span>'
        controls = open_link+'<form method="post" action="/content-center/'+str(content_id)+'/mark-published"><button class="btn">تأكيد أنه تم النشر</button></form>'
        if session.get('role') == 'admin' and item['platform'] in ('YouTube', 'TikTok', 'YouTube+TikTok') and item['content_type'] in ('video', 'reel'):
            controls = '<a class="btn" href="/content-center/'+str(content_id)+'/schedule">مراجعة وجدولة النشر التلقائي</a>'
    body = '<div class="nav"><a href="/content-center">← مركز المحتوى</a><a href="/dashboard">الرئيسية</a></div><div class="hero"><span class="pill">'+e(item['platform'])+'</span><h1>'+e(item['title'])+'</h1><p class="muted">'+e(item['content_type'])+' · '+e(item['status'])+' · '+e(item.get('scheduled_at') or 'بلا موعد')+'</p></div><div class="card"><h2>النص الجاهز</h2><div style="white-space:pre-wrap">'+e(item['body'])+'</div></div>'
    if item.get('media_url'): body += '<div class="card"><a class="btn" target="_blank" rel="noopener" href="'+e(item['media_url'])+'">فتح ملف الوسائط</a></div>'
    body += '<div class="card actions">'+controls+'</div>'
    from app.social_publishing import publication_panel
    body += publication_panel(content_id, session)
    return HTMLResponse(page(body))


@router.post("/content-center/{content_id}/request-approval")
def request_content_approval(content_id: int, request: Request):
    session = auth(request); item = one("SELECT * FROM social_content WHERE id=?",(content_id,))
    if not item or item['status'] != 'draft': raise HTTPException(409)
    now=utcnow(); approval_id=execute("INSERT INTO approvals(kind,entity_type,entity_id,status,requested_by,notes,created_at) VALUES(?,?,?,?,?,?,?)",("social_publish","social_content",content_id,"pending",session["user_id"],"مراجعة واعتماد محتوى: "+item['title'],now))
    execute("UPDATE social_content SET status='pending_approval',approval_id=?,updated_at=? WHERE id=?",(approval_id,now,content_id)); log(session["user_id"],"social_content_approval_requested","social_content",content_id,item['title'])
    return RedirectResponse("/content-center/"+str(content_id),303)


@router.post("/content-center/{content_id}/approve")
def approve_content(content_id: int, request: Request):
    session=auth(request)
    if session.get('role') != 'admin': raise HTTPException(403)
    item=one("SELECT * FROM social_content WHERE id=?",(content_id,))
    if not item or item['status'] != 'pending_approval': raise HTTPException(409)
    now=utcnow(); execute("UPDATE approvals SET status='approved',decided_by=?,decided_at=? WHERE id=?",(session['user_id'],now,item['approval_id'])); execute("UPDATE social_content SET status='approved',updated_at=? WHERE id=?",(now,content_id)); log(session['user_id'],"social_content_approved","social_content",content_id,item['title'])
    return RedirectResponse("/content-center/"+str(content_id),303)


@router.post("/content-center/{content_id}/mark-published")
def mark_published(content_id: int, request: Request):
    session=auth(request); item=one("SELECT * FROM social_content WHERE id=?",(content_id,))
    if not item or item['status'] != 'approved': raise HTTPException(409)
    if item['platform'] in ('YouTube', 'TikTok', 'YouTube+TikTok') and item['content_type'] in ('video', 'reel'):
        raise HTTPException(409, 'جدول الفيديو ثم حدّث نتيجة النشر من Zernio لإثبات نشره.')
    now=utcnow(); execute("UPDATE social_content SET status='published',published_at=?,updated_at=? WHERE id=?",(now,now,content_id)); log(session['user_id'],"social_content_published","social_content",content_id,item['title'])
    return RedirectResponse("/content-center/"+str(content_id),303)
