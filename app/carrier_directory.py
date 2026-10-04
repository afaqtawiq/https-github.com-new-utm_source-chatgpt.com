"""Separate carrier-company records. No messaging, scheduling or audience hooks."""
import json
import secrets
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import carrier_records as records
from app.data_import import MAX_FILE_BYTES
from app.drivers_management import esc, page, selected
from app.storage import db, get_session, log, one, rows, utcnow

router = APIRouter()
LOCK_KEY = 73002041


def init_storage():
    with db() as connection:
        connection.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK_KEY,))
        connection.execute('''CREATE TABLE IF NOT EXISTS carrier_companies(
            id BIGSERIAL PRIMARY KEY, company_name TEXT NOT NULL, normalized_name TEXT NOT NULL,
            country TEXT NOT NULL CHECK(country IN ('SA','AE','QA','KW','BH','OM')),
            city TEXT NOT NULL DEFAULT '', contact_name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '', website TEXT NOT NULL DEFAULT '', website_domain TEXT NOT NULL DEFAULT '',
            preferred_routes TEXT NOT NULL DEFAULT '', vehicle_types TEXT NOT NULL DEFAULT '', capacity TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '', maps_url TEXT NOT NULL DEFAULT '',
            verification_status TEXT NOT NULL DEFAULT 'unverified' CHECK(verification_status IN ('unverified','public_contact_verified')),
            verified_on DATE, notes TEXT NOT NULL DEFAULT '', quote_notes TEXT NOT NULL DEFAULT '',
            contact_consent TEXT NOT NULL DEFAULT 'unknown' CHECK(contact_consent IN ('unknown','granted','declined')),
            consent_evidence TEXT NOT NULL DEFAULT '', consent_date DATE,
            created_by BIGINT REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
            UNIQUE(normalized_name,country))''')
        connection.execute('''CREATE TABLE IF NOT EXISTS carrier_import_batches(
            id TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), file_name TEXT NOT NULL,
            rows_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'preview', inserted_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL, committed_at TIMESTAMPTZ)''')
        # Additive only: existing IDs, history, malformed raw fields and offer flags remain untouched.
        connection.execute("ALTER TABLE drivers ADD COLUMN IF NOT EXISTS record_type TEXT NOT NULL DEFAULT 'unreviewed'")
        connection.execute('ALTER TABLE drivers ADD COLUMN IF NOT EXISTS carrier_company_id BIGINT REFERENCES carrier_companies(id)')
        connection.execute('ALTER TABLE drivers ADD COLUMN IF NOT EXISTS classified_by BIGINT REFERENCES users(id)')
        connection.execute('ALTER TABLE drivers ADD COLUMN IF NOT EXISTS classified_at TIMESTAMPTZ')


def auth(request, *, admin=False):
    session = get_session(request.cookies.get('gla_session'))
    if not session:
        raise HTTPException(401, 'Login required')
    if session.get('role') not in (('admin',) if admin else ('admin', 'transport')):
        raise HTTPException(403, 'Admin role required' if admin else 'Transport directory requires admin or transport role')
    return session


def csrf(session, form):
    token = str(form.get('csrf') or '')
    if not token or not secrets.compare_digest(token, str(session.get('csrf') or '')):
        raise HTTPException(403, 'Invalid CSRF token')


def nav():
    return '<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/carriers">شركات النقل</a><a href="/drivers">كشف السائقين</a><a href="/drivers?record_type=unreviewed">مراجعة السجلات القديمة</a><a href="/data-import">استيراد البيانات</a></div>'


def conflict(connection, record, exclude_id=0):
    found = connection.execute('''SELECT id,normalized_name,country,phone,email,website_domain FROM carrier_companies
        WHERE id<>%s AND ((normalized_name=%s AND country=%s) OR (phone<>'' AND phone=%s)
        OR (email<>'' AND email=%s) OR (website_domain<>'' AND website_domain=%s)) ORDER BY id''',
        (exclude_id, record['normalized_name'], record['country'], record['phone'], record['email'], record['website_domain'])).fetchall()
    exact = any((item['normalized_name'], item['country']) == records.identity_key(record) for item in found)
    return 'duplicate' if exact else 'shared_contact' if found else ''


