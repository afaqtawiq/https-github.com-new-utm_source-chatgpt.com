"""Authenticated finance workspace; deliberate manual controls, no external actions."""
import secrets
from urllib.parse import parse_qs
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from app.storage import get_session, one
from app.fine_permissions import has_permission
from app import finance_core as core, finance_service as service, finance_view as view
from app import finance_claim_view as claim_view

router = APIRouter()


def auth(request, *, permission='view_finance'):
    session = get_session(request.cookies.get('gla_session'))
    if not session:
        raise HTTPException(401, 'Login required')
    allowed = ('admin',) if permission == 'approve_finance' else ('admin','finance')
    if session.get('role') not in allowed or not has_permission(session, permission):
        raise HTTPException(403, 'صلاحية المالية غير متاحة لهذا الإجراء')
    active = one('SELECT is_active,must_change_password FROM users WHERE id=%s', (session['user_id'],))
    if not active or not active['is_active'] or active['must_change_password']:
        raise HTTPException(403, 'يلزم حساب نشط مكتمل الإعداد')
    session = dict(session)
    session['can_view_profit'] = has_permission(session, 'view_profit')
    session['can_edit_finance'] = has_permission(session, 'edit_finance')
    session['can_approve_finance'] = session['role']=='admin' and has_permission(session, 'approve_finance')
    return session


async def mutation(request, permission='edit_finance'):
    session = auth(request, permission=permission)
    if not request.headers.get('content-type', '').lower().startswith('application/x-www-form-urlencoded'):
        raise HTTPException(415, 'استخدم نموذج المالية دون مرفقات')
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 24000:
            raise HTTPException(413, 'الطلب أكبر من الحد المسموح')
        chunks.append(chunk)
    try:
        fields = parse_qs(b''.join(chunks).decode('utf-8'), keep_blank_values=True, max_num_fields=40)
        if any(len(values) != 1 for values in fields.values()):
            raise ValueError('Duplicate fields')
        form = {key:values[0] for key,values in fields.items()}
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'حقول النموذج غير صالحة أو مكررة')
    if not form.get('csrf') or not secrets.compare_digest(form['csrf'].encode('utf-8'), str(session.get('csrf') or '').encode('utf-8')):
        raise HTTPException(403, 'Invalid CSRF token')
    return session, form


def invoke(function, *args):
    try:
        return function(*args)
    except (ValueError, ArithmeticError) as error:
        raise HTTPException(400, str(error)) from error


@router.get('/finance', response_class=HTMLResponse)
def dashboard(request: Request):
    session = auth(request)
    data=list(service.dashboard_data())
    if not session['can_view_profit']:data[3]=[a for a in data[3] if not a['action'].startswith('closing_')]
    return HTMLResponse(view.render_dashboard(session, *data), headers={'Cache-Control':'no-store'})


@router.get('/finance/documents/{doc_id}', response_class=HTMLResponse)
def detail(doc_id: int, request: Request):
    session = auth(request)
    data=list(service.detail_data(doc_id))
    if not session['can_view_profit']:data[2]=[a for a in data[2] if not a['action'].startswith('closing_')]
    return HTMLResponse(view.render_document(session, *data), headers={'Cache-Control':'no-store'})


@router.get('/finance/documents/{doc_id}/claim', response_class=HTMLResponse)
def customer_claim(doc_id: int, request: Request):
    auth(request)
    return HTMLResponse(claim_view.render_customer_claim(*service.customer_claim_data(doc_id)),
                        headers={'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow','Referrer-Policy':'no-referrer'})


@router.get('/finance/documents/{doc_id}/claim.pdf')
def customer_claim_pdf(doc_id: int, request: Request):
    auth(request)
    from app.finance_claim_pdf import render_pdf
    content = invoke(render_pdf, *service.customer_claim_data(doc_id))
    return Response(content, media_type='application/pdf', headers={
        'Content-Disposition':'attachment; filename="claim-'+str(doc_id)+'.pdf"',
        'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow','Referrer-Policy':'no-referrer'})


@router.post('/finance/documents/{doc_id}/claim-details')
async def claim_details(doc_id: int, request: Request):
    session, form = await mutation(request, 'approve_finance')
    invoke(service.attach_claim_details, doc_id, session['user_id'], form)
    return RedirectResponse('/finance/documents/'+str(doc_id)+'#claim-details',303)


