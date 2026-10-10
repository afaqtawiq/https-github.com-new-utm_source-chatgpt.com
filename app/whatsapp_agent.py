"""Durable, explicitly gated WhatsApp document pilot and routine reply lane.

Webhook intake only commits a job. Provider reads, local parsing, model work and
outbox dispatch happen after that transaction in a recoverable worker.
"""
import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
import logging
import re
import httpx
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from app import zernio_whatsapp as z
from app import whatsapp_inbox as inbox
from app import whatsapp_agent_store as store
from app import whatsapp_agent_privacy as privacy

router = APIRouter()
logger = logging.getLogger(__name__)


def identity(payload):
    if not isinstance(payload, dict) or payload.get('event') != 'message.received':
        return None
    metadata = payload.get('metadata') or {}
    if not isinstance(metadata, dict) or metadata.get('standby'):
        return None
    account, message, conversation = [payload.get(k) for k in ('account','message','conversation')]
    if not all(isinstance(x, dict) for x in (account, message, conversation)):
        return None
    sender = message.get('sender') or {}
    if not isinstance(sender, dict):
        return None
    number = z.phone(sender.get('phoneNumber'))
    account_id = account.get('accountId') or account.get('id')
    cid, mid, event = conversation.get('id'), message.get('platformMessageId') or message.get('id'), payload.get('id')
    if (account_id != z.account_id() or account.get('platform') != 'whatsapp'
            or message.get('direction') != 'incoming' or not number
            or conversation.get('isGroup') or message.get('isGroup')
            or z.phone(conversation.get('participantId')) != number
            or (sender.get('id') and z.phone(sender['id']) != number)
            or not all(isinstance(v,str) and 0 < len(v) <= 255 for v in (cid, mid, event))):
        return None
    return {'account_id':account_id,'sender':number,'conversation_id':cid,'message_id':mid,'event_id':event}


def enabled(settings, sender):
    return settings['mode'] == 'routine' or (settings['mode'] == 'owner_pilot' and settings['pilot_sender'] == sender)


def attachment_snapshot(item, index, account):
    """Allowlisted identity/shape only: never retain a signed/private URL."""
    item = item if isinstance(item, dict) else {}
    payload = item.get('payload')
    raw_id = payload.get('id') if isinstance(payload, dict) else None
    media_id = inbox.media_identifier(raw_id)
    url = item.get('url')
    kind = 'absent'
    if isinstance(url, str) and url:
        try:
            parsed = urlsplit(url)
            kind = 'relative' if not parsed.scheme and not parsed.netloc else 'absolute'
        except ValueError:
            kind = 'invalid'
        if not media_id:
            media_id = inbox.canonical_media_identifier(url, account)
            # Relative references are parsed only, never fetched. The resulting
            # request still uses the fixed Zernio binary endpoint and this account.
            if not media_id and kind == 'relative' and url.startswith('/api/v1/whatsapp/media/'):
                media_id = inbox.canonical_media_identifier('https://zernio.com' + url, account)
        if inbox.canonical_media_identifier(url, account):
            kind = 'canonical_proxy'
    classification = inbox.pdf_attachment_metadata(item)
    return {'index':index,**classification,'media_id':media_id,
            'shape':{'payload_present':isinstance(payload,dict),'payload_id_type':type(raw_id).__name__,
                     'url_kind':kind,'media_id_available':bool(media_id),
                     'attachment_kind':classification['kind'],'mime_status':classification['mime_status'],
                     'mime_key_present':'mimeType' in item,
                     'mime_value_type':type(item.get('mimeType')).__name__}}


def deterministic_staff_command(text):
    """Only legacy syntax known to complete locally, never its AI fallback."""
    from app.whatsapp_admin import normalize
    value = re.sub(r'^افاق(?: طويق)?\s*[:،-]?\s*', '', normalize(text)).strip()
    if value in {'اعرض السائقين','السائقين','السائقون','اعرض الشحنات','الشحنات','اعرض العملاء','العملاء'}:
        return True
    patterns = (
        r'حالة (?:الشحنة|شحنة) [A-Za-z0-9_-]{1,60}',
        r'(?:اضف|سجل) (?:السائق|سائق) .{1,100}? (?:ورقمه|رقمه|ورقم|رقم|جواله) \+?\d{10,15}(?: (?:ومركبته|مركبته) .{1,100})?',
        r'(?:اضف|سجل) شحنة مرجع [A-Za-z0-9_-]{1,60} من .{1,100}? (?:الى|إلى) .{1,100}',
    )
    return any(re.fullmatch(pattern,value) for pattern in patterns)


