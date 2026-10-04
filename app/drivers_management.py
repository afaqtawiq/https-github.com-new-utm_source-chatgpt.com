import html
import urllib.parse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.data_import import _phone
from app.carrier_records import DRIVER_TYPES, csv_text
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
    return '<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/carriers">شركات النقل</a><a href="/drivers">السائقون</a><a href="/data-import">استيراد البيانات</a><a href="/shipments">الشحنات</a><a href="/approvals">الموافقات</a></div>'

def driver_form(action, driver=None):
    driver = driver or {}
    country_options = ''.join(
        '<option value="'+code+'">'+label+' (+'+code+')</option>'
        for code, label in (
            ('966','السعودية'), ('971','الإمارات'), ('965','الكويت'),
            ('973','البحرين'), ('974','قطر'), ('968','عُمان')
        )
    )
    return '<form method="post" action="'+action+'"><div class="grid"><label>اسم السائق<input name="driver_name" value="'+esc(driver.get('driver_name'))+'" required></label><label>دولة الرقم<select name="country_code">'+country_options+'</select></label><label>رقم واتساب<input class="ltr" name="whatsapp_phone" value="'+esc(driver.get('whatsapp_phone'))+'" placeholder="مثال: 0501234567" required></label><label>نوع المركبة<input name="vehicle_type" value="'+esc(driver.get('vehicle_type'))+'" required></label><label>سعة الحمولة<input name="capacity" value="'+esc(driver.get('capacity'))+'"></label><label>المدينة الحالية<input name="current_city" value="'+esc(driver.get('current_city'))+'"></label><label>المسارات المفضلة<input name="preferred_routes" value="'+esc(driver.get('preferred_routes'))+'"></label><label>التوفر<select name="availability"><option value="متاح"'+selected(driver.get('availability','متاح'),'متاح')+'>متاح</option><option value="غير متاح"'+selected(driver.get('availability'),'غير متاح')+'>غير متاح</option><option value="غير محدد"'+selected(driver.get('availability'),'غير محدد')+'>غير محدد</option></select></label><label>اسم المؤسسة<input name="company_name" value="'+esc(driver.get('company_name'))+'"></label></div><label>ملاحظات<textarea name="notes">'+esc(driver.get('notes'))+'</textarea></label><p class="muted">تسجيل السائق يضمه إلى قائمة استقبال عروض الحمولات.</p><button class="btn">حفظ السائق</button></form>'

def selected(actual, expected):
    return ' selected' if (actual or '') == expected else ''

