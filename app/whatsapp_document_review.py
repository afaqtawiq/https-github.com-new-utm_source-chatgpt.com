"""Explicit, scoped review of exact PDF excerpts; never sends or replays a job."""
from hashlib import sha256
from html import escape
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from app import whatsapp_agent as agent
from app import whatsapp_agent_store as store
from app import whatsapp_agent_privacy as privacy
from app import whatsapp_inbox as inbox
from app import zernio_whatsapp as z

router = APIRouter()
PURPOSE = 'الإجابة عن أسئلة لاحقة في هذه المحادثة فقط باستخدام النص المراجع، عبر Anthropic الموجود في آفاق.'


def page(body, status=200):
    response = inbox.page(body, status)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


async def review_form(request, actor):
    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Form required')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 180000:
            raise HTTPException(413, 'Review form too large')
    try:
        values = parse_qs(bytes(body).decode('utf-8'), keep_blank_values=True, max_num_fields=12)
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'Invalid review form') from None
    if any(len(v) != 1 for v in values.values()):
        raise HTTPException(400, 'Duplicate review field')
    result = {k:v[0] for k,v in values.items()}
    if result.get('csrf') != actor['csrf']:
        raise HTTPException(403, 'CSRF required')
    return result


async def source_scope(job_id, request, actor, account):
    job = await run_in_threadpool(store.get_job, job_id)
    settings = await run_in_threadpool(store.get_settings, account)
    agent.read_scope(request, actor, account)
    if (not job or job['account_id'] != account or settings['mode'] != 'routine'
            or job['authorization_generation'] != settings['authorization_generation']
            or not store._pdf_payload(job['payload'])
            or not job.get('document_sha256')
            or job.get('document_status') not in ('ok', 'quarantined')
            or not store._review_source_valid(job, settings, None)):
        raise HTTPException(409, 'Current scoped PDF review required')
    return job, settings


async def extracted_source(job, request, actor, account):
    content = await agent.fetch_document(job)
    if sha256(content).hexdigest() != job['document_sha256']:
        raise HTTPException(409, 'Document bytes changed')
    try:
        pages, notes = await run_in_threadpool(inbox.extract_pdf_locally, content)
    except ValueError:
        raise HTTPException(422, 'Local PDF extraction failed') from None
    agent.read_scope(request, actor, account)
    if (notes or not pages or any(p.get('method') != 'نص PDF' or not p.get('text', '').strip() for p in pages)):
        raise HTTPException(422, 'OCR or uncertain extraction requires separate local review')
    normalized = privacy._text('\n\n'.join(p['text'] for p in pages), privacy.MAX_DOCUMENT_CHARS)
    if normalized is None:
        raise HTTPException(422, 'Document text cannot be reviewed in this bounded path')
    return normalized


def exact_excerpts(selected, original):
    """Only whole original lines, in order; no manager-added source assertions."""
    text = privacy._text(selected, privacy.MAX_DOCUMENT_CHARS)
    if not text:
        raise HTTPException(422, 'Select nonempty bounded excerpts')
    original_lines = iter(line.strip() for line in original.splitlines() if line.strip())
    for line in (line.strip() for line in text.splitlines() if line.strip()):
        if not any(candidate == line for candidate in original_lines):
            raise HTTPException(422, 'Use only original whole-line excerpts in their original order')
    return text


@router.get('/whatsapp-assistant/jobs/{job_id}/review')
async def review_source(job_id: int, request: Request):
    actor, account = dict(z.session(request)), z.account_id()
    job, settings = await source_scope(job_id, request, actor, account)
    original = await extracted_source(job, request, actor, account)
    body = '<h2>مراجعة محلية للمستند</h2><p>هذه المعاينة المحلية لا ترسل النص إلى نموذج خارجي.</p>'
    body += '<p>المحادثة: +' + escape(job['sender']) + ' · ' + escape(job['conversation_id']) + '</p>'
    body += '<p>بصمة الأصل: ' + escape(job['document_sha256']) + '</p><pre>' + escape(original) + '</pre>'
    body += '<p>اختر سطورًا تشغيلية غير حساسة من النص أعلاه، بترتيبها الأصلي. احذف السطور غير اللازمة كاملة؛ لا تضف معلومات. لا تعتمد أسرارًا أو بيانات بنكية أو بطاقات أو معلومات صحية أو معلومات قاصرين. إذا لم تستطع فصلها بثقة، أبق المستند للمراجعة المحلية.</p>'
    body += '<form method="post"><input type="hidden" name="csrf" value="' + escape(actor['csrf']) + '">' + agent.scope_fields(settings)
    body += '<label>النص المختار للمراجعة<textarea name="text" maxlength="24000" rows="12" required></textarea></label>'
    body += '<p>' + PURPOSE + '</p><button>معاينة النص المحدد قبل الاعتماد</button></form>'
    return page(body)