def claim_legacy_message(connection, payload):
    who = identity(payload)
    if not who:
        return True
    return store.claim_legacy(connection, **who)


def accept_inbound(payload):
    """Called after signature validation and receiver table initialization."""
    who = identity(payload)
    if not who:
        return None
    settings = store.get_settings(who['account_id'])
    # Once this lane owns a message, mode changes must never let a new webhook
    # alias fall through and receive a second reply from the legacy handler.
    with store.database() as c:
        c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (who['conversation_id'],))
        owned = c.execute('''SELECT id FROM whatsapp_agent_jobs WHERE account_id=%s
            AND (message_id=%s OR id IN (SELECT job_id FROM whatsapp_agent_events
                WHERE account_id=%s AND event_id=%s))''',
            (who['account_id'],who['message_id'],who['account_id'],who['event_id'])).fetchone()
        if owned:
            job = store.enqueue(c, **who, payload={})
            c.execute("INSERT INTO zernio_reply_events(event_id,conversation_id,state) VALUES(%s,%s,'agent_duplicate') ON CONFLICT DO NOTHING",
                      (who['event_id'],who['conversation_id']))
            return {'ok':True,'duplicate':True,'agent_queue':True,'job_id':job['id']}
    if not enabled(settings, who['sender']):
        return None
    message = payload['message']
    attachments = message.get('attachments') or []
    if not isinstance(attachments, list):
        attachments = []
    # Preserve existing independently authorized staff operational commands.
    # This lane never gains write privileges from a caption or document.
    if not attachments and settings['mode'] == 'routine':
        from app.team import identify
        _, member = identify(payload)
        if member and deterministic_staff_command(str(message.get('text') or '')):
            return {'legacy_local_only':True}
    snapshots = [attachment_snapshot(item, index, who['account_id']) for index,item in enumerate(attachments[:6])]
    decision = (privacy.screen_caption(str(message.get('text') or '')) if snapshots
                else privacy.screen_question(str(message.get('text') or '')))
    metadata = payload.get('metadata') or {}
    quoted = metadata.get('quotedMessage')
    quoted_id = quoted.get('platformMessageId') if isinstance(quoted,dict) else None
    # Only Zernio's stored platform ID is documented as matching our ledger.
    # The raw envelope quotedMessageId may identify another perspective.
    quoted_id = quoted_id if isinstance(quoted_id,str) and 0 < len(quoted_id) <= 255 else None
    quote_present = 'quotedMessageId' in metadata or 'quotedMessage' in metadata
    data = {'question':decision.safe_text if decision.allowed else '',
            'question_allowed':decision.allowed,'question_kind':decision.kind,
            'question_reason':decision.reason,'attachments':snapshots,
            'attachment_count':len(attachments),'quoted_reference_present':quote_present,
            'quoted_platform_message_id':quoted_id}
    with store.database() as c:
        c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (who['conversation_id'],))
        prior = c.execute('SELECT event_id FROM zernio_reply_events WHERE event_id=%s', (who['event_id'],)).fetchone()
        if prior:
            return {'ok':True,'duplicate':True,'agent_queue':True}
        job = store.enqueue(c, **who, payload=data)
        c.execute("INSERT INTO zernio_reply_events(event_id,conversation_id,state) VALUES(%s,%s,'agent_queued') ON CONFLICT DO NOTHING",
                  (who['event_id'],who['conversation_id']))
    return {'ok':True,'queued':True,'job_id':job['id'],'automatic_retry_of_send':False}