def insert_company(connection, record, user_id):
    keys = records.COLUMNS + ['normalized_name', 'website_domain']
    values = [record[key] or None if key == 'verified_on' else record[key] for key in keys]
    return connection.execute('INSERT INTO carrier_companies('+','.join(keys)+',created_by,created_at,updated_at) VALUES('
        + ','.join(['%s']*(len(keys)+3)) + ') RETURNING id', tuple(values+[user_id, utcnow(), utcnow()])).fetchone()['id']


def visible_record(record, session):
    return {key: value for key, value in record.items() if session['role'] == 'admin' or key not in ('quote_notes', 'consent_evidence')}


def filters(q, country, verification):
    clauses, args = [], []
    if q.strip():
        clauses.append('(company_name ILIKE %s OR phone ILIKE %s OR email ILIKE %s OR city ILIKE %s OR preferred_routes ILIKE %s)')
        args.extend(['%'+q.strip()+'%']*5)
    if country:
        if country not in records.COUNTRIES:
            raise HTTPException(400, 'Invalid country')
        clauses.append('country=%s'); args.append(country)
    if verification:
        if verification not in records.VERIFICATIONS:
            raise HTTPException(400, 'Invalid verification status')
        clauses.append('verification_status=%s'); args.append(verification)
    return (' WHERE '+' AND '.join(clauses) if clauses else ''), args


def options(mapping, actual='', blank=''):
    return ('<option value="">'+esc(blank)+'</option>' if blank else '') + ''.join('<option value="'+esc(key)+'"'+selected(actual,key)+'>'+esc(label)+'</option>' for key,label in mapping.items())


def company_form(session, record=None):
    record = record or {}
    fields = ''
    for key in records.COLUMNS:
        value = record.get(key, '')
        if key == 'country':
            field = '<select name="country" required>'+options(records.COUNTRIES,value, 'اختر الدولة')+'</select>'
        elif key == 'verification_status':
            field = '<select name="verification_status">'+options(records.VERIFICATIONS,value or 'unverified')+'</select>'
        elif key == 'notes':
            field = '<textarea name="notes">'+esc(value)+'</textarea>'
        else:
            field = '<input name="'+key+'" value="'+esc(value)+'"'+(' required' if key == 'company_name' else '')+(' type="date"' if key == 'verified_on' else '')+'>'
        fields += '<label>'+records.LABELS[key]+field+'</label>'
    return '<input type="hidden" name="csrf" value="'+esc(session['csrf'])+'"><div class="grid">'+fields+'</div><label><input type="checkbox" name="confirm_shared_contact" value="yes" style="width:auto"> تحققت أن جهة الاتصال المشتركة تخص شركة مستقلة؛ لا تدمج السجلين</label><p class="muted">اترك المعلومات غير المعروفة فارغة. توثيق المصدر العام لا يؤكد الترخيص أو تملك الأسطول أو التوفر أو السعر. الحفظ لا يمنح موافقة تواصل ولا يرسل عروضًا.</p>'


@router.get('/carriers', response_class=HTMLResponse)
def directory(request: Request, q: str='', country: str='', verification: str='', page_number: int=1):
    session = auth(request)
    where, args = filters(q, country, verification)
    page_number = max(1, page_number); offset = (page_number-1)*50
    count = one('SELECT COUNT(*) n FROM carrier_companies'+where, tuple(args))['n']
    data = rows('SELECT * FROM carrier_companies'+where+' ORDER BY company_name,id LIMIT 50 OFFSET %s', tuple(args+[offset]))
    query = urlencode({'q':q,'country':country,'verification':verification})
    actions = '<a class="btn" href="/carriers/new">+ إضافة شركة نقل</a> <a class="btn" href="/carriers/import">استيراد شركات النقل</a>' if session['role']=='admin' else ''
    body = nav()+'<h1>كشف شركات النقل</h1><p>شركات وجهات نقل محتملة: '+str(count)+'</p>'+actions+' <a class="btn" href="/carriers/export.csv?'+query+'">تصدير كشف الشركات</a><p class="muted">هذا دليل شركات مستقل عن السائقين وقوائم الإرسال. لا يُرسل شيء عند الحفظ أو الاستيراد.</p>'
    body += '<div class="card"><form><div class="grid"><input name="q" value="'+esc(q)+'" placeholder="الشركة أو المدينة أو المسار أو جهة الاتصال"><select name="country">'+options(records.COUNTRIES,country,'كل الدول')+'</select><select name="verification">'+options(records.VERIFICATIONS,verification,'كل حالات التحقق')+'</select><button class="btn">بحث</button></div></form></div>'
    table = ''.join('<tr><td><a href="/carriers/'+str(item['id'])+'">'+esc(item['company_name'])+'</a></td><td>'+esc(records.COUNTRIES[item['country']])+' / '+esc(item['city'])+'</td><td class="ltr">'+esc(item['phone'])+'<br>'+esc(item['email'])+'</td><td>'+esc(item['preferred_routes'])+'</td><td>'+esc(item['vehicle_types'])+' / '+esc(item['capacity'])+'</td><td>'+esc(records.VERIFICATIONS[item['verification_status']])+'</td></tr>' for item in data) or '<tr><td colspan="6">لا توجد شركات مطابقة</td></tr>'
    body += '<div class="card scroll"><table><tr><th>شركة النقل</th><th>الموقع</th><th>الاتصال المنشور</th><th>المسارات</th><th>المركبات والسعة</th><th>التحقق</th></tr>'+table+'</table></div>'
    if page_number > 1: body += '<a class="btn" href="/carriers?'+query+'&page_number='+str(page_number-1)+'">السابق</a> '
    if offset+50 < count: body += '<a class="btn" href="/carriers?'+query+'&page_number='+str(page_number+1)+'">التالي</a>'
    return HTMLResponse(page('كشف شركات النقل',body))