@router.get('/finance/statement', response_class=HTMLResponse)
def statement(request: Request, owner_id: int, counterparty_id: int, currency: str, side: str='receivable'):
    session = auth(request)
    owner, party, entries, balance = invoke(service.statement_data, owner_id, counterparty_id, currency, side)
    return HTMLResponse(view.render_statement(session, owner, party, currency.upper(), entries, balance, side=side), headers={'Cache-Control':'no-store'})


@router.get('/finance/statement.csv')
def statement_csv(request: Request, owner_id: int, counterparty_id: int, currency: str, side: str='receivable'):
    auth(request)
    owner, party, entries, balance = invoke(service.statement_data, owner_id, counterparty_id, currency, side)
    headers = ['owner','counterparty','currency','side','document_id','document_date','recorded_at','kind','phase','source_ref','source_locator','economic_ref','invoice_ref','customs_ref','source_amount_raw','amount_basis','debit','credit','balance','opening_cutoff','opening_confirmation_ref']
    data = [[owner['name'],party['name'],currency.upper(),side,e['id'],e['document_date'],e['created_at'],e['kind'],e['phase'],e['source_ref'],e['source_locator'],e['economic_ref'],e['invoice_ref'],e['customs_ref'],e['source_amount_raw'],e['amount_basis'],e['debit_display'],e['credit_display'],e['running_display'],e['opening_cutoff'],e['opening_confirmation_ref']] for e in entries]
    return Response(core.csv_bytes(headers,data), media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="finance-statement.csv"','Cache-Control':'no-store'})


@router.get('/api/v7/finance')
def api(request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    auth(request)
    parties, documents, summary, audit, rules, totals = service.dashboard_data()
    # All monetary values returned as decimal strings / integer units, never binary floats.
    return {'parties':parties,'documents':documents,'balances':[dict(x,receivable_minor=str(x['receivable_minor']),payable_minor=str(x['payable_minor'])) for x in summary],
            'totals':[dict(x, **{name+'_minor':str(x[name+'_minor']) for name in ('receivable','payable','net')}) for x in totals],
            'rules':[dict(x,rate=str(x['rate'])) for x in rules], 'scope':'operational_subledger', 'external_actions':False}


@router.post('/finance/parties')
async def create_party(request: Request):
    session, form = await mutation(request, 'approve_finance')
    invoke(service.create_party, form, session['user_id'])
    return RedirectResponse('/finance',303)


@router.post('/finance/documents')
async def create_document(request: Request):
    session, form = await mutation(request)
    doc_id = invoke(service.create_document, form, session['user_id'])
    return RedirectResponse('/finance/documents/'+str(doc_id),303)


@router.post('/finance/owners/{owner_id}/display-name')
async def rename_owner(owner_id: int, request: Request):
    session, form = await mutation(request, 'approve_finance')
    invoke(service.rename_owner, owner_id, session['user_id'], form)
    return RedirectResponse('/finance#parties',303)


@router.post('/finance/documents/{doc_id}/review')
async def review(doc_id: int, request: Request):
    session, form = await mutation(request)
    invoke(service.review_document, doc_id, session['user_id'], form)
    return RedirectResponse('/finance/documents/'+str(doc_id),303)


@router.post('/finance/documents/{doc_id}/post')
async def post(doc_id: int, request: Request):
    session, form = await mutation(request, 'approve_finance')
    invoke(service.post_document, doc_id, session['user_id'], form)
    return RedirectResponse('/finance/documents/'+str(doc_id),303)


@router.post('/finance/documents/{doc_id}/reverse')
async def reverse(doc_id: int, request: Request):
    session, form = await mutation(request, 'approve_finance')
    invoke(service.reverse_document, doc_id, session['user_id'], form)
    return RedirectResponse('/finance/documents/'+str(doc_id),303)


@router.post('/finance/documents/{doc_id}/void')
async def void(doc_id: int, request: Request):
    session, form = await mutation(request, 'approve_finance')
    invoke(service.void_document, doc_id, session['user_id'], form)
    return RedirectResponse('/finance/documents/'+str(doc_id),303)


@router.post('/finance/allocations')
async def allocation(request: Request):
    session, form = await mutation(request, 'approve_finance')
    invoke(service.create_allocation, form, session['user_id'])
    return RedirectResponse('/finance/documents/'+str(int(form['credit_id'])),303)


@router.post('/finance/rules')
async def rule(request: Request):
    session, form = await mutation(request, 'approve_finance')
    invoke(service.create_rule, form, session['user_id'])
    return RedirectResponse('/finance',303)


@router.get('/finance/monthly-statement', response_class=HTMLResponse)
def monthly_statement(request: Request, owner_id: int, counterparty_id: int, currency: str, start: str, end: str):
    session=auth(request)
    from app import finance_monthly_service, finance_monthly_view
    report=invoke(finance_monthly_service.statement_data,owner_id,counterparty_id,currency,start,end)
    return HTMLResponse(finance_monthly_view.render_statement(session,report),headers={'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow','Referrer-Policy':'no-referrer'})


@router.get('/finance/monthly-statement.pdf')
def monthly_statement_pdf(request: Request, owner_id: int, counterparty_id: int, currency: str, start: str, end: str):
    auth(request)
    from app import finance_monthly_service, finance_monthly_pdf
    report=invoke(finance_monthly_service.statement_data,owner_id,counterparty_id,currency,start,end)
    return Response(invoke(finance_monthly_pdf.render_statement,report),media_type='application/pdf',headers={
        'Content-Disposition':'attachment; filename="monthly-statement-'+report['start']+'-'+report['end']+'.pdf"',
        'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow','Referrer-Policy':'no-referrer'})


@router.get('/finance/monthly-closing', response_class=HTMLResponse)
def monthly_closing(request: Request, owner_id: int, month: str):
    session=auth(request)
    if not session['can_view_profit']:raise HTTPException(403,'صلاحية مشاهدة التكلفة والربحية مطلوبة')
    from app import finance_closing_service, finance_monthly_view
    report=invoke(finance_closing_service.report_data,owner_id,month)
    return HTMLResponse(finance_monthly_view.render_closing(session,report),headers={'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow','Referrer-Policy':'no-referrer'})


@router.get('/finance/monthly-closing.pdf')
def monthly_closing_pdf(request: Request, owner_id: int, month: str):
    session=auth(request)
    if not session['can_view_profit']:raise HTTPException(403,'صلاحية مشاهدة التكلفة والربحية مطلوبة')
    from app import finance_closing_service, finance_monthly_pdf
    report=invoke(finance_closing_service.report_data,owner_id,month)
    return Response(invoke(finance_monthly_pdf.render_closing,report),media_type='application/pdf',headers={
        'Content-Disposition':'attachment; filename="monthly-closing-'+report['month']+'.pdf"',
        'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow','Referrer-Policy':'no-referrer'})


@router.post('/finance/documents/{doc_id}/closing-input')
async def closing_input(doc_id: int, request: Request):
    session,form=await mutation(request,'approve_finance')
    if not session['can_view_profit']:raise HTTPException(403,'صلاحية مشاهدة التكلفة والربحية مطلوبة')
    if not has_permission(session,'view_finance'):raise HTTPException(403,'صلاحية عرض المالية مطلوبة')
    from app import finance_closing_service
    invoke(finance_closing_service.save_input,doc_id,session['user_id'],form)
    d=service.detail_data(doc_id)[0]
    return RedirectResponse('/finance/monthly-closing?owner_id='+str(d['owner_id'])+'&month='+str(d['document_date'])[:7],303)


@router.post('/finance/monthly-closing/{owner_id}/{month}/review')
async def closing_review(owner_id: int, month: str, request: Request):
    session,form=await mutation(request,'approve_finance')
    if not session['can_view_profit']:raise HTTPException(403,'صلاحية مشاهدة التكلفة والربحية مطلوبة')
    if not has_permission(session,'view_finance'):raise HTTPException(403,'صلاحية عرض المالية مطلوبة')
    from app import finance_closing_service
    invoke(finance_closing_service.save_review,owner_id,month,session['user_id'],form)
    return RedirectResponse('/finance/monthly-closing?owner_id='+str(owner_id)+'&month='+month,303)