async def fetch_document(job):
    data = job['payload']
    if data.get('attachment_count') != 1 or len(data.get('attachments', [])) != 1:
        raise inbox.PDFValidationError('metadata', 'count')
    attachment = data['attachments'][0]
    absent_candidate = (attachment.get('mime') == 'unknown' and attachment.get('kind') == 'file'
                        and attachment.get('mime_status') == 'absent')
    declared_pdf = (attachment.get('mime') == 'application/pdf'
                    and attachment.get('kind') in (None,'file','absent'))
    if not declared_pdf and not absent_candidate:
        raise inbox.PDFValidationError('metadata', 'mime')
    if job['account_id'] != z.account_id():
        raise HTTPException(409, 'Account changed')
    async with z.client() as c:
        await z.validate_account(c)
        media_id = attachment.get('media_id')
        if absent_candidate and not media_id:
            raise HTTPException(404,'Verified file media identifier is unavailable')
        if not media_id:
            observed = await inbox.verified_attachment(c,job['conversation_id'],job['message_id'],attachment['index'])
            media_id = await inbox.resolve_media_identifier(c,observed,job['conversation_id'],job['message_id'],attachment['index'],job['account_id'])
        content = await inbox.read_pdf(c,media_id,job['account_id'],require_structure=absent_candidate)
    if job['account_id'] != z.account_id():
        raise HTTPException(409, 'Account changed')
    return content