@router.get('/drivers', response_class=HTMLResponse)
def drivers(request: Request, q: str = '', availability: str = '', consent: str = '', page_number: int = 1, record_type: str = ''):
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
    if record_type:
        if record_type not in DRIVER_TYPES:
            raise HTTPException(400, 'Invalid record type')
        clauses.append('record_type=%s'); args.append(record_type)
    where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
    total = one('SELECT COUNT(*) n FROM drivers'+where, tuple(args))['n']
    per_page = 50
    offset = (page_number - 1) * per_page
    data = rows('SELECT * FROM drivers'+where+' ORDER BY driver_name,id LIMIT %s OFFSET %s', tuple(args+[per_page, offset]))
    total_all = one('SELECT COUNT(*) n FROM drivers')['n']
    available = one("SELECT COUNT(*) n FROM drivers WHERE availability='متاح'")['n']
    query = urllib.parse.urlencode({'q': q, 'availability': availability, 'record_type': record_type})
    table_rows = ''.join(
        '<tr><td>'+esc(x['driver_name'])+'<br><span class="muted">'+esc(DRIVER_TYPES.get(x.get('record_type'),'بانتظار تصنيف الإدارة'))+'</span></td><td class="ltr">'+esc(x['whatsapp_phone'])+'</td><td>'+esc(x['vehicle_type'])+'</td><td>'+esc(x['current_city'])+'</td><td>'+esc(x['company_name'])+'</td><td>'+esc(x['availability'])+'</td><td><a class="btn" href="/drivers/'+str(x['id'])+'/edit">عرض وتعديل</a></td></tr>'
        for x in data
    ) or '<tr><td colspan="7" class="muted">لا توجد نتائج مطابقة.</td></tr>'
    previous = '<a class="btn" href="/drivers?'+query+'&page_number='+str(page_number-1)+'">السابق</a>' if page_number > 1 else ''
    next_link = '<a class="btn" href="/drivers?'+query+'&page_number='+str(page_number+1)+'">التالي</a>' if offset + per_page < total else ''
    body = nav()+'<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap"><h1>إدارة السائقين</h1><a class="btn" href="/drivers/new">+ إضافة سائق جديد</a></div><div class="grid"><div class="kpi">سجلات دليل السائقين<b>'+str(total_all)+'</b></div><div class="kpi">متاحون<b>'+str(available)+'</b></div><div class="kpi">نتائج البحث<b>'+str(total)+'</b></div></div>'
    review_count = one("SELECT COUNT(*) n FROM drivers WHERE record_type='unreviewed'")["n"]
    body += '<p class="muted">السجلات القديمة محفوظة كما هي وقد تتضمن شركات. بانتظار تصنيف الإدارة: '+str(review_count)+'. <a href="/drivers?record_type=unreviewed">مراجعة التصنيف</a> · <a href="/drivers/export.csv?'+query+'">تصدير الكشف الحالي مع التصنيف</a></p>'
    body += '<p class="muted">كل سائق مسجل منضم لاستقبال عروض الحمولات. تشمل الحملة جميع الأرقام الصالحة غير المكررة.</p>'
    type_options = '<select name="record_type"><option value="">كل التصنيفات</option>'+''.join('<option value="'+key+'"'+selected(record_type,key)+'>'+esc(label)+'</option>' for key,label in DRIVER_TYPES.items())+'</select>'
    body += '<div class="card"><form method="get" action="/drivers"><div class="grid"><input name="q" value="'+esc(q)+'" placeholder="بحث بالاسم أو الجوال أو الشركة أو المدينة"><select name="availability"><option value="">كل حالات التوفر</option><option value="متاح"'+selected(availability,'متاح')+'>متاح</option><option value="غير متاح"'+selected(availability,'غير متاح')+'>غير متاح</option><option value="غير محدد"'+selected(availability,'غير محدد')+'>غير محدد</option></select>'+type_options+'<button class="btn">بحث وتصفية</button></div></form></div>'
    body += '<div class="card scroll"><table><tr><th>السائق</th><th>واتساب</th><th>المركبة</th><th>المدينة</th><th>الشركة</th><th>التوفر</th><th>الإجراء</th></tr>'+table_rows+'</table><div class="pager">'+previous+'<span>صفحة '+str(page_number)+'</span>'+next_link+'</div></div>'
    return HTMLResponse(page('إدارة السائقين', body))