@router.post('/whatsapp-assistant/jobs/{job_id}/review')
async def stage_review(job_id: int, request: Request):
    actor, account = dict(z.session(request)), z.account_id()
    form = await review_form(request, actor)
    if set(form) != {'csrf','account_id','generation','text'}:
        raise HTTPException(400, 'Unexpected review fields')
    job, settings = await source_scope(job_id, request, actor, account)
    if form['account_id'] != account or form['generation'] != str(settings['authorization_generation']):
        raise HTTPException(409, 'Review scope changed')
    original = await extracted_source(job, request, actor, account)
    text = exact_excerpts(form['text'], original)
    decision = privacy.screen_reviewed_document(text, job['document_sha256'], [job['document_sha256']])
    if not decision.allowed or decision.safe_text != text:
        raise HTTPException(422, 'Selected text requires further local privacy review')
    await source_scope(job_id, request, actor, account)
    try:
        reviewed = await run_in_threadpool(store.stage_document_review, job_id, str(actor['user_id']), text,
            expected_account=account, expected_generation=settings['authorization_generation'],
            verified_source_sha256=job['document_sha256'], extraction_sha256=sha256(original.encode()).hexdigest())
    except (ValueError, store.StateConflict):
        raise HTTPException(409, 'Review could not be staged under current scope') from None
    return RedirectResponse('/whatsapp-assistant/reviews/' + reviewed['review_id'], 303)


async def owned_review(token, request, actor, account):
    reviewed = await run_in_threadpool(store.get_document_review, token, str(actor['user_id']))
    agent.read_scope(request, actor, account)
    if not reviewed or reviewed['account_id'] != account:
        raise HTTPException(404)
    return reviewed


@router.get('/whatsapp-assistant/reviews/{token}')
async def preview_review(token: str, request: Request):
    actor, account = dict(z.session(request)), z.account_id()
    reviewed = await owned_review(token, request, actor, account)
    body = '<h2>النص المحدد للمشاركة مع Anthropic</h2><p>' + PURPOSE + '</p>'
    body += '<p>المستلم في المحادثة: +' + escape(reviewed['sender']) + ' · ' + escape(reviewed['conversation_id']) + '</p>'
    body += '<p>الرسالة: ' + escape(reviewed['message_id']) + ' · بصمة الأصل: ' + escape(reviewed['source_sha256']) + '</p>'
    body += '<p>بصمة النص: ' + escape(reviewed['text_sha256']) + ' · ينتهي: ' + escape(str(reviewed['expires_at'])) + '</p>'
    body += '<p>الحالة: ' + escape(reviewed['status']) + '</p><pre>' + escape(reviewed.get('text') or '') + '</pre>'
    body += '<p>الاعتماد يخص هذا النص وهذه المحادثة فقط، ولا يرسل جوابًا الآن أو يعيد رسالة قديمة أو يعتمد حركة مالية. تستخدم الأسئلة اللاحقة النص خلال مدة الاعتماد. يمكن إعادة مبلغ واضح مقرون بتسميته وعملته من المقتطف بوصفه معلومة واردة فيه فقط؛ الغموض أو استنتاج السداد أو اعتماد الأسعار يحتاج مراجعة بشرية. اعتماد نسخة جديدة يلغي النسخة السابقة لهذا المستند. يمكن إلغاء الاعتماد؛ الإلغاء لا يسترجع محتوى سبق إرساله للنموذج قبل الإلغاء.</p>'
    target = '/whatsapp-assistant/reviews/' + token
    body += '<a href="/mfa/step-up?' + escape(urlencode({'next':target})) + '">التحقق الإضافي قبل الاعتماد أو الإلغاء</a>'
    if reviewed['status'] in ('staged','approved'):
        body += '<form method="post" action="' + escape(target) + '/' + ('approve' if reviewed['status']=='staged' else 'revoke') + '">'
        for name, value in {'csrf':actor['csrf'],'account_id':account,'generation':reviewed['authorization_generation'],
                            'source_sha256':reviewed['source_sha256'],'text_sha256':reviewed['text_sha256']}.items():
            body += '<input type="hidden" name="' + name + '" value="' + escape(str(value)) + '">'
        if reviewed['status']=='staged':
            body += '<label><input type="checkbox" name="confirm" value="yes" required>راجعت النص أعلاه، وهو غير حساس وأوافق على مشاركته مع Anthropic لهذا الغرض وهذه المحادثة فقط.</label><button>اعتماد هذا النص فقط</button>'
        else:
            body += '<button>إلغاء اعتماد هذا النص</button>'
        body += '</form>'
    return page(body)


async def change_review(token, request, *, approve):
    actor, account = dict(inbox.send_authority(request)), z.account_id()
    form = await review_form(request, actor)
    expected = {'csrf','account_id','generation','source_sha256','text_sha256'} | ({'confirm'} if approve else set())
    if set(form) != expected:
        raise HTTPException(400, 'Unexpected review fields')
    generation = agent.mutation_scope(request, actor, form, account)
    reviewed = await owned_review(token, request, actor, account)
    if (form.get('source_sha256') != reviewed['source_sha256'] or
            form.get('text_sha256') != reviewed['text_sha256'] or
            (approve and form.get('confirm') != 'yes')):
        raise HTTPException(409, 'Exact review confirmation required')
    try:
        if approve:
            await run_in_threadpool(store.approve_document_review, token, str(actor['user_id']),
                expected_account=account, expected_generation=generation,
                expected_text_sha256=reviewed['text_sha256'], expected_source_sha256=reviewed['source_sha256'])
        else:
            await run_in_threadpool(store.revoke_document_review, token, str(actor['user_id']),
                expected_account=account, expected_generation=generation)
    except (ValueError, store.StateConflict):
        raise HTTPException(409, 'Review changed or expired') from None
    return RedirectResponse('/whatsapp-assistant/reviews/' + token, 303)


@router.post('/whatsapp-assistant/reviews/{token}/approve')
async def approve_review(token: str, request: Request):
    return await change_review(token, request, approve=True)


@router.post('/whatsapp-assistant/reviews/{token}/revoke')
async def revoke_review(token: str, request: Request):
    return await change_review(token, request, approve=False)