async def processing(job):
    jid, lease, data = job['id'], job['lease_token'], job['payload']
    settings = await run_in_threadpool(store.get_settings,job['account_id'])
    if job['account_id'] != z.account_id() or not enabled(settings,job['sender']):
        await run_in_threadpool(store.prepare_reply,jid,lease,terminal_status='blocked',diagnostics={'reason':'scope_changed'})
        return
    local_reason = None
    text, digest, source_id = '', None, None
    review_id = None
    model_hashes = settings['approved_sha256']
    conversation_history = ()
    conversation_scope = None
    if data.get('question_allowed') and data.get('question_kind') in ('operations','conversation','document_question'):
        conversation_scope = {key:job[key] for key in
                              ('account_id','sender','conversation_id','authorization_generation')}
        conversation_scope['before_job_id'] = jid
        conversation_history = await run_in_threadpool(store.recent_exchanges,
            account_id=job['account_id'],sender=job['sender'],conversation_id=job['conversation_id'],before_job_id=jid)
    if job.get('document_checkpointed_at'):
        text, digest, source_id = job.get('document_text') or '', job.get('document_sha256'), job.get('context_source_job_id')
        document_status = job.get('document_status')
        if job.get('review_id'):
            reviewed = await run_in_threadpool(store.find_review_context,
                account_id=job['account_id'],sender=job['sender'],conversation_id=job['conversation_id'],
                before_job_id=jid)
            if not reviewed or reviewed['review_id'] != job['review_id']:
                raise store.StateConflict('Reviewed document authorization changed')
            review_id, model_hashes = reviewed['review_id'], reviewed['approved_hashes']
    elif data.get('attachments'):
        try:
            content = await fetch_document(job)
            digest = sha256(content).hexdigest()
            if digest not in settings['approved_sha256']:
                document_status = 'quarantined'
                diagnostics = {'reason':'unapproved_document_provenance','byte_count':len(content)}
            else:
                pages, notes = await run_in_threadpool(inbox.extract_pdf_locally, content)
                extracted = '\n\n'.join('صفحة ' + str(p['page']) + '\n' + p['text'] for p in pages)
                decision = privacy.screen_document(extracted,digest,settings['approved_sha256'])
                uncertain = bool(notes) or any(p.get('method') != 'نص PDF' or not p.get('text','').strip() for p in pages)
                if uncertain or not decision.allowed:
                    document_status = 'quarantined'
                    diagnostics = {'reason':'extraction_uncertain' if uncertain else decision.reason,'pages':len(pages),'byte_count':len(content)}
                else:
                    document_status, text = 'ok', decision.safe_text
                    diagnostics = {'reason':'verified_local_read','pages':len(pages),'byte_count':len(content),
                                   'extracted_text_sha256':sha256(text.encode()).hexdigest()}
        except (z.WhatsAppBlocked,httpx.HTTPError,HTTPException,ValueError,TimeoutError) as error:
            document_status = 'unavailable'
            diagnostics = {'reason':'document_read_failed','error_type':type(error).__name__}
            if isinstance(error,HTTPException):
                diagnostics['http_status'] = error.status_code
            if isinstance(error,inbox.PDFValidationError) and (error.stage,error.reason) in {
                    ('metadata','count'),('metadata','mime'),('response','encoding'),
                    ('response','mime'),('response','signature'),('parser','invalid_pdf'),
                    ('parser','busy'),('parser','timeout'),('parser','unavailable')}:
                diagnostics.update(document_failure_stage=error.stage,document_failure_reason=error.reason)
            if isinstance(error,z.WhatsAppPreflightBlocked):
                diagnostics['provider_status'] = error.diagnostic.get('http_status')
        diagnostics['document_reason'] = diagnostics['reason']
        await run_in_threadpool(store.checkpoint_document,jid,lease,text=text,sha256=digest,status=document_status,diagnostics=diagnostics)
    else:
        context = None
        unread = None
        quote_unavailable = False
        if data.get('question_allowed') and privacy.wants_recent_document(data.get('question','')):
            quoted_id = data.get('quoted_platform_message_id')
            quoted = data.get('quoted_reference_present') is True
            lookup = {'message_id':quoted_id} if quoted and quoted_id else {}
            latest = (await run_in_threadpool(store.recent_attachment_outcome,
                account_id=job['account_id'],sender=job['sender'],conversation_id=job['conversation_id'],before_job_id=jid,**lookup)
                if not quoted or quoted_id else None)
            quote_unavailable = quoted and latest is None
            if latest and latest['document_status'] in ('unavailable','quarantined'):
                unread = latest
            context = (await run_in_threadpool(store.recent_context,account_id=job['account_id'],sender=job['sender'],
                                             conversation_id=job['conversation_id'],before_job_id=jid,**lookup)
                       if not quote_unavailable else None)
            reviewed = (await run_in_threadpool(store.find_review_context,
                account_id=job['account_id'],sender=job['sender'],conversation_id=job['conversation_id'],
                before_job_id=jid,**lookup) if not quote_unavailable else None)
            if reviewed and (not context or reviewed['id'] >= context['id']):
                context = reviewed
            if latest and (not context or latest['id'] > context['id']):
                context = None
                if latest['document_status'] == 'ok':
                    # A newer attachment is no longer eligible for reuse; never
                    # silently substitute an older approved document.
                    unread = {'id':latest['id'],'document_status':'quarantined'}
            if not quoted and privacy.implicit_document_detail(data.get('question','')):
                selected = context or unread
                newer = [entry for entry in conversation_history
                         if selected and entry['job_id'] > selected['id']]
                # A full newer text window cannot prove the earlier document
                # still owns the topic. Do not resurrect it when a topic-shift
                # marker has fallen outside the retained conversation window.
                if selected and (any(privacy.document_topic_shift(entry['question']) for entry in newer)
                        or (len(conversation_history) >= store.MAX_EXCHANGES
                            and len(newer) == len(conversation_history))):
                    context,unread = None,None
            if (not quoted and context and data.get('question_kind') == 'conversation' and conversation_history
                    and conversation_history[-1]['job_id'] > context['id']):
                context = None
            if (not quoted and unread and data.get('question_kind') == 'conversation' and conversation_history
                    and conversation_history[-1]['job_id'] > unread['id']):
                unread = None
        if context:
            text, digest, source_id = context['document_text'],context['document_sha256'],context['id']
            review_id = context.get('review_id')
            if review_id:
                model_hashes = context['approved_hashes']
        if unread and (not context or unread['id'] > context['id']):
            # Keep only the failed-read outcome, never failed document content.
            text,digest,source_id = '',None,None
            document_status = unread['document_status']
        elif quote_unavailable:
            document_status = 'reference_unavailable'
        else:
            document_status = 'ok' if text else 'none'
        await run_in_threadpool(store.checkpoint_document,jid,lease,text=text,sha256=digest,status=document_status,context_source_job_id=source_id,review_id=review_id,
            diagnostics={'document_context_reason':'prior_unread_attachment','unread_source_job_id':unread['id']} if unread and document_status in ('unavailable','quarantined') else {})
    if not data.get('question_allowed'):
        if data.get('question_reason') == 'broker_execution_request':
            reply = privacy.BROKER_EXECUTION_REPLY
        elif data.get('question_kind') == 'clarify_driver':
            reply = privacy.DRIVER_CLARIFY_REPLY
        elif data.get('question_kind') == 'clarify_action':
            reply = privacy.ACTION_CLARIFY_REPLY
        elif data.get('question_reason') == 'instruction_content':
            reply = 'وضّح السؤال الذي تريد الإجابة عنه؛ لا أنفّذ التعليمات الموجودة داخل المستندات.'
        elif data.get('question_kind') == 'clarify':
            reply = 'ما الذي تريد معرفته؟ أقدر أساعدك بسؤال عن المستند أو استفسار تشغيلي واضح.'
        else:
            reply = 'تحتاج هذه الرسالة مراجعة محلية قبل استخدامها في الفهم الآلي. اكتب السؤال دون أسرار أو بيانات بنكية.'
    elif document_status == 'reference_unavailable':
        reply = 'الرسالة المشار إليها لا تتيح لي ملفًا مقروءًا في هذه المحادثة. لم أستخدم مستندًا آخر بدلًا منها؛ يلزم إرفاق الملف نفسه لمراجعته.'
    elif document_status == 'quarantined':
        reply = 'وصل ملف PDF، وأوقفته للمراجعة المحلية قبل مشاركته مع نموذج الفهم. لم أعتمد محتواه أو أسجل منه أي حركة.'
    elif document_status == 'unavailable':
        reply = 'وصلتني بيانات المرفق، لكن لم أتمكن من قراءة محتواه في هذا المسار. لم أستنتج منه معلومات؛ يلزم مراجعته مباشرة.'
    elif not data.get('attachments') and not text and (service_reply := privacy.local_fasah_service_reply(
            data['question'], conversation_history, conversation_scope)):
        reply = service_reply
        local_reason = 'local_official_service'
    elif not data.get('attachments') and (identity_reply := privacy.local_identity_reply(data['question'])):
        reply = identity_reply
    elif not data.get('attachments') and data.get('question_kind') in ('greeting','thanks','ready'):
        reply = {'greeting':privacy.GREETING_REPLY,'thanks':privacy.THANKS_REPLY,
                 'ready':privacy.READY_REPLY}[data['question_kind']]
    elif not text and data.get('question_kind') not in ('operations','conversation','document_question'):
        reply = ('جاهزة للاختبار. أرسل ملف PDF التجريبي هنا، ثم اسألني عن محتواه.'
                 if settings['mode'] == 'owner_pilot' else 'أنا معك. أرسل المستند أو حدّد الاستفسار التشغيلي الذي تريد مراجعته.')
    else:
        if text:
            # The selected PDF is separately provenance-bound; older ordinary
            # chat must not obscure the document referent or enter by accident.
            conversation_history = ()
        if not await run_in_threadpool(store.reserve_model,jid,lease):
            return
        try:
            async def model_guard():
                allowed = await run_in_threadpool(store.model_authorized,jid,lease)
                if not allowed or z.account_id() != job['account_id']:
                    raise store.StateConflict('Model scope changed before request')
            result = await privacy.understand(data['question'],text,history=(),document_sha256=digest,
                                             approved_hashes=model_hashes,before_request=model_guard,reviewed_excerpt=bool(review_id),
                                             conversation_history=conversation_history,conversation_scope=conversation_scope)
            await run_in_threadpool(store.save_model,jid,lease,reply_text=result.text,
                                    diagnostics={'model_success':bool(result.ok and result.used_model),
                                                 'model_attempted':result.used_model,'model_reason':result.reason})
            await run_in_threadpool(store.prepare_reply,jid,lease)
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            await run_in_threadpool(store.prepare_reply,jid,lease,terminal_status='uncertain',diagnostics={'reason':'model_outcome_unknown'})
            return
    await run_in_threadpool(store.prepare_reply,jid,lease,reply_text=reply,
        diagnostics={'model_attempted':False,'model_success':False,'model_reason':'document_unread'}
        if document_status in ('unavailable','quarantined','reference_unavailable') else
        {'model_attempted':False,'model_success':False,'model_reason':local_reason} if local_reason else {})