@router.get('/carriers/export.csv')
def export(request: Request, q: str='', country: str='', verification: str=''):
    session = auth(request)
    where,args = filters(q,country,verification)
    data = rows('SELECT * FROM carrier_companies'+where+' ORDER BY company_name,id',tuple(args))
    keys = ['id','entity_type']+records.COLUMNS+['contact_consent']
    for item in data: item['entity_type']='carrier_company'
    if session['role']=='admin': keys += ['quote_notes','consent_evidence','consent_date']
    return Response(records.csv_text(keys,data), media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="carrier-companies.csv"'})


@router.get('/carriers/new',response_class=HTMLResponse)
def new(request: Request):
    session=auth(request,admin=True)
    return HTMLResponse(page('إضافة شركة نقل',nav()+'<h1>إضافة شركة نقل</h1><div class="card"><form method="post" action="/carriers/new">'+company_form(session)+'<button class="btn">حفظ الشركة</button></form></div>'))


@router.post('/carriers/new')
async def create(request: Request):
    session=auth(request,admin=True); form=await request.form(); csrf(session,form)
    record,errors=records.normalize_record(form)
    if errors: raise HTTPException(400,'؛ '.join(errors))
    with db() as connection:
        connection.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK_KEY,))
        collision=conflict(connection,record)
        if collision=='duplicate': raise HTTPException(409,'Company already exists; review its existing record')
        if collision=='shared_contact' and form.get('confirm_shared_contact')!='yes': raise HTTPException(409,'Shared contact: review and explicitly confirm separate company; no records merged')
        carrier_id=insert_company(connection,record,session['user_id'])
    log(session['user_id'],'create','carrier_company',carrier_id,'Separate company record; no outreach enrollment')
    return RedirectResponse('/carriers/'+str(carrier_id),303)


@router.get('/carriers/import',response_class=HTMLResponse)
def import_home(request: Request):
    session=auth(request,admin=True)
    return HTMLResponse(page('استيراد شركات النقل',nav()+'<h1>استيراد شركات النقل فقط</h1><div class="card"><p>المعاينة قبل الحفظ. لا تُضاف هذه الشركات إلى السائقين أو التسويق. أي موافقة تواصل في الملف لا تُعتمد تلقائيًا.</p><a href="/carriers/template.csv">تحميل القالب</a><form method="post" action="/carriers/import/preview" enctype="multipart/form-data"><input type="hidden" name="csrf" value="'+esc(session['csrf'])+'"><input type="file" name="file" accept=".csv,.xlsx" required><button class="btn">معاينة</button></form></div>'))


