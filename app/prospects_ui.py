"""Prospects: shared page helpers, labels and the router.
"""
from app.prospects_schema import *  # noqa: F401,F403

router = APIRouter()


# ---------------------------------------------------------------- web

def esc(v):
    return html.escape(str(v if v is not None else ''))


def admin(request):
    s = get_session(request.cookies.get('gla_session'))
    if not s:
        raise HTTPException(401)
    if s.get('role') != 'admin':
        raise HTTPException(403)
    return s


async def checked(request):
    s = admin(request)
    data = {k: v[0] for k, v in urllib.parse.parse_qs((await request.body()).decode()).items()}
    if data.get('csrf') != s['csrf']:
        raise HTTPException(403)
    return s, data


def page(title, body):
    try:
        from app.branding import BRAND_CSS
    except ImportError:
        BRAND_CSS = ''
    style = BRAND_CSS or ('body{font-family:Tahoma,Arial;background:#07131f;color:#eef6fb;margin:0}.w{max-width:1300px;margin:auto;padding:24px}'
        '.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}'
        '.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}'
        '.kpi{background:#0d2231;border:1px solid #28475d;border-radius:14px;padding:16px}.kpi b{display:block;font-size:28px;color:#ffd978}'
        'input,select{padding:11px;border-radius:9px;border:1px solid #36586e;background:#081925;color:#fff;width:100%;box-sizing:border-box}'
        '.btn{display:inline-block;padding:10px 16px;border-radius:10px;border:0;background:linear-gradient(135deg,#ffd978,#e7b64b);color:#132331;font-weight:800;cursor:pointer;text-decoration:none}'
        'table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #28475d;text-align:right;vertical-align:top}th{color:#ffd978}'
        '.scroll{overflow-x:auto}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav a{padding:9px 13px;border-radius:10px;background:#18384d;color:#fff;text-decoration:none}'
        '.pill{display:inline-block;padding:3px 10px;border-radius:999px;font-size:13px}.q{background:#14532d;color:#bbf7d0}.p{background:#1e3a5f;color:#bfdbfe}'
        '.r{background:#3f3413;color:#fde68a}.x{background:#4c1d24;color:#fecaca}.muted{color:#9fb4c4}a{color:#dff6ff}')
    return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                        '<title>' + esc(title) + '</title><style>' + style + '</style><body><div class="w wrap">' + body + '</div></body></html>')


TIERS = {'qualified': ('مؤهل للبريد', 'q'), 'phone_only': ('مؤهل — هاتف فقط', 'p'), 'review': ('يحتاج مراجعة', 'r'), 'excluded': ('مستبعد', 'x')}
STATUSES = {'new': 'جديد', 'contacted': 'أُرسلت الرسالة الأولى', 'done': 'اكتملت المتابعة', 'replied': 'ردّ — فرصة مفتوحة',
            'bounced': 'بريد مرتد', 'suppressed': 'أوقف الرسائل', 'excluded': 'مستبعد'}


