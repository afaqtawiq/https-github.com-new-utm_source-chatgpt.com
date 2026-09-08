import html,urllib.parse
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import get_session,rows,one,execute,log,utcnow
from app.discovery import fetch_public

router=APIRouter()
STYLE='''<style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}*{box-sizing:border-box}.wrap{max-width:1250px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}.top{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}.nav{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.nav a,.btn{display:inline-block;padding:10px 14px;border:0;border-radius:10px;background:#18384d;color:white;font-weight:700;text-decoration:none;cursor:pointer}.btn{background:#22c55e;color:#04130a}.muted{color:#9fb4c4}.good{color:#54e28b}.warn{color:#fbbf24}input{padding:12px;border:1px solid #36586e;border-radius:9px;margin:6px 0;background:#081925;color:white;width:100%}.formgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}table{width:100%;border-collapse:collapse}th,td{text-align:right;padding:11px;border-bottom:1px solid #28475d;vertical-align:top}.scroll{overflow:auto}.pill{padding:4px 8px;border-radius:999px;background:#18384d}</style>'''
def esc(x):return html.escape(str(x or ''))
def page(title,body):return '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title>'+STYLE+'<body><div class="wrap">'+body+'</div></body></html>'
def session(r):
    s=get_session(r.cookies.get('gla_session'))
    if not s:raise HTTPException(401)
    return s
def parse(raw):return {k:v[0] for k,v in urllib.parse.parse_qs(raw.decode()).items()}
def nav():return '<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/discovery">اكتشاف الفرص</a><a href="/accounts">العملاء</a><a href="/opportunities">الفرص</a><a href="/shipments">الشحنات</a><a href="/pipeline">Pipeline</a><a href="/activity">السجل</a></div>'
def head(s):return '<div class="top"><div><h1>اكتشاف الفرص</h1><div class="muted">Public-source buying intent engine</div></div><div class="good">● '+esc(s['email'])+'</div></div>'+nav()

@router.get('/discovery',response_class=HTMLResponse)
def discovery(r:Request):
    try:s=session(r)
    except HTTPException:return RedirectResponse('/login')
    watches=rows('SELECT * FROM source_watches ORDER BY id DESC')
    signals=rows('SELECT d.*,w.name source_name FROM discovered_signals d LEFT JOIN source_watches w ON w.id=d.source_watch_id ORDER BY d.score DESC,d.id DESC LIMIT 200')
    form='''<div class="card"><h2>إضافة مصدر عام للمراقبة</h2><form method="post" action="/discovery/sources"><div class="formgrid"><input name="name" placeholder="اسم المصدر" required><input name="url" placeholder="https://..." required></div><button class="btn">إضافة المصدر</button></form><p class="muted">استخدم فقط صفحات عامة مسموح بالوصول إليها. لا يتم تجاوز تسجيل الدخول أو الحماية.</p></div>'''
    wt=''.join(f'<tr><td>{x["id"]}</td><td>{esc(x["name"])}</td><td><a target="_blank" href="{esc(x["url"])}">فتح</a></td><td>{esc(x["last_status"])}</td><td>{esc(x["last_checked_at"])}</td><td><form method="post" action="/discovery/scan/{x["id"]}"><button class="btn">Scan</button></form></td></tr>' for x in watches)
    st=''
    for x in signals:
        action='<span class="good">تم التحويل</span>' if x['opportunity_id'] else f'<form method="post" action="/discovery/convert/{x["id"]}"><button class="btn">تحويل إلى فرصة</button></form>'
        st+=f'<tr><td>{x["score"]}</td><td>{esc(x["title"])}</td><td>{esc(x["source_name"])}</td><td>{esc(x["excerpt"])[:400]}</td><td>{esc(x["matched_terms"])}</td><td><a target="_blank" href="{esc(x["url"])}">المصدر</a></td><td>{action}</td></tr>'
    body=head(s)+form+'<div class="card"><h2>المصادر</h2><div class="scroll"><table><tr><th>#</th><th>المصدر</th><th>الرابط</th><th>الحالة</th><th>آخر فحص</th><th></th></tr>'+wt+'</table></div></div><div class="card"><h2>الإشارات المكتشفة</h2><div class="scroll"><table><tr><th>Score</th><th>العنوان</th><th>المصدر</th><th>المقتطف</th><th>سبب التقييم</th><th>الرابط</th><th></th></tr>'+st+'</table></div></div>'
    return HTMLResponse(page('اكتشاف الفرص',body),headers={'Cache-Control':'no-store'})