async def dispatch(job):
    async def guard():
        if (z.account_id() != job['account_id'] or not await run_in_threadpool(store.send_authorized,job['id'],job['send_token'])):
            raise z.WhatsAppBlocked('Reply scope changed')
    state, mid, reason = 'uncertain', None, 'send_outcome_unknown'
    try:
        with z.dispatch_guard(guard):
            result = await z.send(job['sender'],job['reply_text'],expected_account=job['account_id'],
                                  expected_conversation=job['conversation_id'],idempotency_key=job['idempotency_key'])
        state, mid, reason = 'sent',result['messages'][0]['id'],'provider_accepted'
    except z.WhatsAppBlocked:
        state, reason = 'blocked','preflight_or_explicit_rejection'
    except asyncio.CancelledError:
        raise
    except Exception:
        pass
    await run_in_threadpool(store.finish_send,job['id'],job['send_token'],status=state,
                            provider_message_id=mid,diagnostics={'reason':reason})


async def tick():
    account = z.account_id()
    if not account:
        return False
    worked = False
    job = await run_in_threadpool(store.claim_job,account_id=account)
    if job:
        worked = True
        try:
            await processing(job)
        except store.StateConflict:
            pass
        except asyncio.CancelledError:
            raise
        except Exception:
            # The lease is durable. Recovery retries read-only phases and freezes
            # model/send ambiguity; never manufacture a send after a crash.
            logger.warning('WhatsApp agent job interrupted: job_id=%s',job['id'])
    outgoing = await run_in_threadpool(store.claim_send,account_id=account)
    if outgoing:
        worked = True
        await dispatch(outgoing)
    return worked


