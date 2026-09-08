from fastapi import Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.main import app
from app.discovery_ui import router as discovery_router
from app.storage import get_session,rows,one
from app.intelligence import analyze
import html

app.include_router(discovery_router)

def esc(x):return html.escape(str(x or ''))
def sess(r):
    s=get_session(r.cookies.get('gla_session'))
    if not s:raise HTTPException(401)
    return s

@app.get('/intelligence',response_class=HTMLResponse)
def intelligence(r:Request):
    try:s=sess(r)
    except HTTPException:return RedirectResponse('/login')
    opps=rows('SELECT * FROM opportunities ORDER BY score DESC,id DESC LIMIT 200')
    trs=''
    for o in opps:
        a=analyze(o); services=', '.join(a['services']) or 'غير محدد'
        trs+=f'<tr><td>{o["id"]}</td><td>{esc(o["company_name"])}</td><td><b>{a["priority"]}</b></td><td>{a["intent"]}</td><td>{esc(services)}</td><td>{esc(a["rationale"])}</td><td>{esc(a["next_action"])}</td></tr>'
    body='''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Opportunity Intelligence</title><style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}.wrap{max-width:1350px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav a{padding:10px 14px;border-radius:10px;background:#18384d;color:white;text-decoration:none;font-weight:bold}table{width:100%;border-collapse:collapse}th,td{text-align:right;padding:11px;border-bottom:1px solid #28475d;vertical-align:top}.scroll{overflow:auto}.muted{color:#9fb4c4}</style><body><div class="wrap"><h1>Opportunity Intelligence</h1><div class="muted">تحليل أولوية الفرص والخدمة المناسبة والخطوة التالية</div><div class="nav"><a href="/dashboard">الرئيسية</a><a href="/discovery">اكتشاف الفرص</a><a href="/opportunities">الفرص</a><a href="/intelligence">Intelligence</a></div><div class="card scroll"><table><tr><th>#</th><th>الشركة</th><th>الأولوية</th><th>نية الشراء</th><th>الخدمات المناسبة</th><th>سبب التقييم</th><th>الإجراء المقترح</th></tr>'''+trs+'''</table></div></div></body></html>'''
    return HTMLResponse(body,headers={'Cache-Control':'no-store'})

@app.get('/api/v8/intelligence')
def intelligence_api(r:Request):
    sess(r); out=[]
    for o in rows('SELECT * FROM opportunities ORDER BY score DESC,id DESC LIMIT 200'):
        out.append({'opportunity':o,'intelligence':analyze(o)})
    return out