@router.get('/carriers/template.csv')
def template(request: Request):
    auth(request,admin=True)
    return Response(records.csv_text(records.COLUMNS,[]),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="carrier-companies-template.csv"'})


@router.post('/carriers/import/preview',response_class=HTMLResponse)
async def preview(request: Request):
    session=auth(request,admin=True); form=await request.form(); csrf(session,form)
    upload=form.get('file')
    if not upload or not hasattr(upload,'read'): raise HTTPException(400,'Choose a CSV or XLSX file')
    raw=await upload.read(MAX_FILE_BYTES+1)
    if len(raw)>MAX_FILE_BYTES: raise HTTPException(400,'Maximum file size is 2 MB')
    try: items=records.prepare_matrix(records.read_upload(upload.filename or '',raw))
    except Exception as exc: raise HTTPException(400,str(exc))
    with db() as connection:
        existing={item['row']:conflict(connection,item['data']) for item in items if not item['validation_errors']}
        records.review_candidates(items,existing)
        batch_id=str(uuid.uuid4())
        connection.execute('INSERT INTO carrier_import_batches(id,user_id,file_name,rows_json,created_at) VALUES(%s,%s,%s,%s,%s)',(batch_id,session['user_id'],upload.filename or '',json.dumps(items,ensure_ascii=False),utcnow()))
    valid=sum(not item['errors'] and not item['duplicate'] for item in items)
    table=''.join('<tr><td>'+str(item['row'])+'</td><td>'+esc(item['data']['company_name'])+'</td><td>'+esc('؛ '.join(item['errors']) if item['errors'] else 'مكرر؛ لن يحفظ' if item['duplicate'] else 'جاهز')+'</td></tr>' for item in items[:200])
    return HTMLResponse(page('معاينة شركات النقل',nav()+'<h1>معاينة شركات النقل</h1><p>جاهز: '+str(valid)+' من '+str(len(items))+'. تظهر أول 200 نتيجة. أرقام السائقين المشابهة لا تُدمج ولا تربط تلقائيًا.</p><div class="card scroll"><table><tr><th>الصف</th><th>الشركة</th><th>الحالة</th></tr>'+table+'</table></div><form method="post" action="/carriers/import/'+batch_id+'/commit"><input type="hidden" name="csrf" value="'+esc(session['csrf'])+'"><button class="btn"'+(' disabled' if not valid else '')+'>اعتماد حفظ الشركات الجاهزة</button></form><p><a href="/carriers/import">إلغاء والعودة</a></p>'))


@router.post('/carriers/import/{batch_id}/commit',response_class=HTMLResponse)
async def commit(batch_id: str,request: Request):
    session=auth(request,admin=True); form=await request.form(); csrf(session,form)
    with db() as connection:
        connection.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK_KEY,))
        batch=connection.execute('SELECT * FROM carrier_import_batches WHERE id=%s AND user_id=%s FOR UPDATE',(batch_id,session['user_id'])).fetchone()
        if not batch: raise HTTPException(404,'Import preview not found')
        if batch['status']=='committed':
            inserted,skipped=batch['inserted_count'],batch['skipped_count']
        else:
            inserted=skipped=0
            for item in json.loads(batch['rows_json']):
                record,errors=records.normalize_record(item['data'])
                if errors or item['errors'] or item['duplicate'] or conflict(connection,record): skipped+=1; continue
                insert_company(connection,record,session['user_id']); inserted+=1
            connection.execute("UPDATE carrier_import_batches SET status='committed',inserted_count=%s,skipped_count=%s,committed_at=%s WHERE id=%s",(inserted,skipped,utcnow(),batch_id))
            connection.execute('INSERT INTO activity(user_id,action,entity_type,summary,created_at) VALUES(%s,%s,%s,%s,%s)',(session['user_id'],'carrier_import','carrier_company',f'Imported {inserted}; skipped {skipped}; batch {batch_id}; no outreach enrollment',utcnow()))
    return HTMLResponse(page('نتيجة استيراد شركات النقل',nav()+'<h1>تم حفظ '+str(inserted)+' شركة</h1><p>تُرك '+str(skipped)+' سجلًا للتكرار أو المراجعة. إعادة الاعتماد لا تكرر الاستيراد. لم تُضف أي جهة إلى السائقين أو قوائم الإرسال.</p><a class="btn" href="/carriers">كشف الشركات</a>'))


@router.get('/api/v7/carriers')
def api(request: Request,q: str='',country: str='',verification: str='',limit: int=200):
    session=auth(request);where,args=filters(q,country,verification)
    return [visible_record(item,session) for item in rows('SELECT * FROM carrier_companies'+where+' ORDER BY company_name,id LIMIT %s',tuple(args+[min(500,max(1,limit))]))]