def register_worker(app):
    # Bootstrap already initializes the application's production schema. Keeping
    # this here also supports TestClient callers that do not run lifespan hooks.
    store.init_storage()
    from app import zernio_receiver
    zernio_receiver.durable_inbound = accept_inbound
    zernio_receiver.durable_legacy_claim = claim_legacy_message
    async def loop():
        while True:
            try:
                worked = await tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                worked = False
                logger.warning('WhatsApp agent worker unavailable')
            await asyncio.sleep(1 if worked else 5)
    @app.on_event('startup')
    async def start():
        app.state.whatsapp_document_agent = asyncio.create_task(loop())
    @app.on_event('shutdown')
    async def stop():
        task = getattr(app.state,'whatsapp_document_agent',None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def scope_fields(settings):
    return ('<input type="hidden" name="account_id" value="' + escape(settings['account_id'])
            + '"><input type="hidden" name="generation" value="' + str(settings['authorization_generation']) + '">')


def mutation_scope(request, current, form, account):
    latest = inbox.send_authority(request)
    if latest['user_id'] != current['user_id'] or z.account_id() != account or form.get('account_id') != account:
        raise HTTPException(409, 'Account or session changed')
    try:
        generation = int(form['generation'])
    except (ValueError,KeyError):
        raise HTTPException(400, 'Authorization generation required') from None
    return generation


def read_scope(request, current, account):
    if z.account_id() != account or z.session(request)['user_id'] != current['user_id']:
        raise HTTPException(409, 'Account or session changed')


@router.get('/whatsapp-assistant')
async def status_page(request: Request):
    current = z.session(request)
    account = z.account_id()
    settings = await run_in_threadpool(store.get_settings,account)
    jobs = await run_in_threadpool(store.list_jobs,account_id=account,limit=50)
    read_scope(request,current,account)
    body = '<h2>مساعد واتساب المستمر</h2><p>الوضع: ' + escape(settings['mode']) + '</p><p>الاختبار مخصص لرقم واحد موثق. لا تُمنح له صلاحية إدارية، ولا تُشارك المستندات غير المعتمدة مع النموذج. الحد اليومي لمحاولات النموذج: 10 للاختبار و50 للتشغيل المعتاد، دون شراء تلقائي.</p>'
    body += '<form method="post" action="/whatsapp-assistant/settings"><input type="hidden" name="csrf" value="' + escape(current['csrf']) + '">' + scope_fields(settings) + '<label>رقم المرسل التجريبي الدولي<input name="pilot_sender" value="' + escape(settings.get('pilot_sender') or '') + '" required></label><label>بصمة PDF التجريبي المراجع محليًا<input name="approved_sha256" value="' + escape(','.join(settings['approved_sha256'])) + '" required></label><input type="hidden" name="mode" value="owner_pilot"><label><input type="checkbox" name="confirm" value="yes" required>أوافق على الاختبار والرد على هذا الرقم فقط، والملف المطابق لهذه البصمة لا يتضمن أسرارًا أو بيانات بنكية.</label><button>تفعيل الاختبار المحدود</button></form>'
    body += '<form method="post" action="/whatsapp-assistant/settings"><input type="hidden" name="csrf" value="' + escape(current['csrf']) + '">' + scope_fields(settings) + '<input type="hidden" name="mode" value="off"><input type="hidden" name="confirm" value="yes"><button>إيقاف المسار الجديد</button></form>'
    body += '<p><a href="/mfa/step-up?next=/whatsapp-assistant">التحقق الإضافي قبل تغيير التشغيل</a></p>'
    for job in jobs:
        body += '<article><a href="/whatsapp-assistant/jobs/' + str(job['id']) + '">طلب ' + str(job['id']) + '</a> · ' + escape(job['status']) + ' · ' + escape(str(job['created_at'])) + '</article>'
    return inbox.page(body)


@router.post('/whatsapp-assistant/settings')
async def update_settings(request: Request):
    current = inbox.send_authority(request)
    account = z.account_id()
    form = await inbox.form(request,current)
    generation = mutation_scope(request,current,form,account)
    if form.get('confirm') != 'yes':
        raise HTTPException(400,'Explicit approval required')
    mode = form.get('mode')
    if mode not in ('off','owner_pilot'):
        raise HTTPException(400,'Routine activation requires completed pilot evidence')
    kwargs = {'mode':mode}
    if mode == 'owner_pilot':
        sender = z.phone(form.get('pilot_sender'))
        hashes = [item.strip().lower() for item in form.get('approved_sha256','').split(',') if item.strip()]
        if not sender or not hashes:
            raise HTTPException(400,'Pilot sender and reviewed file digest are required')
        kwargs.update(pilot_sender=sender,approved_sha256=hashes,acceptance={})
    try:
        await run_in_threadpool(store.update_settings,account,expected_generation=generation,**kwargs)
    except (ValueError,store.StateConflict):
        raise HTTPException(409,'Invalid or stale pilot settings') from None
    return RedirectResponse('/whatsapp-assistant',303)


@router.get('/whatsapp-assistant/jobs/{job_id}')
async def job_page(job_id: int, request: Request):
    current = z.session(request)
    account = z.account_id()
    job = await run_in_threadpool(store.get_job,job_id)
    if not job or job['account_id'] != z.account_id():
        raise HTTPException(404)
    outbox = await run_in_threadpool(store.get_outbox,job_id)
    settings = await run_in_threadpool(store.get_settings,account)
    read_scope(request,current,account)
    public = {k:job.get(k) for k in ('id','account_id','status','sender','conversation_id','message_id','event_id','read_attempts',
        'authorization_generation','document_sha256','document_status','context_source_job_id','review_id','model_started_at','model_completed_at','created_at','diagnostics')}
    public['quoted_reference_present'] = job['payload'].get('quoted_reference_present') is True
    public['quoted_stored_id_available'] = bool(job['payload'].get('quoted_platform_message_id'))
    public['attachment_count'] = job['payload'].get('attachment_count')
    public['attachment_mimes'] = [item.get('mime') if item.get('mime') in ('application/pdf','image/jpeg','image/png','audio/ogg','audio/mpeg','unknown','other') else 'other' for item in job['payload'].get('attachments',[])]
    public['attachment_shapes'] = [item.get('shape') for item in job['payload'].get('attachments',[])]
    public['provider_message_id'] = (outbox or {}).get('provider_message_id')
    body = '<h2>دليل المعالجة والرد</h2><pre>' + escape(json.dumps(public,ensure_ascii=False,indent=2,default=str)) + '</pre><p>sent تعني قبول المزود فقط؛ وصول الرد يؤكده المستلم أو دليل التسليم.</p>'
    if job.get('reply_text'):
        body += '<h3>الرد المحفوظ</h3><pre>' + escape(job['reply_text']) + '</pre>'
    if job.get('document_text'):
        body += '<h3>النص الذي قُرئ فعليًا</h3><pre>' + escape(job['document_text']) + '</pre>'
    if job['payload'].get('attachments'):
        body += '<a href="/whatsapp-assistant/jobs/' + str(job_id) + '/document">تنزيل المستند الأصلي للمراجعة المحلية</a>'
    if (settings['mode']=='routine' and job.get('document_sha256')
            and job['authorization_generation']==settings['authorization_generation']
            and job['payload'].get('attachments') and job['document_status'] in ('ok','quarantined')
            and store._review_source_valid(job, settings, None)):
        body += '<p><a href="/whatsapp-assistant/jobs/' + str(job_id) + '/review">مراجعة مقتطف محدد للمشاركة مع نموذج الفهم</a></p>'
    if (settings['mode']=='owner_pilot' and job['sender']==settings['pilot_sender']
            and job['authorization_generation']==settings['authorization_generation']
            and job['document_status']=='unavailable' and store._pdf_payload(job['payload'])):
        body += '<form method="post" action="/whatsapp-assistant/jobs/' + str(job_id) + '/media-diagnostic"><input type="hidden" name="csrf" value="' + escape(current['csrf']) + '">' + scope_fields(settings) + '<button>فحص بيانات استجابة المرفق فقط</button></form>'
    body += '<form method="post" action="/whatsapp-assistant/accept"><input type="hidden" name="csrf" value="' + escape(current['csrf']) + '">' + scope_fields(settings) + '<label>رقم طلب قراءة PDF الناجح<input name="document_job_id" required></label><label>رقم طلب سؤال المتابعة الناجح<input name="followup_job_id" required></label><label><input type="checkbox" name="owner_receipt_confirmed" value="yes" required>أكد المالك وصول الردين ومطابقتهما للملف التجريبي الفعلي.</label><button>اعتماد نجاح الاختبار وتوسيع الردود التشغيلية المصرح بها</button></form>'
    return inbox.page(body)


@router.get('/whatsapp-assistant/jobs/{job_id}/document')
async def job_document(job_id: int, request: Request):
    current = z.session(request)
    account = z.account_id()
    job = await run_in_threadpool(store.get_job,job_id)
    if not job or job['account_id'] != z.account_id():
        raise HTTPException(404)
    content = await fetch_document(job)
    read_scope(request,current,account)
    return Response(content,media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="whatsapp-document.pdf"',
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"sandbox; default-src 'none'"})


