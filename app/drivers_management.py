import html
import urllib.parse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.data_import import _phone
from app.storage import execute, get_session, log, one, rows, utcnow

router = APIRouter()

STYLE = '''<style>body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}*{box-sizing:border-box}.wrap{max-width:1350px;margin:auto;padding:24px}.nav{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.nav a,.btn{display:inline-block;padding:10px 14px;border:0;border-radius:10px;background:#18384d;color:white;font-weight:700;text-decoration:none;cursor:pointer}.btn{background:#22c55e;color:#04130a}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}.kpi{background:#0b1d2b;padding:16px;border-radius:12px}.kpi b{font-size:24px;display:block;margin-top:6px}input,select,textarea{padding:11px;border:1px solid #36586e;border-radius:9px;background:#081925;color:white;width:100%}textarea{min-height:90px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse}th,td{text-align:right;padding:10px;border-bottom:1px solid #28475d;vertical-align:top;white-space:nowrap}.muted{color:#9fb4c4}.good{color:#86efac}.warn{color:#fde68a}.bad{color:#fca5a5}.ltr{direction:ltr;text-align:left}.pager{display:flex;gap:8px;align-items:center;justify-content:center;margin-top:16px}</style>'''

def esc(value):
    return html.escape(str(value or ''))

def page(title, body):
    return '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title>'+STYLE+'<body><div class="wrap">'+body+'</div></body></html>'

def auth(request):
    session = get_session(request.cookies.get('gla_session'))
    if not session:
        return None
    if session.get('role') not in ('admin', 'transport'):
        raise HTTPException(403, 'Driver directory requires admin or transport role')
    return session

def nav():
    return '<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/drivers">السائقون</a><a href="/data-import">استيراد البيانات</a><a href="/shipments">الشحنات</a><a href="/approvals">الموافقات</a></div>'

def selected(actual, expected):
    return ' selected' if (actual or '') == expected else ''

@router.get('/drivers', response_class=HTMLResponse)
def drivers(request: Request, q: str = '', availability: str = '', consent: str = '', page_number: int = 1):
    session = auth(request)
    if not session:
        return RedirectResponse('/login', 303)
    page_number = max(1, page_number)
    clauses = []
    args = []
    if q.strip():
        term = '%'+q.strip()+'%'
        clauses.append('(driver_name ILIKE %s OR whatsapp_phone ILIKE %s OR company_name ILIKE %s OR current_city ILIKE %s OR notes ILIKE %s)')
        args.extend([term] * 5)
    if availability:
        clauses.append('availability=%s')
        args.append(availability)
    if consent in ('0', '1'):
        clauses.append('offer_consent=%s')
        args.append(int(consent))
    where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
    total = one('SELECT COUNT(*) n FROM drivers'+where, tuple(args))['n']
    per_page = 50
    offset = (page_number - 1) * per_page
    data = rows('SELECT * FROM drivers'+where+' ORDER BY driver_name,id LIMIT %s OFFSET %s', tuple(args+[per_page, offset]))
    total_all = one('SELECT COUNT(*) n FROM drivers')['n']
    consented = one('SELECT COUNT(*) n FROM drivers WHERE offer_consent=1')['n']
    available = one("SELECT COUNT(*) n FROM drivers WHERE availability='متاح'")['n']
    query = urllib.parse.urlencode({'q': q, 'availability': availability, 'consent': consent})
    table_rows = ''.join(
        '<tr><td>'+esc(x['driver_name'])+'</td><td class="ltr">'+esc(x['whatsapp_phone'])+'</td><td>'+esc(x['vehicle_type'])+'</td><td>'+esc(x['current_city'])+'</td><td>'+esc(x['company_name'])+'</td><td>'+esc(x['availability'])+'</td><td>'+('<span class="good">موافق</span>' if x['offer_consent'] else '<span class="warn">غير مسجل</span>')+'</td><td><a class="btn" href="/drivers/'+str(x['id'])+'/edit">عرض وتعديل</a></td></tr>'
        for x in data
    ) or '<tr><td colspan="8" class="muted">لا توجد نتائج مطابقة.</td></tr>'
    previous = '<a class="btn" href="/drivers?'+query+'&page_number='+str(page_number-1)+'">السابق</a>' if page_number > 1 else ''
    next_link = '<a class="btn" href="/drivers?'+query+'&page_number='+str(page_number+1)+'">التالي</a>' if offset + per_page < total else ''
    body = nav()+'<h1>إدارة السائقين</h1><div class="grid"><div class="kpi">إجمالي السائقين<b>'+str(total_all)+'</b></div><div class="kpi">موافقة استقبال العروض<b>'+str(consented)+'</b></div><div class="kpi">متاحون<b>'+str(available)+'</b></div><div class="kpi">نتائج البحث<b>'+str(total)+'</b></div></div>'
    body += '<div class="card"><form method="get" action="/drivers"><div class="grid"><input name="q" value="'+esc(q)+'" placeholder="بحث بالاسم أو الجوال أو الشركة أو المدينة"><select name="availability"><option value="">كل حالات التوفر</option><option value="متاح"'+selected(availability,'متاح')+'>متاح</option><option value="غير متاح"'+selected(availability,'غير متاح')+'>غير متاح</option><option value="غير محدد"'+selected(availability,'غير محدد')+'>غير محدد</option></select><select name="consent"><option value="">كل حالات الموافقة</option><option value="1"'+selected(consent,'1')+'>موافق على العروض</option><option value="0"'+selected(consent,'0')+'>الموافقة غير مسجلة</option></select><button class="btn">بحث وتصفية</button></div></form></div>'
    body += '<div class="card scroll"><table><tr><th>السائق</th><th>واتساب</th><th>المركبة</th><th>المدينة</th><th>الشركة</th><th>التوفر</th><th>موافقة العروض</th><th>الإجراء</th></tr>'+table_rows+'</table><div class="pager">'+previous+'<span>صفحة '+str(page_number)+'</span>'+next_link+'</div></div>'
    return HTMLResponse(page('إدارة السائقين', body))