@router.get('/drivers/export.csv')
def export_drivers(request: Request, q: str = '', availability: str = '', record_type: str = ''):
    if not auth(request):
        raise HTTPException(401)
    clauses, args = [], []
    if q.strip():
        clauses.append('(driver_name ILIKE %s OR whatsapp_phone ILIKE %s OR company_name ILIKE %s OR current_city ILIKE %s OR notes ILIKE %s)')
        args.extend(['%'+q.strip()+'%']*5)
    if availability:
        clauses.append('availability=%s'); args.append(availability)
    if record_type:
        if record_type not in DRIVER_TYPES:
            raise HTTPException(400, 'Invalid record type')
        clauses.append('record_type=%s'); args.append(record_type)
    where = ' WHERE '+' AND '.join(clauses) if clauses else ''
    data = rows('SELECT * FROM drivers'+where+' ORDER BY driver_name,id',tuple(args))
    keys = ['id','record_type','driver_name','whatsapp_phone','vehicle_type','capacity','current_city','preferred_routes','availability','company_name','carrier_company_id','notes']
    return Response(csv_text(keys,data),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="driver-register.csv"'})


def classification_form(session, driver):
    current_type = driver.get('record_type') or 'unreviewed'
    if session['role'] != 'admin':
        return '<div class="card">التصنيف: '+esc(DRIVER_TYPES.get(current_type,current_type))+'</div>'
    options = ''.join('<option value="'+key+'"'+selected(current_type,key)+'>'+esc(label)+'</option>' for key,label in DRIVER_TYPES.items())
    companies = rows('SELECT id,company_name FROM carrier_companies ORDER BY company_name,id')
    links = '<option value="">بدون ربط</option>'+''.join('<option value="'+str(item['id'])+'"'+selected(str(driver.get('carrier_company_id') or ''),str(item['id']))+'>'+esc(item['company_name'])+'</option>' for item in companies)
    return '<div class="card"><h2>تصنيف السجل وربط الشركة</h2><p class="muted">تصنيف يدوي من الإدارة فقط. لا يحذف السجل ولا ينقله ولا يغير سجل العروض أو موافقات الإرسال. اسم المؤسسة أو تشابه الهاتف لا يثبت الارتباط.</p><form method="post" action="/drivers/'+str(driver['id'])+'/classify"><input type="hidden" name="csrf" value="'+esc(session['csrf'])+'"><label>نوع السجل<select name="record_type">'+options+'</select></label><label>الشركة المرتبطة بعد التحقق<select name="carrier_company_id">'+links+'</select></label><button class="btn">تأكيد التصنيف والربط</button></form><a href="/carriers/new">إضافة شركة في كشف الشركات</a></div>'


@router.post('/drivers/{driver_id}/classify')
async def classify_driver(driver_id: int, request: Request):
    from app.carrier_directory import auth as directory_auth, csrf
    from app.storage import db
    session = directory_auth(request,admin=True)
    form = await request.form(); csrf(session,form)
    record_type = str(form.get('record_type') or '')
    if record_type not in DRIVER_TYPES:
        raise HTTPException(400,'Invalid record type')
    carrier_id = str(form.get('carrier_company_id') or '').strip()
    if carrier_id and (not carrier_id.isascii() or not carrier_id.isdigit()):
        raise HTTPException(400,'Invalid company reference')
    if record_type == 'independent_driver' and carrier_id:
        raise HTTPException(400,'Independent driver cannot have a company link')
    with db() as connection:
        current = connection.execute('SELECT id FROM drivers WHERE id=%s FOR UPDATE',(driver_id,)).fetchone()
        if not current:
            raise HTTPException(404,'Driver record not found')
        if carrier_id and not connection.execute('SELECT id FROM carrier_companies WHERE id=%s',(int(carrier_id),)).fetchone():
            raise HTTPException(400,'Company not found')
        connection.execute('UPDATE drivers SET record_type=%s,carrier_company_id=%s,classified_by=%s,classified_at=%s WHERE id=%s',
            (record_type,int(carrier_id) if carrier_id else None,session['user_id'],utcnow(),driver_id))
        connection.execute('INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at) VALUES(%s,%s,%s,%s,%s,%s)',
            (session['user_id'],'classify','driver',driver_id,'Manual type '+record_type+'; company '+(carrier_id or 'none')+'; history and offer flags unchanged',utcnow()))
    return RedirectResponse('/drivers/'+str(driver_id)+'/edit',303)


@router.get('/drivers/new', response_class=HTMLResponse)
def new_driver(request: Request):
    session = auth(request)
    if not session:
        return RedirectResponse('/login', 303)
    if session.get('role') != 'admin':
        raise HTTPException(403, 'Admin role required to add drivers')
    return HTMLResponse(page('إضافة سائق جديد', nav()+'<h1>إضافة سائق جديد</h1><div class="card">'+driver_form('/drivers/new')+'</div>'))

@router.post('/drivers/new')
async def create_driver(request: Request):
    session = auth(request)
    if not session:
        return RedirectResponse('/login', 303)
    if session.get('role') != 'admin':
        raise HTTPException(403, 'Admin role required to add drivers')
    form = await request.form()
    driver_name = str(form.get('driver_name') or '').strip()
    vehicle_type = str(form.get('vehicle_type') or '').strip()
    phone = _phone(form.get('whatsapp_phone'), str(form.get('country_code') or '966'))
    if not driver_name or not vehicle_type:
        raise HTTPException(400, 'Driver name and vehicle type are required')
    if not phone:
        raise HTTPException(400, 'Invalid GCC WhatsApp number')
    consent = 1
    consent_date = ''
    now = utcnow()
    try:
        driver_id = execute('''INSERT INTO drivers(driver_name,whatsapp_phone,vehicle_type,capacity,current_city,preferred_routes,availability,company_name,offer_consent,consent_date,notes,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,NULLIF(%s,'')::date,%s,%s,%s)''',(
            driver_name, phone, vehicle_type, str(form.get('capacity') or '').strip(), str(form.get('current_city') or '').strip(), str(form.get('preferred_routes') or '').strip(), str(form.get('availability') or 'متاح').strip(), str(form.get('company_name') or '').strip(), consent, consent_date, str(form.get('notes') or '').strip(), now, now
        ))
    except Exception as exc:
        if 'unique' in str(exc).lower() or 'duplicate' in str(exc).lower():
            raise HTTPException(409, 'WhatsApp number already belongs to another driver')
        raise
    log(session['user_id'], 'create', 'driver', driver_id, 'Driver registered for freight offers')
    return RedirectResponse('/drivers', 303)

@router.get('/drivers/{driver_id}/edit', response_class=HTMLResponse)
def edit_driver(driver_id: int, request: Request):
    session = auth(request)
    if not session:
        return RedirectResponse('/login', 303)
    driver = one('SELECT * FROM drivers WHERE id=%s', (driver_id,))
    if not driver:
        raise HTTPException(404, 'Driver not found')
    form = '<form method="post" action="/drivers/'+str(driver_id)+'/edit"><div class="grid"><label>اسم السائق<input name="driver_name" value="'+esc(driver['driver_name'])+'" required></label><label>رقم واتساب<input class="ltr" name="whatsapp_phone" value="'+esc(driver['whatsapp_phone'])+'" required></label><label>نوع المركبة<input name="vehicle_type" value="'+esc(driver['vehicle_type'])+'" required></label><label>سعة الحمولة<input name="capacity" value="'+esc(driver['capacity'])+'"></label><label>المدينة الحالية<input name="current_city" value="'+esc(driver['current_city'])+'"></label><label>المسارات المفضلة<input name="preferred_routes" value="'+esc(driver['preferred_routes'])+'"></label><label>التوفر<select name="availability"><option value="متاح"'+selected(driver['availability'],'متاح')+'>متاح</option><option value="غير متاح"'+selected(driver['availability'],'غير متاح')+'>غير متاح</option><option value="غير محدد"'+selected(driver['availability'],'غير محدد')+'>غير محدد</option></select></label><label>اسم المؤسسة<input name="company_name" value="'+esc(driver['company_name'])+'"></label></div><label>ملاحظات<textarea name="notes">'+esc(driver['notes'])+'</textarea></label><p class="muted">تسجيل السائق يضمه إلى قائمة استقبال عروض الحمولات.</p><button class="btn">حفظ التعديلات</button></form>'
    classification = classification_form(session, driver)
    return HTMLResponse(page('تعديل السائق', nav()+'<h1>تعديل السائق</h1><div class="card">'+form+'</div>'+classification))

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
    consent = 1
    consent_date = str(current.get('consent_date') or '')
    try:
        execute('''UPDATE drivers SET driver_name=%s,whatsapp_phone=%s,vehicle_type=%s,capacity=%s,current_city=%s,preferred_routes=%s,availability=%s,company_name=%s,offer_consent=%s,consent_date=NULLIF(%s,'')::date,notes=%s,updated_at=%s WHERE id=%s''',(
            str(form.get('driver_name') or '').strip(), phone, str(form.get('vehicle_type') or '').strip(), str(form.get('capacity') or '').strip(), str(form.get('current_city') or '').strip(), str(form.get('preferred_routes') or '').strip(), str(form.get('availability') or 'غير محدد').strip(), str(form.get('company_name') or '').strip(), consent, consent_date, str(form.get('notes') or '').strip(), utcnow(), driver_id
        ))
    except Exception as exc:
        if 'unique' in str(exc).lower() or 'duplicate' in str(exc).lower():
            raise HTTPException(409, 'WhatsApp number already belongs to another driver')
        raise
    log(session['user_id'], 'update', 'driver', driver_id, 'Driver profile updated; registration includes freight offers')
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