@router.post('/discovery/sources')
async def add_source(r:Request):
    try:s=session(r)
    except HTTPException:return RedirectResponse('/login')
    d=parse(await r.body()); name=d.get('name','').strip(); url=d.get('url','').strip()
    if not name or not url:return HTMLResponse(page('خطأ','<div class="card">الاسم والرابط مطلوبان.</div>'),400)
    try:
        iid=execute('INSERT INTO source_watches(name,url,source_type,enabled,created_at) VALUES(?,?,?,?,?)',(name,url,'web',1,utcnow())); log(s['user_id'],'create','source_watch',iid,name)
    except Exception:
        return HTMLResponse(page('خطأ','<div class="card">المصدر موجود مسبقًا أو الرابط غير صالح. <a class="btn" href="/discovery">عودة</a></div>'),400)
    return RedirectResponse('/discovery',303)

@router.post('/discovery/scan/{watch_id}')
def scan_source(watch_id:int,r:Request):
    try:s=session(r)
    except HTTPException:return RedirectResponse('/login')
    w=one('SELECT * FROM source_watches WHERE id=?',(watch_id,))
    if not w:return HTMLResponse(page('غير موجود','<div class="card">المصدر غير موجود.</div>'),404)
    try:
        result=fetch_public(w['url']); now=utcnow(); execute('UPDATE source_watches SET last_status=?,last_checked_at=? WHERE id=?',('ok',now,watch_id))
        company=(result['title'] or w['name'])[:180]
        try:
            sid=execute('INSERT INTO discovered_signals(source_watch_id,title,url,company_name,excerpt,score,matched_terms,status,discovered_at) VALUES(?,?,?,?,?,?,?,?,?)',(watch_id,result['title'],result['url'],company,result['excerpt'],result['score'],', '.join(result['matched_terms']),'new',now)); log(s['user_id'],'scan','source_watch',watch_id,f'Found signal score {result["score"]}')
        except Exception:
            execute('UPDATE discovered_signals SET title=?,excerpt=?,score=?,matched_terms=?,discovered_at=? WHERE url=?',(result['title'],result['excerpt'],result['score'],', '.join(result['matched_terms']),now,result['url']))
    except Exception as e:
        execute('UPDATE source_watches SET last_status=?,last_checked_at=? WHERE id=?',(str(e)[:160],utcnow(),watch_id)); log(s['user_id'],'scan_error','source_watch',watch_id,str(e)[:160])
    return RedirectResponse('/discovery',303)

@router.post('/discovery/convert/{signal_id}')
def convert_signal(signal_id:int,r:Request):
    try:s=session(r)
    except HTTPException:return RedirectResponse('/login')
    sig=one('SELECT * FROM discovered_signals WHERE id=?',(signal_id,))
    if not sig:return HTMLResponse(page('غير موجود','<div class="card">الإشارة غير موجودة.</div>'),404)
    if sig.get('opportunity_id'):return RedirectResponse('/opportunities',303)
    now=utcnow(); stage='qualified' if sig['score']>=70 else ('research' if sig['score']>=40 else 'new')
    oid=execute('INSERT INTO opportunities(company_name,source_url,signal,score,stage,estimated_value,currency,owner,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(sig['company_name'] or sig['title'],sig['url'],sig['excerpt'],sig['score'],stage,0,'SAR',s['email'],now,now))
    execute('UPDATE discovered_signals SET status=?,opportunity_id=? WHERE id=?',('converted',oid,signal_id)); log(s['user_id'],'convert','discovered_signal',signal_id,f'Opportunity {oid}')
    return RedirectResponse('/opportunities',303)

@router.get('/api/v7/discovery/signals')
def api_signals(r:Request):session(r);return rows('SELECT * FROM discovered_signals ORDER BY score DESC,id DESC LIMIT 200')
