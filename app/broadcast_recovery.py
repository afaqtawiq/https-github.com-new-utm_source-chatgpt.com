"""One explicitly approved, append-only recovery for a disclosed driver test.

The original campaign/recipient receipts are never reset or overwritten. An
uncertain send consumes its attempt and cannot be replayed by this feature.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.storage import db, execute, one, rows, utcnow
from app.driver_offer import require_valid_audience
from app.transport_test import test_broadcast_context, preview_digest
from app import zernio_whatsapp as transport

router = APIRouter()
CAP = Decimal('25.00')
# Verified 2026-10-02: SA/UAE marketing $0.0576 + <=$0.0001 meter,
# 3.75 SAR/USD, 15% tax = <0.25 SAR. Reserve 0.30, never recycle it.
UNIT_RESERVE = Decimal('0.30')
FAILED_METER_RESERVE = Decimal('0.01')
LEGACY_PREFLIGHT_ERROR = 'تعذر التحقق من إعداد واتساب لدى Zernio؛ لم تُرسل الرسالة'


def init_storage():
    execute("""CREATE TABLE IF NOT EXISTS driver_recovery_batches(
        id BIGSERIAL PRIMARY KEY, broadcast_id BIGINT NOT NULL UNIQUE REFERENCES driver_broadcasts(id),
        account_id TEXT NOT NULL, message TEXT NOT NULL, source_digest TEXT NOT NULL,
        preview_digest TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'prepared',
        budget_sar NUMERIC(10,2) NOT NULL, reserved_sar NUMERIC(10,2) NOT NULL,
        prior_reserved_sar NUMERIC(10,2) NOT NULL,
        created_by BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
        approved_by BIGINT, approved_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
        CHECK (budget_sar > 0 AND budget_sar <= 25 AND reserved_sar <= budget_sar))""")
    execute("""CREATE TABLE IF NOT EXISTS driver_recovery_attempts(
        id BIGSERIAL PRIMARY KEY, batch_id BIGINT NOT NULL REFERENCES driver_recovery_batches(id),
        recipient_id BIGINT NOT NULL UNIQUE REFERENCES driver_broadcast_recipients(id),
        driver_id BIGINT NOT NULL, phone TEXT NOT NULL, source_evidence JSONB NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', post_attempted_at TIMESTAMPTZ,
        provider_message_id TEXT, conversation_id TEXT, sent_at TIMESTAMPTZ,
        last_error TEXT, replied_at TIMESTAMPTZ,
        UNIQUE(batch_id,phone))""")
    execute("""CREATE TABLE IF NOT EXISTS driver_recovery_receipts(
        id BIGSERIAL PRIMARY KEY, attempt_id BIGINT NOT NULL REFERENCES driver_recovery_attempts(id),
        provider_message_id TEXT NOT NULL, delivery_status TEXT NOT NULL,
        error_code INTEGER, checked_at TIMESTAMPTZ NOT NULL)""")


def _fingerprint(campaign, recipients):
    # Include the source outcome, receipt and reply facts in stale-form protection.
    value = [campaign['id'], campaign['message'], campaign['status'], campaign.get('accepted_at'),
             campaign.get('accepted_driver_id'), campaign.get('is_test'),
             [{k:r.get(k) for k in ('id','driver_id','phone','status','provider_message_id',
               'sent_at','replied_at','last_error','post_attempted_at','send_phase','provider_response_status')} for r in recipients]]
    return hashlib.sha256(json.dumps(value, default=str, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _source(connection, bid, lock=False):
    suffix = ' FOR UPDATE' if lock else ''
    campaign = connection.execute('SELECT * FROM driver_broadcasts WHERE id=%s' + suffix, (bid,)).fetchone()
    if not campaign:
        raise HTTPException(404)
    recipients = connection.execute('SELECT * FROM driver_broadcast_recipients WHERE broadcast_id=%s ORDER BY id' + suffix, (bid,)).fetchall()
    return campaign, recipients


def _valid(campaign, recipients):
    if (not campaign.get('is_test') or campaign['status'] != 'completed_with_errors'
            or campaign.get('accepted_at') or campaign.get('accepted_driver_id')):
        raise HTTPException(409, 'الاسترداد متاح لاختبار معلن فشل فقط، قبل أي قبول سائق')
    test_broadcast_context(campaign, approved=True)
    require_valid_audience(campaign, recipients)
    active = [r for r in recipients if r['status'] != 'excluded']
    if (len(active) > 81 or any(not r.get('driver_id') or not r['phone'].startswith(('+966', '+971')) for r in active)):
        raise HTTPException(409, 'تجاوز نطاق هذه الاستعادة المحدودة أو تعذر تقدير التكلفة')
    if os.getenv('WHATSAPP_PROVIDER', '').lower() != 'zernio':
        raise HTTPException(409, 'الاستعادة مرتبطة بمزود Zernio المحدد فقط')
    if datetime.now(timezone.utc) >= datetime(2027, 1, 1, tzinfo=timezone.utc):
        raise HTTPException(409, 'يلزم تحديث تقدير رسوم الرسائل قبل الاستعادة')


def preflight_proven(row):
    return (row['status'] == 'failed' and not row.get('provider_message_id')
            and not row.get('sent_at') and not row.get('replied_at')
            and not row.get('post_attempted_at') and row.get('provider_response_status') is None
            and (row.get('send_phase') == 'preflight_failed'
                 or (not row.get('send_phase') and row.get('last_error') == LEGACY_PREFLIGHT_ERROR)))


def prior_reserve(recipients, evidence):
    """Meta bills delivered messages; still reserve the meter for failed POSTs.

    Any original accepted/uncertain attempt without verified terminal failure
    retains a full-message reserve. Only proven no-POST preflight costs zero.
    """
    total = Decimal('0')
    for row in recipients:
        if row['status'] == 'excluded' or preflight_proven(row): continue
        if evidence.get(row['id'], {}).get('kind') == 'provider_failed':
            total += FAILED_METER_RESERVE
        else:
            total += UNIT_RESERVE
    return total


async def conversation_index(client):
    cursor, visited, found = None, set(), {}
    for _ in range(50):
        params = {'accountId':transport.account_id(), 'platform':'whatsapp', 'limit':100}
        if cursor: params['cursor'] = cursor
        payload = await transport.read(client, '/inbox/conversations', params)
        if (payload.get('meta') or {}).get('accountsFailed'):
            raise transport.WhatsAppBlocked('تعذر التحقق من سجل المزود؛ لم يُرسل شيء')
        for item in payload.get('data', []):
            if (item.get('accountId') == transport.account_id() and item.get('platform') == 'whatsapp'
                    and item.get('id') and not item.get('isGroup')):
                number = transport.phone(item.get('participantId'))
                if number: found.setdefault(number, []).append(str(item['id']))
        pagination = payload.get('pagination') or {}
        if not pagination.get('hasMore'): return found
        cursor = pagination.get('nextCursor')
        if not cursor or cursor in visited: break
        visited.add(cursor)
    raise transport.WhatsAppBlocked('لم يكتمل سجل المحادثات؛ لم يُرسل شيء')


async def receipt(client, cid, mid):
    cursor, visited = None, set()
    for _ in range(50):
        params = {'accountId':transport.account_id(), 'sortOrder':'desc', 'limit':100}
        if cursor: params['cursor'] = cursor
        payload = await transport.read(client, '/inbox/conversations/' + quote(cid, safe='') + '/messages', params)
        for msg in payload.get('messages', []):
            if msg.get('id') != mid: continue
            if (msg.get('direction') != 'outgoing' or msg.get('accountId') != transport.account_id()
                    or msg.get('platform') != 'whatsapp' or msg.get('conversationId') != cid):
                return {'delivery_status':'unknown'}
            status = msg.get('deliveryStatus')
            status = status if status in ('sent','delivered','read','played','failed','deleted') else 'unknown'
            # Conflicting delivery evidence is never replayable.
            if status == 'failed' and (msg.get('deliveredAt') or msg.get('readAt')): status = 'unknown'
            code = (msg.get('deliveryError') or {}).get('code')
            return {'delivery_status':status, 'error_code':code if isinstance(code,int) else None,
                    'conversation_id':cid, 'provider_message_id':mid}
        pagination = payload.get('pagination') or {}
        if not pagination.get('hasMore'): return {'delivery_status':'unknown'}
        cursor = pagination.get('nextCursor')
        if not cursor or cursor in visited: break
        visited.add(cursor)
    return {'delivery_status':'unknown'}


async def _eligible(campaign, recipients):
    evidence = {}
    async with transport.transport_batch() as batch:
        client = await batch.get_client()
        await transport.validate_account(client)
        index = await conversation_index(client) if any(r.get('provider_message_id') for r in recipients if r['status'] != 'excluded') else {}
        for row in recipients:
            if row['status'] == 'excluded' or row.get('replied_at'): continue
            if preflight_proven(row):
                evidence[row['id']] = {'kind':'proven_preflight', 'checked_at':utcnow()}
            elif row['status'] == 'sent' and row.get('provider_message_id'):
                cids = index.get(transport.phone(row['phone']), [])
                if len(cids) != 1: continue
                item = await receipt(client, cids[0], row['provider_message_id'])
                if item['delivery_status'] == 'failed':
                    evidence[row['id']] = {'kind':'provider_failed', **item, 'checked_at':utcnow()}
    return evidence


def _auth(request):
    from app.command_assistant import session
    current = session(request)
    if current.get('role') != 'admin': raise HTTPException(403)
    return current


async def _form(request):
    from app.command_assistant import form
    current = _auth(request)
    values = form(await request.body())
    if values.get('csrf') != current['csrf']: raise HTTPException(403)
    return current, values


def _page(title, body):
    from app.freight_workflow import _page as layout
    return HTMLResponse(layout(title, body))


@router.get('/commands/broadcast/{bid}/recovery', response_class=HTMLResponse)
def review(bid: int, request: Request):
    current = _auth(request)
    with db() as c: campaign, recipients = _source(c, bid)
    batch = one('SELECT * FROM driver_recovery_batches WHERE broadcast_id=?', (bid,))
    body = f'<div class=card><h1>استعادة اختبار السائقين</h1><p>حساب المزود: {escape(batch["account_id"] if batch else transport.account_id())}</p><p>الحملة الأصلية {bid} — لا يتغير سجل محاولتها السابقة.</p><pre>{escape(campaign["message"])}</pre><p>سقف رسوم الاستعادة 25 ريالًا؛ احتياطي 0.30 ريال لكل محاولة، وليس أجرة نقل.</p>'
    if not batch:
        _valid(campaign, recipients)
        body += f'''<form method=post action=/commands/broadcast/{bid}/recovery/prepare>
        <input type=hidden name=csrf value="{escape(current['csrf'])}">
        <input type=hidden name=source_digest value="{_fingerprint(campaign, recipients)}">
        <button>تحقق من الفشل وجهز محاولة مرتبطة دون إرسال</button></form>'''
    else:
        attempts = rows('SELECT a.*,r.driver_name FROM driver_recovery_attempts a JOIN driver_broadcast_recipients r ON r.id=a.recipient_id WHERE a.batch_id=? ORDER BY a.id', (batch['id'],))
        body += f'<p>حالة الاستعادة: {escape(batch["status"])} · المستلمون المؤهلون: {len(attempts)} · الاحتياطي: {batch["reserved_sar"]} ريال</p>'
        if batch['status'] == 'prepared':
            body += f'''<form method=post action=/commands/broadcast/{bid}/recovery/send>
            <input type=hidden name=csrf value="{escape(current['csrf'])}"><input type=hidden name=preview_digest value="{batch['preview_digest']}">
            <label><input type=checkbox name=confirmed value=yes required> أعتمد إعادة الاختبار المعلن للمستلمين المعروضين فقط، دون حمولة فعلية، وبحد إجمالي 25 ريالًا</label>
            <button>إرسال محاولة الاستعادة مرة واحدة</button></form>'''
        body += '<table><tr><th>السائق</th><th>الرقم</th><th>الحالة</th><th>دليل الفشل السابق</th><th>نتيجة التسليم الحالية</th><th>معرف المحاولة الجديدة</th></tr>'
        for item in attempts:
            result = one('SELECT delivery_status,error_code,checked_at FROM driver_recovery_receipts WHERE attempt_id=? ORDER BY id DESC LIMIT 1', (item['id'],))
            body += '<tr>' + ''.join('<td>' + escape(str(x or '—')) + '</td>' for x in (item['driver_name'],item['phone'],item['status'],item['source_evidence']['kind'],result,item['provider_message_id'] or item['last_error'])) + '</tr>'
        body += '</table>'
        body += f'''<form method=post action=/commands/broadcast/{bid}/recovery/reconcile><input type=hidden name=csrf value="{escape(current['csrf'])}"><button>تحقق من التسليم دون إعادة إرسال</button></form>'''
    body += f'</div><a href=/commands/broadcast/{bid}>السجل الأصلي</a>'
    return _page('استعادة اختبار السائقين', body)


@router.post('/commands/broadcast/{bid}/recovery/prepare')
async def prepare(bid: int, request: Request):
    current, values = await _form(request)
    with db() as c: campaign, recipients = _source(c, bid)
    _valid(campaign, recipients)
    before = _fingerprint(campaign, recipients)
    if values.get('source_digest') != before: raise HTTPException(409, 'تغير السجل؛ راجع الصفحة مجددًا')
    if one('SELECT id FROM driver_recovery_batches WHERE broadcast_id=?',(bid,)):
        return RedirectResponse(f'/commands/broadcast/{bid}/recovery',303)
    try: evidence = await _eligible(campaign, recipients)
    except transport.WhatsAppBlocked as exc: raise HTTPException(409, str(exc)) from None
    eligible = [r for r in recipients if r['id'] in evidence]
    if not eligible: raise HTTPException(409, 'لا يوجد فشل مؤكد مؤهل؛ لم تُجهز أو تُرسل محاولة')
    prior = prior_reserve(recipients,evidence)
    reserved = prior + UNIT_RESERVE * len(eligible)
    if reserved > CAP: raise HTTPException(409, 'تجاوز سقف رسوم الاستعادة')
    digest = preview_digest(campaign['message'], eligible)
    with db() as c:
        locked, current_rows = _source(c,bid,True)
        _valid(locked, current_rows)
        if _fingerprint(locked,current_rows) != before: raise HTTPException(409,'تغير السجل أثناء التحقق')
        existing = c.execute('SELECT id FROM driver_recovery_batches WHERE broadcast_id=%s',(bid,)).fetchone()
        if not existing:
            batch = c.execute('''INSERT INTO driver_recovery_batches(broadcast_id,account_id,message,source_digest,preview_digest,budget_sar,reserved_sar,prior_reserved_sar,created_by,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                (bid,transport.account_id(),campaign['message'],before,digest,CAP,reserved,prior,current['user_id'],utcnow())).fetchone()
            for item in eligible:
                c.execute('''INSERT INTO driver_recovery_attempts(batch_id,recipient_id,driver_id,phone,source_evidence)
                    VALUES(%s,%s,%s,%s,%s::jsonb)''',(batch['id'],item['id'],item['driver_id'],item['phone'],json.dumps(evidence[item['id']],default=str)))
    return RedirectResponse(f'/commands/broadcast/{bid}/recovery',303)


def _locked_ready(c, batch_id, *, sending=True):
    # Every path, including inbound acceptance, locks the parent first.
    ref = c.execute('SELECT broadcast_id FROM driver_recovery_batches WHERE id=%s',(batch_id,)).fetchone()
    if not ref: raise HTTPException(409,'محاولة الاستعادة غير موجودة')
    campaign, recipients = _source(c,ref['broadcast_id'],True)
    _valid(campaign,recipients)
    batch = c.execute('SELECT * FROM driver_recovery_batches WHERE id=%s FOR UPDATE',(batch_id,)).fetchone()
    if (batch['account_id'] != transport.account_id() or batch['source_digest'] != _fingerprint(campaign,recipients)
            or batch['message'] != campaign['message'] or (sending and (batch['status'] != 'sending' or not batch['approved_at']))):
        raise HTTPException(409,'تغير السجل أو انتهت صلاحية اعتماد الاستعادة')
    attempts = c.execute('SELECT * FROM driver_recovery_attempts WHERE batch_id=%s ORDER BY id',(batch_id,)).fetchall()
    if (batch['preview_digest'] != preview_digest(batch['message'],attempts)
            or len(attempts) > 81 or UNIT_RESERVE * len(attempts) + batch['prior_reserved_sar'] != batch['reserved_sar']
            or batch['prior_reserved_sar'] != prior_reserve(recipients,{a['recipient_id']:a['source_evidence'] for a in attempts})
            or batch['reserved_sar'] > batch['budget_sar'] or batch['budget_sar'] > CAP):
        raise HTTPException(409,'تغير المستلمون أو حد تكلفة الاستعادة')
    return batch, campaign, recipients


@router.post('/commands/broadcast/{bid}/recovery/send')
async def send_recovery(bid: int, request: Request, background_tasks: BackgroundTasks):
    current, values = await _form(request)
    if values.get('confirmed') != 'yes': raise HTTPException(400,'يلزم اعتماد الاختبار المعروض')
    if os.getenv('ENABLE_EXTERNAL_ACTIONS','0') != '1': raise HTTPException(409,'الإرسال الخارجي متوقف')
    target = one('SELECT id FROM driver_recovery_batches WHERE broadcast_id=?',(bid,))
    if not target: raise HTTPException(409,'جهز المعاينة أولًا')
    with db() as c:
        batch,_,_ = _locked_ready(c,target['id'],sending=False)
        if batch['status'] != 'prepared': raise HTTPException(409,'بدأت هذه المحاولة مسبقًا؛ لن تتكرر')
        if values.get('preview_digest') != batch['preview_digest']: raise HTTPException(409,'المعاينة تغيرت')
        c.execute("UPDATE driver_recovery_batches SET status='sending',approved_by=%s,approved_at=%s WHERE id=%s",(current['user_id'],utcnow(),batch['id']))
    background_tasks.add_task(deliver,batch['id'])
    return RedirectResponse(f'/commands/broadcast/{bid}/recovery',303)


def _boundary(batch_id, attempt_id):
    if os.getenv('ENABLE_EXTERNAL_ACTIONS','0') != '1': raise HTTPException(409,'الإرسال الخارجي متوقف')
    with db() as c:
        _locked_ready(c,batch_id)
        item = c.execute('SELECT * FROM driver_recovery_attempts WHERE id=%s AND batch_id=%s FOR UPDATE',(attempt_id,batch_id)).fetchone()
        if not item or item['status'] != 'sending' or item['post_attempted_at'] or item['provider_message_id']:
            raise HTTPException(409,'بدأت المحاولة مسبقًا أو توقفت')
        c.execute('UPDATE driver_recovery_attempts SET post_attempted_at=%s WHERE id=%s',(utcnow(),attempt_id))


async def deliver(batch_id):
    attempts = rows("SELECT * FROM driver_recovery_attempts WHERE batch_id=? AND status='pending' ORDER BY id",(batch_id,))
    async with transport.transport_batch() as state:
        for item in attempts:
            try:
                with db() as c:
                    batch,_,_ = _locked_ready(c,batch_id)
                    claimed = c.execute("UPDATE driver_recovery_attempts SET status='sending' WHERE id=%s AND status='pending' RETURNING id",(item['id'],)).fetchone()
                if not claimed: continue
                evidence = item['source_evidence']
                async def final_boundary():
                    if evidence['kind'] == 'provider_failed':
                        # A separate read client avoids taking the sending
                        # batch's mutex twice, and never uses cached receipts.
                        async with transport.client() as check_client:
                            now = await receipt(check_client,evidence['conversation_id'],evidence['provider_message_id'])
                        if now['delivery_status'] != 'failed':
                            raise transport.WhatsAppBlocked('لم يعد فشل الرسالة السابقة مؤكدًا؛ لم تُرسل محاولة')
                    _boundary(batch_id,item['id'])
                with transport.dispatch_guard(final_boundary):
                    result = await transport.send(item['phone'],batch['message'])
                messages = result.get('messages') or []
                mid = messages[0].get('id') if messages else None
                if not mid: raise RuntimeError('missing_receipt')
                execute("UPDATE driver_recovery_attempts SET status='accepted',provider_message_id=?,conversation_id=?,sent_at=? WHERE id=? AND status='sending'",(mid,result.get('conversation_id'),utcnow(),item['id']))
            except HTTPException:
                execute("UPDATE driver_recovery_attempts SET status='blocked',last_error='تغيرت الحملة أو انتهت التجربة؛ لم تُرسل محاولة جديدة' WHERE id=? AND status='sending' AND post_attempted_at IS NULL",(item['id'],))
                execute("UPDATE driver_recovery_attempts SET status='uncertain',last_error='توقفت المحاولة بعد حد الإرسال؛ يلزم التحقق' WHERE id=? AND status='sending' AND post_attempted_at IS NOT NULL",(item['id'],))
                execute("UPDATE driver_recovery_batches SET status='stopped',completed_at=? WHERE id=? AND status='sending'",(utcnow(),batch_id))
                return
            except Exception as exc:
                boundary = one('SELECT post_attempted_at FROM driver_recovery_attempts WHERE id=?',(item['id'],))
                status = 'failed' if isinstance(exc,transport.WhatsAppBlocked) else ('uncertain' if boundary['post_attempted_at'] else 'blocked')
                message = 'فشل تحقق أو رفض صريح من المزود؛ لا توجد إعادة تلقائية' if status == 'failed' else 'نتيجة غير مؤكدة؛ لا توجد إعادة تلقائية' if status == 'uncertain' else 'توقف قبل الإرسال؛ لا توجد إعادة تلقائية'
                execute('UPDATE driver_recovery_attempts SET status=?,last_error=? WHERE id=? AND status=\'sending\'',(status,message,item['id']))
    execute("""UPDATE driver_recovery_batches SET status='completed',completed_at=? WHERE id=? AND status='sending'
        AND NOT EXISTS(SELECT 1 FROM driver_recovery_attempts WHERE batch_id=? AND status IN ('pending','sending'))""",(utcnow(),batch_id,batch_id))


@router.post('/commands/broadcast/{bid}/recovery/reconcile')
async def reconcile(bid: int, request: Request):
    await _form(request)
    batch = one('SELECT * FROM driver_recovery_batches WHERE broadcast_id=?',(bid,))
    if not batch or batch['account_id'] != transport.account_id(): raise HTTPException(409,'الحساب لا يطابق المحاولة')
    attempts = rows("SELECT * FROM driver_recovery_attempts WHERE batch_id=? AND provider_message_id IS NOT NULL",(batch['id'],))
    async with transport.transport_batch() as state:
        client = await state.get_client()
        await transport.validate_account(client)
        index = await conversation_index(client)
        for item in attempts:
            cids = index.get(transport.phone(item['phone']),[])
            if len(cids) != 1: continue
            result = await receipt(client,cids[0],item['provider_message_id'])
            execute('''INSERT INTO driver_recovery_receipts(attempt_id,provider_message_id,delivery_status,error_code,checked_at)
                VALUES(?,?,?,?,?)''',(item['id'],item['provider_message_id'],result['delivery_status'],result.get('error_code'),utcnow()))
    return RedirectResponse(f'/commands/broadcast/{bid}/recovery',303)
