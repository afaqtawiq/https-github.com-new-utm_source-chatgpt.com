import html
import json
import os
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.storage import db, get_session, log, utcnow

router = APIRouter()
PLACES_URL = 'https://places.googleapis.com/v1/places:searchText'
REGIONS = {'sa':'السعودية','ae':'الإمارات','kw':'الكويت','bh':'البحرين','qa':'قطر','om':'عُمان'}


def esc(value):
    return html.escape(str(value or ''))


def admin(request):
    session = get_session(request.cookies.get('gla_session'))
    if not session:
        return None
    if session.get('role') != 'admin':
        raise HTTPException(403, 'Admin role required')
    return session


def page(body):
    return HTMLResponse('''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>اكتشاف الشركات من خرائط Google</title><style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}.w{max-width:1200px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}input,select,button{width:100%;padding:11px;border-radius:9px;border:1px solid #36586e;background:#081925;color:#fff}.btn{background:#22c55e;color:#04130a;font-weight:bold;cursor:pointer}.links a{color:#dff6ff;margin-left:12px}.ok{color:#86efac}.warn{color:#fde68a}.bad{color:#fca5a5}</style><div class="w">'''+body+'</div></html>')


def search_places(query, region, limit):
    api_key = os.getenv('GOOGLE_MAPS_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('GOOGLE_MAPS_API_KEY is not configured')
    payload = json.dumps({
        'textQuery': query,
        'languageCode': 'ar',
        'regionCode': region,
        'pageSize': limit,
        'includePureServiceAreaBusinesses': True,
    }).encode('utf-8')
    request = urllib.request.Request(PLACES_URL, data=payload, method='POST', headers={
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': api_key,
        'X-Goog-FieldMask': 'places.id,places.displayName,places.formattedAddress,places.location,places.primaryTypeDisplayName,places.googleMapsUri,places.businessStatus',
    })
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode('utf-8')).get('places', [])
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:500]
        raise RuntimeError('Google Places HTTP '+str(exc.code)+': '+detail) from exc


@router.get('/google-places', response_class=HTMLResponse)
def google_places_home(request: Request):
    session = admin(request)
    if not session:
        return RedirectResponse('/login', 303)
    configured = bool(os.getenv('GOOGLE_MAPS_API_KEY', '').strip())
    status = '<p class="ok">واجهة Google Places مفعلة.</p>' if configured else '<p class="warn">يلزم إضافة GOOGLE_MAPS_API_KEY إلى إعدادات Railway وتفعيل Places API (New).</p>'
    options = ''.join('<option value="'+code+'">'+label+'</option>' for code,label in REGIONS.items())
    body = '<div class="links"><a href="/dashboard">الرئيسية</a><a href="/accounts">العملاء</a></div><h1>اكتشاف الشركات من خرائط Google</h1><div class="card">'+status+'<p>اكتب نشاطًا وموقعًا محددًا مثل: مصانع الأغذية في جدة، مستوردو قطع الغيار في الرياض، أو مستودعات التجارة الإلكترونية في الدمام.</p><form method="post" action="/google-places/discover"><div class="grid"><input name="query" minlength="3" placeholder="نوع الشركات والمدينة" required><select name="region">'+options+'</select><select name="limit"><option value="10">10 نتائج</option><option value="20">20 نتيجة</option></select></div><p><button class="btn"'+('' if configured else ' disabled')+'>بحث وإضافة النتائج الجديدة</button></p></form><p class="warn">يحفظ النظام الشركات الجديدة فقط ويمنع تكرار الاسم. بيانات خرائط Google قد تكون ناقصة؛ راجع السجل قبل التواصل.</p></div>'
    return page(body)


@router.post('/google-places/discover', response_class=HTMLResponse)
async def discover_google_places(request: Request):
    session = admin(request)
    if not session:
        return RedirectResponse('/login', 303)
    form = await request.form()
    query = str(form.get('query') or '').strip()
    region = str(form.get('region') or 'sa').lower()
    limit = int(form.get('limit') or 10)
    if len(query) < 3 or region not in REGIONS or limit not in (10, 20):
        raise HTTPException(400, 'Invalid search parameters')
    try:
        places = search_places(query, region, limit)
    except RuntimeError as exc:
        return page('<div class="links"><a href="/google-places">العودة</a></div><div class="card bad"><h1>تعذر البحث</h1><p>'+esc(exc)+'</p></div>')
    inserted = 0
    duplicates = 0
    now = utcnow()
    with db() as connection:
        for place in places:
            name = str((place.get('displayName') or {}).get('text') or '').strip()
            if not name:
                continue
            exists = connection.execute('SELECT 1 FROM accounts WHERE LOWER(name)=LOWER(%s)', (name,)).fetchone()
            if exists:
                duplicates += 1
                continue
            address = str(place.get('formattedAddress') or '').strip()
            category = str((place.get('primaryTypeDisplayName') or {}).get('text') or '').strip()
            location = place.get('location') or {}
            notes = 'المصدر: Google Places | Place ID: '+str(place.get('id') or '')+' | رابط الخريطة: '+str(place.get('googleMapsUri') or '')+' | حالة النشاط: '+str(place.get('businessStatus') or '')+' | إحداثيات: '+str(location.get('latitude') or '')+','+str(location.get('longitude') or '')
            saved = connection.execute('''INSERT INTO accounts(name,country,domain,status,notes,created_at,updated_at) VALUES(%s,%s,%s,'جديد',%s,%s,%s) RETURNING id''', (name,address,category,notes,now,now)).fetchone()
            if saved:
                inserted += 1
    log(session['user_id'], 'google_places_discovery', 'account', None, 'Query='+query+'; inserted='+str(inserted)+'; duplicates='+str(duplicates))
    return page('<div class="links"><a href="/google-places">بحث جديد</a><a href="/accounts">عرض العملاء</a></div><div class="card ok"><h1>اكتمل البحث</h1><p>أضاف النظام '+str(inserted)+' شركة جديدة، وتجاوز '+str(duplicates)+' شركة مكررة.</p></div>')