@router.get('/drivers/{driver_id}/edit', response_class=HTMLResponse)
def edit_driver(driver_id: int, request: Request):
    session = auth(request)
    if not session:
        return RedirectResponse('/login', 303)
    driver = one('SELECT * FROM drivers WHERE id=%s', (driver_id,))
    if not driver:
        raise HTTPException(404, 'Driver not found')
    form = '<form method="post" action="/drivers/'+str(driver_id)+'/edit"><div class="grid"><label>اسم السائق<input name="driver_name" value="'+esc(driver['driver_name'])+'" required></label><label>رقم واتساب<input class="ltr" name="whatsapp_phone" value="'+esc(driver['whatsapp_phone'])+'" required></label><label>نوع المركبة<input name="vehicle_type" value="'+esc(driver['vehicle_type'])+'" required></label><label>سعة الحمولة<input name="capacity" value="'+esc(driver['capacity'])+'"></label><label>المدينة الحالية<input name="current_city" value="'+esc(driver['current_city'])+'"></label><label>المسارات المفضلة<input name="preferred_routes" value="'+esc(driver['preferred_routes'])+'"></label><label>التوفر<select name="availability"><option value="متاح"'+selected(driver['availability'],'متاح')+'>متاح</option><option value="غير متاح"'+selected(driver['availability'],'غير متاح')+'>غير متاح</option><option value="غير محدد"'+selected(driver['availability'],'غير محدد')+'>غير محدد</option></select></label><label>اسم المؤسسة<input name="company_name" value="'+esc(driver['company_name'])+'"></label><label>موافقة استقبال العروض<select name="offer_consent"><option value="0"'+selected(str(driver['offer_consent']),'0')+'>غير مسجلة</option><option value="1"'+selected(str(driver['offer_consent']),'1')+'>موافق</option></select></label><label>تاريخ الموافقة<input type="date" name="consent_date" value="'+esc(driver['consent_date'])+'"></label></div><label>ملاحظات<textarea name="notes">'+esc(driver['notes'])+'</textarea></label><p class="muted">تفعيل الموافقة يجب أن يعتمد على موافقة حقيقية وموثقة من السائق.</p><button class="btn">حفظ التعديلات</button></form>'
    return HTMLResponse(page('تعديل السائق', nav()+'<h1>تعديل السائق</h1><div class="card">'+form+'</div>'))

@router.post('/drivers/{driver_id}/edit')
async def update_driver(driver_id: int, request: Request):
    session = auth(request)
    if not session:
        return RedirectResponse('/login', 303)
    if session.get('role') != 'admin':
        raise HTTPException(403, 'Admin role required to edit drivers')
    current = one('SELECT * FROM drivers WHERE id=%s', (driver_id,))
    if not current:
        raise HTTPException(404, 'Driver not found')
    form = await request.form()
    phone = _phone(form.get('whatsapp_phone'), '971')
    if not phone:
        raise HTTPException(400, 'Invalid GCC WhatsApp number')
    consent = 1 if form.get('offer_consent') == '1' else 0
    consent_date = str(form.get('consent_date') or '') if consent else ''
    if consent and not consent_date:
        raise HTTPException(400, 'Consent date is required when offer consent is enabled')
    try:
        execute('''UPDATE drivers SET driver_name=%s,whatsapp_phone=%s,vehicle_type=%s,capacity=%s,current_city=%s,preferred_routes=%s,availability=%s,company_name=%s,offer_consent=%s,consent_date=NULLIF(%s,'')::date,notes=%s,updated_at=%s WHERE id=%s''',(
            str(form.get('driver_name') or '').strip(), phone, str(form.get('vehicle_type') or '').strip(), str(form.get('capacity') or '').strip(), str(form.get('current_city') or '').strip(), str(form.get('preferred_routes') or '').strip(), str(form.get('availability') or 'غير محدد').strip(), str(form.get('company_name') or '').strip(), consent, consent_date, str(form.get('notes') or '').strip(), utcnow(), driver_id
        ))
    except Exception as exc:
        if 'unique' in str(exc).lower() or 'duplicate' in str(exc).lower():
            raise HTTPException(409, 'WhatsApp number already belongs to another driver')
        raise
    log(session['user_id'], 'update', 'driver', driver_id, 'Driver profile updated; offer consent='+str(consent))
    return RedirectResponse('/drivers/'+str(driver_id)+'/edit', 303)

@router.get('/api/v7/drivers')
def api_drivers(request: Request, q: str = '', limit: int = 200):
    if not auth(request):
        raise HTTPException(401)
    limit = min(max(limit, 1), 500)
    if q.strip():
        term = '%'+q.strip()+'%'
        return rows('SELECT * FROM drivers WHERE driver_name ILIKE %s OR whatsapp_phone ILIKE %s OR company_name ILIKE %s ORDER BY driver_name LIMIT %s', (term, term, term, limit))
    return rows('SELECT * FROM drivers ORDER BY driver_name LIMIT %s', (limit,))