def diagnostic_scope(job, settings, account):
    if (not job or job['account_id'] != account or settings['mode'] != 'owner_pilot'
            or job['sender'] != settings['pilot_sender']
            or job['authorization_generation'] != settings['authorization_generation']
            or job['document_status'] != 'unavailable' or not store._pdf_payload(job['payload'])):
        raise HTTPException(409,'Current owner attachment scope required')
    media_id = job['payload']['attachments'][0].get('media_id')
    if not inbox.media_identifier(media_id):
        raise HTTPException(404,'Verified media identity unavailable')
    return media_id


@router.post('/whatsapp-assistant/jobs/{job_id}/media-diagnostic')
async def media_diagnostic(job_id: int, request: Request):
    """One read-only bounded provider inspection; never invokes the worker."""
    current = z.session(request)
    account = z.account_id()
    form = await inbox.form(request,current)
    read_scope(request,current,account)
    if form.get('account_id') != account:
        raise HTTPException(409,'Account changed')
    try:
        generation = int(form['generation'])
    except (ValueError,KeyError):
        raise HTTPException(400,'Authorization generation required') from None
    job = await run_in_threadpool(store.get_job,job_id)
    settings = await run_in_threadpool(store.get_settings,account)
    media_id = diagnostic_scope(job,settings,account)
    if settings['authorization_generation'] != generation:
        raise HTTPException(409,'Scope changed')
    read_scope(request,current,account)
    async with z.client() as c:
        await z.validate_account(c)
        latest = await run_in_threadpool(store.get_settings,account)
        diagnostic_scope(job,latest,account)
        read_scope(request,current,account)
        result = await inbox.inspect_media_response(c,media_id,account)
    latest = await run_in_threadpool(store.get_settings,account)
    diagnostic_scope(job,latest,account)
    read_scope(request,current,account)
    body = '<h2>بيانات استجابة المرفق</h2><p>فحص للنوع والحالة فقط؛ لم يُحلل المستند ولم يُرسل رد.</p><pre>' + escape(json.dumps(result,ensure_ascii=False,indent=2)) + '</pre>'
    return inbox.page(body)


@router.post('/whatsapp-assistant/accept')
async def accept_pilot(request: Request):
    current = inbox.send_authority(request)
    account = z.account_id()
    form = await inbox.form(request,current)
    generation = mutation_scope(request,current,form,account)
    if form.get('owner_receipt_confirmed') != 'yes':
        raise HTTPException(400,'Owner receipt confirmation required')
    try:
        acceptance = {'owner_receipt_confirmed':True,'document_job_id':int(form['document_job_id']),
                      'followup_job_id':int(form['followup_job_id'])}
        await run_in_threadpool(store.update_settings,account,mode='routine',acceptance=acceptance,expected_generation=generation,
                                accepted_by=str(current['user_id']),accepted_at=datetime.now(timezone.utc))
    except (ValueError,KeyError,store.StateConflict):
        raise HTTPException(409,'Successful correlated pilot evidence is required') from None
    return RedirectResponse('/whatsapp-assistant',303)