@router.get('/carriers/{carrier_id}',response_class=HTMLResponse)
def detail(carrier_id: int,request: Request):
    session=auth(request);record=one('SELECT * FROM carrier_companies WHERE id=%s',(carrier_id,))
    if not record: raise HTTPException(404,'Company not found')
    body=nav()+'<h1>'+esc(record['company_name'])+'</h1><p>نوع السجل: شركة نقل / جهة نقل محتملة</p>'
    if session['role']=='admin':
        body+='<div class="card"><form method="post" action="/carriers/'+str(carrier_id)+'/edit">'+company_form(session,record)+'<label>ملاحظات عروض الأسعار للإدارة فقط<textarea name="quote_notes">'+esc(record['quote_notes'])+'</textarea></label><h2>توثيق موافقة التواصل</h2><select name="contact_consent">'+options({'unknown':'غير معروفة','granted':'موافقة موثقة','declined':'رفض التواصل'},record['contact_consent'])+'</select><label>دليل الموافقة<textarea name="consent_evidence">'+esc(record['consent_evidence'])+'</textarea></label><label>تاريخ الموافقة<input type="date" name="consent_date" value="'+esc(record['consent_date'])+'"></label><p class="muted">تسجيل الدليل لا ينشئ حملة أو رسالة ولا يغيّر صلاحيات الإرسال.</p><button class="btn">حفظ التعديلات</button></form></div>'
    else:
        body+='<div class="card"><dl>'+''.join('<dt>'+esc(records.LABELS[key])+'</dt><dd>'+esc(record[key])+'</dd>' for key in records.COLUMNS)+'</dl></div>'
    linked=rows('SELECT id,driver_name,record_type FROM drivers WHERE carrier_company_id=%s ORDER BY id',(carrier_id,))
    body+='<div class="card"><h2>السجلات المرتبطة يدويًا</h2>'+(''.join('<p><a href="/drivers/'+str(item['id'])+'/edit">'+esc(item['driver_name'])+'</a> · '+esc(records.DRIVER_TYPES.get(item['record_type'],'غير مصنف'))+'</p>' for item in linked) or '<p>لا توجد روابط مؤكدة. تشابه الهاتف لا ينشئ رابطًا.</p>')+'</div>'
    return HTMLResponse(page(record['company_name'],body))


@router.post('/carriers/{carrier_id}/edit')
async def update(carrier_id: int,request: Request):
    session=auth(request,admin=True);form=await request.form();csrf(session,form)
    record,errors=records.normalize_record(form)
    consent=str(form.get('contact_consent') or 'unknown');evidence=str(form.get('consent_evidence') or '').strip();consent_date=str(form.get('consent_date') or '')
    if consent not in ('unknown','granted','declined'): errors.append('موافقة التواصل غير صالحة')
    if consent=='granted' and (not evidence or not consent_date): errors.append('الموافقة تحتاج دليلًا وتاريخًا صريحين')
    if consent_date:
        from datetime import date
        try:
            if date.fromisoformat(consent_date)>date.today(): errors.append('تاريخ الموافقة مستقبلي')
        except ValueError: errors.append('تاريخ الموافقة غير صالح')
    if len(evidence)>4000 or len(str(form.get('quote_notes') or ''))>4000: errors.append('الملاحظات طويلة جدًا')
    if errors: raise HTTPException(400,'؛ '.join(errors))
    with db() as connection:
        connection.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK_KEY,))
        if not connection.execute('SELECT id FROM carrier_companies WHERE id=%s FOR UPDATE',(carrier_id,)).fetchone(): raise HTTPException(404,'Company not found')
        collision=conflict(connection,record,carrier_id)
        if collision=='duplicate' or (collision=='shared_contact' and form.get('confirm_shared_contact')!='yes'): raise HTTPException(409,'Duplicate/shared contact needs review; no records merged')
        keys=records.COLUMNS+['normalized_name','website_domain']
        values=[record[key] or None if key=='verified_on' else record[key] for key in keys]
        connection.execute('UPDATE carrier_companies SET '+','.join(key+'=%s' for key in keys)+',quote_notes=%s,contact_consent=%s,consent_evidence=%s,consent_date=%s,updated_at=%s WHERE id=%s',tuple(values+[str(form.get('quote_notes') or '').strip(),consent,evidence,consent_date or None,utcnow(),carrier_id]))
    log(session['user_id'],'update','carrier_company',carrier_id,'Company information/explicit consent evidence updated; no external action')
    return RedirectResponse('/carriers/'+str(carrier_id),303)
