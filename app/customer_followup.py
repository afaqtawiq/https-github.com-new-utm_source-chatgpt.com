"""Private, read-only customer follow-up projection over existing evidence.

No imports with database side effects, migrations, writes, provider reads, sends,
classification, automatic CRM merges or scheduled delivery. A refresh reflects
new source records automatically. All counts describe endpoints/evidence, not
unique people, customers, conversions or permission to contact anyone.
"""
from datetime import date, datetime, time, timedelta, timezone
from html import escape
import os
import re
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()
RIYADH = ZoneInfo('Asia/Riyadh')
LIMIT = 10000
HEADERS = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
           'X-Content-Type-Options': 'nosniff'}
LABELS = {
    'identity_review': 'تحقق من الاسم والرقم قبل أي متابعة',
    'suppressed': 'موقوف تسويقيًا؛ لا ترسل متابعة',
    'paused': 'المحادثة لدى الموظف؛ أبق الرد الآلي موقوفًا',
    'review_inbound': 'يوجد وارد تاريخي؛ حالة مراجعته والرد عليه غير محسومة',
    'delivery_review': 'راجع فشل أو غموض الإرسال دون إعادة إرسال',
    'waiting_unverified': 'تحقق من سجل المحادثة؛ الرد غير محسوم',
    'no_evidence': 'لا يوجد دليل إرسال في المصادر المتاحة',
    'safety_review': 'تحقق من حالة الإيقاف والتسليم للموظف قبل أي متابعة',
}


def stamp(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    return value.astimezone(timezone.utc)


def endpoint(channel, value):
    """Full exact address only. Do not infer a country or compare phone suffixes."""
    value = str(value or '').strip()
    if channel == 'whatsapp':
        value = re.sub(r'[ ()\-]', '', value)
        if value.startswith('00'):
            value = '+' + value[2:]
        value = value.removeprefix('+')
        return '+' + value if re.fullmatch(r'[1-9][0-9]{8,14}', value) else None
    if channel == 'email' and re.fullmatch(r'[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+', value):
        return value.lower()
    return None


def window(day):
    start = datetime.combine(day, time.min, RIYADH)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def project(records, events, holds=(), *, now=None, suppression_known=True, pauses_known=True):
    """Deterministic replay, scoped by account/mailbox, preserving identity conflicts."""
    now = stamp(now) or datetime.now(timezone.utc)
    groups = {}

    def group(row):
        address = endpoint(row['channel'], row.get('recipient'))
        # Invalid identities cannot be merged even if their raw string matches.
        key = (row['channel'], str(row['scope']), address or 'unresolved:' + row['source'])
        if key not in groups:
            groups[key] = {'channel': key[0], 'scope': key[1], 'recipient': address,
                           'names': set(), 'sources': set(), 'events': {},
                           'invalid_identity': address is None, 'paused': False, 'suppressed': False}
        result = groups[key]
        result['sources'].add(row['source'])
        if row.get('name'):
            result['names'].add(str(row['name']).strip())
        return result

    for row in records:
        group(row)
    for row in events:
        item = group(row)
        when = stamp(row.get('at'))
        identity = str(row.get('provider_id') or '').strip()
        # Deduplicate one provider message across source tables; direction and scope
        # are part of identity. Missing IDs stay source-qualified, never guessed.
        event_key = (row['direction'], identity or row['source'])
        if event_key not in item['events']:
            item['events'][event_key] = {'direction': row['direction'], 'states': set(),
                                         'at': when, 'sources': set()}
        event = item['events'][event_key]
        event['states'].add(row['state'])
        event['sources'].add(row['source'])
        if when and (event['at'] is None or when > event['at']):
            event['at'] = when
    suppressed_endpoints = set()
    for row in holds:
        item = group(row)
        item['paused'] |= bool(row.get('paused'))
        item['suppressed'] |= bool(row.get('suppressed'))
        if row.get('suppressed') and item['recipient']:
            suppressed_endpoints.add((item['channel'], item['recipient']))

    output = []
    for item in groups.values():
        # marketing_suppressions is global by channel/address. Apply once after
        # all scopes exist, preserving prohibitions without quadratic scans.
        if (item['channel'], item['recipient']) in suppressed_endpoints:
            item['suppressed'] = True
        if not item['suppressed'] and not suppression_known:
            item['suppressed'] = None
        pause_scope_known = pauses_known and item['scope'] != 'legacy_campaign_unscoped'
        if item['channel'] == 'whatsapp' and not item['paused'] and not pause_scope_known:
            item['paused'] = None
        item['safety_state_complete'] = item['suppressed'] is not None and item['paused'] is not None
        evidence = list(item.pop('events').values())
        inbound = [e for e in evidence if e['direction'] == 'inbound']
        attempts = [e for e in evidence if e['direction'] == 'outbound'
                    and e['states'] != {'not_sent'}]
        notice = [e for e in evidence if e['direction'] == 'notice']
        ambiguous = any(len(e['states']) > 1 for e in evidence)
        failed = any(e['states'] & {'failed', 'uncertain'} for e in attempts + notice)
        last_out = max((e['at'] for e in attempts if e['at']), default=None)
        last_in = max((e['at'] for e in inbound if e['at']), default=None)
        item['identity_conflict'] = item['invalid_identity'] or len(item['names']) > 1
        action = ('suppressed' if item['suppressed'] else 'paused' if item['paused'] else
                  'safety_review' if not item['safety_state_complete'] else
                  'identity_review' if item['identity_conflict'] else
                  'review_inbound' if inbound else 'delivery_review' if failed or ambiguous else
                  'waiting_unverified' if attempts else 'no_evidence')
        output.append({**item, 'names': sorted(item['names']), 'sources': sorted(item['sources']),
                       'attempts': len(attempts), 'inbound_observations': len(inbound),
                       'notices': len(notice), 'evidence_conflict': ambiguous,
                       'last_outbound_at': last_out, 'last_inbound_at': last_in,
                       'delivery': 'not_verified', 'human_reply': 'not_verified',
                       'next_action': action,
                       'events': [{**e, 'states': sorted(e['states']), 'sources': sorted(e['sources'])}
                                  for e in evidence]})
    return sorted(output, key=lambda x: (x['next_action'], x['channel'], x['scope'], x['recipient'] or '', x['sources']))


def load_sources(c, uid, account, include_mail):
    """Bounded source reads; savepoints preserve a usable partial snapshot.

    SQL and table names below are static. No data bodies, attachments, driver,
    price, token, password, raw errors or financial columns are selected.
    """
    coverage, records, events, holds, crm = [], [], [], [], []

    def read(name, sql, args=(), allowed=True):
        if not allowed:
            coverage.append({'source': name, 'status': 'not_authorized_or_configured', 'rows': 0})
            return []
        c.execute('SAVEPOINT customer_followup_source')
        try:
            result = [dict(r) for r in c.execute(sql + ' LIMIT %s', (*args, LIMIT + 1)).fetchall()]
        except Exception:
            c.execute('ROLLBACK TO SAVEPOINT customer_followup_source')
            coverage.append({'source': name, 'status': 'unavailable', 'rows': 0})
            return []
        finally:
            c.execute('RELEASE SAVEPOINT customer_followup_source')
        coverage.append({'source': name, 'status': 'truncated' if len(result) > LIMIT else 'read',
                         'rows': min(len(result), LIMIT)})
        return result[:LIMIT]

    def add_roster(name, data):
        for r in data:
            for channel, field, scope in [('whatsapp', 'phone', account), ('email', 'email', str(uid))]:
                if r.get(field) and scope and (channel != 'email' or include_mail):
                    records.append({'source': name + ':' + str(r['id']), 'channel': channel,
                                    'scope': scope, 'recipient': r[field], 'name': r.get('name')})

    add_roster('account', read('accounts', 'SELECT id,name,phone,email FROM accounts ORDER BY id DESC'))
    add_roster('directory', read('customer_directory', 'SELECT id,company_name AS name,phone,email FROM customer_directory ORDER BY id DESC'))
    add_roster('daily_prospect', read('daily_prospects', 'SELECT id,company_name AS name,phone,email FROM daily_prospects ORDER BY id DESC'))
    add_roster('sales_prospect', read('sales_prospects', 'SELECT id,company_name AS name,recipient AS email FROM sales_prospects WHERE mail_user_id=%s ORDER BY id DESC', (uid,), include_mail))

    campaign = read('customer_campaign_recipients', '''SELECT r.id,r.channel,r.recipient,r.company_name,r.status,
        r.provider_message_id,r.sent_at,r.claimed_at FROM customer_campaign_recipients r
        WHERE r.channel='whatsapp' OR (r.channel='email' AND r.sender_user_id=%s AND %s) ORDER BY r.id DESC''', (uid, include_mail))
    for r in campaign:
        channel = r['channel']
        if (channel == 'email' and not include_mail) or (channel == 'whatsapp' and not account):
            continue
        # Legacy campaign rows carry no WhatsApp account ID. Never silently
        # attribute them to the currently configured account or merge their IDs.
        events.append({'source': 'campaign:' + str(r['id']), 'scope': 'legacy_campaign_unscoped' if channel == 'whatsapp' else str(uid),
                       'channel': channel, 'recipient': r['recipient'], 'name': r['company_name'],
                       'direction': 'outbound', 'state': send_state(r['status']),
                       'provider_id': r['provider_message_id'], 'at': r['sent_at'] or r['claimed_at']})

    outbound = read('outbound_messages', '''SELECT id,recipient,status,provider_message_id,sent_at,updated_at
        FROM outbound_messages WHERE mail_user_id=%s AND channel='email' ORDER BY id DESC''', (uid,), include_mail)
    for r in outbound:
        events.append({'source': 'outbound:' + str(r['id']), 'channel': 'email', 'scope': str(uid),
                       'recipient': r['recipient'], 'direction': 'outbound', 'state': send_state(r['status']),
                       'provider_id': r['provider_message_id'], 'at': r['sent_at'] or r['updated_at']})
    inbox = read('spacemail_inbox', '''SELECT id,sender_address,notice_kind,notice_recipient,message_id,imported_at
        FROM spacemail_inbox WHERE user_id=%s AND duplicate_of IS NULL ORDER BY id DESC''', (uid,), include_mail)
    for r in inbox:
        notice = str(r['notice_kind'] or '').startswith('delivery_')
        events.append({'source': 'inbox:' + str(r['id']), 'channel': 'email', 'scope': str(uid),
                       'recipient': r['notice_recipient'] if notice else r['sender_address'],
                       'direction': 'notice' if notice else 'inbound',
                       'state': 'failed' if r['notice_kind'] == 'delivery_failed' else 'uncertain' if notice else 'observed',
                       'provider_id': r['message_id'], 'at': r['imported_at']})
    jobs = read('whatsapp_agent_jobs', '''SELECT j.id,j.sender,j.message_id,j.created_at,
        o.status AS send_status,o.provider_message_id,o.updated_at AS sent_at
        FROM whatsapp_agent_jobs j LEFT JOIN whatsapp_agent_outbox o ON o.job_id=j.id
        WHERE j.account_id=%s ORDER BY j.id DESC''', (account,), bool(account))
    for r in jobs:
        base = {'source': 'wa_job:' + str(r['id']), 'channel': 'whatsapp', 'scope': account, 'recipient': r['sender']}
        events.append({**base, 'direction': 'inbound', 'state': 'observed', 'provider_id': r['message_id'], 'at': r['created_at']})
        if r['send_status']:
            events.append({**base, 'source': 'wa_outbox:' + str(r['id']), 'direction': 'outbound',
                           'state': send_state(r['send_status']), 'provider_id': r['provider_message_id'], 'at': r['sent_at']})
    receipts = read('whatsapp_takeover_receipts', '''SELECT id,sender,message_id,received_at FROM whatsapp_takeover_receipts
        WHERE account_id=%s ORDER BY id DESC''', (account,), bool(account))
    for r in receipts:
        events.append({'source': 'wa_receipt:' + str(r['id']), 'channel': 'whatsapp', 'scope': account,
                       'recipient': r['sender'], 'direction': 'inbound', 'state': 'observed',
                       'provider_id': r['message_id'], 'at': r['received_at']})
    manual = read('whatsapp_inbox_drafts', '''SELECT md5(token) AS source_ref,recipient,state,provider_message_id,updated_at
        FROM whatsapp_inbox_drafts WHERE account_id=%s ORDER BY updated_at DESC,token''', (account,), bool(account))
    for r in manual:
        events.append({'source': 'wa_manual:' + r['source_ref'], 'channel': 'whatsapp', 'scope': account,
                       'recipient': r['recipient'], 'direction': 'outbound', 'state': send_state(r['state']),
                       'provider_id': r['provider_message_id'], 'at': r['updated_at']})
    pauses = read('whatsapp_conversation_takeovers', '''SELECT conversation_id,sender FROM whatsapp_conversation_takeovers
        WHERE account_id=%s AND paused=TRUE ORDER BY conversation_id''', (account,), bool(account))
    for r in pauses:
        holds.append({'source': 'wa_pause:' + r['conversation_id'], 'channel': 'whatsapp', 'scope': account,
                      'recipient': r['sender'], 'paused': True})
    suppressions = read('marketing_suppressions', '''SELECT channel,recipient FROM marketing_suppressions
        WHERE channel='whatsapp' OR (channel='email' AND %s) ORDER BY channel,recipient''', (include_mail,))
    for r in suppressions:
        if (r['channel'] == 'email' and include_mail) or (r['channel'] == 'whatsapp' and account):
            holds.append({'source': 'suppression:' + r['channel'] + ':' + r['recipient'],
                          'channel': r['channel'], 'scope': account if r['channel'] == 'whatsapp' else str(uid),
                          'recipient': r['recipient'], 'suppressed': True})
    crm = read('sales_followups', '''SELECT f.id,f.opportunity_id,f.due_at,f.status,o.company_name,o.stage,
        s.outcome AS recorded_outcome FROM sales_followups f JOIN opportunities o ON o.id=f.opportunity_id
        LEFT JOIN sales_outcomes s ON s.opportunity_id=o.id WHERE f.status='open' ORDER BY f.due_at,f.id''')
    opportunities = read('opportunities', '''SELECT o.id,o.account_id,o.company_name,o.stage,
        s.outcome AS recorded_outcome,s.recorded_at FROM opportunities o
        LEFT JOIN sales_outcomes s ON s.opportunity_id=o.id ORDER BY o.id DESC''')
    return records, events, holds, crm, opportunities, coverage


def send_state(raw):
    if raw in {'sent', 'delivered', 'read', 'accepted'}:
        # These source tables are acceptance logs, not verified provider receipts.
        return 'accepted'
    if raw in {'failed', 'bounced', 'rejected'}:
        return 'failed'
    if raw in {'draft', 'pending', 'approved', 'ready', 'cancelled', 'blocked', 'suppressed', 'skipped', 'cadence_skipped'}:
        return 'not_sent'
    return 'uncertain'


def snapshot(uid, account, include_mail, *, db_factory=None, now=None):
    if db_factory is None:
        from app.storage import db
        db_factory = db
    now = stamp(now) or datetime.now(timezone.utc)
    with db_factory() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        c.execute("SET LOCAL statement_timeout = '5s'")
        records, events, holds, crm, opportunities, coverage = load_sources(c, uid, account, include_mail)
    status = {r['source']: r['status'] for r in coverage}
    contacts = project(records, events, holds, now=now,
                       suppression_known=status.get('marketing_suppressions') == 'read',
                       pauses_known=status.get('whatsapp_conversation_takeovers') == 'read')
    return {'generated_at': now, 'contacts': contacts, 'crm_followups': crm,
            'crm_opportunities': opportunities, 'coverage': coverage,
            'complete': False, 'external_actions': False,
            'limitations': ['WhatsApp coverage is the local processed subset, not the full provider inbox.',
                            'Email uses imported time, not verified received time; mailbox sync may lag.',
                            'Campaign WhatsApp rows lack historical account identity and remain in a separate legacy scope.',
                            'Endpoint counts are not unique people, customers, replies or conversions.',
                            'Legacy email campaign rows without explicit mailbox ownership are excluded.',
                            'Sources are bounded to recent records; daily numbers are partial observations, not complete totals.',
                            'The historical Excel is not imported. No inferred opt-in or CRM edits.']}


def digest(data, day):
    start, end = window(day)
    seen_attempts, seen_inbound = set(), set()
    unresolved = 0
    for item in data['contacts']:
        seen = set()
        for event in item['events']:
            at = stamp(event['at'])
            if at and start <= at < end:
                if event['direction'] == 'outbound' and event['states'] != ['not_sent']:
                    seen.add('attempted_endpoints')
                elif event['direction'] == 'inbound':
                    seen.add('inbound_endpoints')
        if seen and not item['recipient']:
            unresolved += 1
            continue
        # Counting addresses across scopes does not merge customer identities.
        identity = (item['channel'], item['recipient'])
        if 'attempted_endpoints' in seen:
            seen_attempts.add(identity)
        if 'inbound_endpoints' in seen:
            seen_inbound.add(identity)
    counts = {'attempted_endpoints': len(seen_attempts), 'inbound_endpoints': len(seen_inbound)}
    due = sum(stamp(r['due_at']) is not None and stamp(r['due_at']) < end for r in data['crm_followups'])
    problems = sum(c['status'] != 'read' for c in data['coverage'])
    return {'day': day.isoformat(), 'timezone': 'Asia/Riyadh', 'start': start, 'end': end,
            'attempted_endpoints': counts['attempted_endpoints'], 'inbound_endpoints': counts['inbound_endpoints'],
            'currently_open_crm_due_by_day_end': due, 'counts_are_partial': True,
            'unresolved_address_records': unresolved, 'incomplete_sources': problems,
            'text': '\n'.join([f'ملخص المتابعة الداخلي ليوم {day.isoformat()} بتوقيت الرياض',
                              f'عناوين تواصل عليها دليل محاولة أو إرسال غير محسوم: {counts["attempted_endpoints"]}',
                              f'عناوين ظهر منها وارد، ومراجعته غير محسومة: {counts["inbound_endpoints"]}',
                              f'مهام CRM المفتوحة الآن والمستحقة حتى التاريخ المحدد: {due}',
                              'الأرقام من الجزء المقروء فقط وليست إجماليات. المحاولة ليست تسليمًا، والوارد ليس ردًا بشريًا أو صفقة مؤكدة.',
                              'لا يرسل هذا الملخص أي متابعة إلى العملاء.'])}


def authority(request):
    from app.storage import get_session
    from app.fine_permissions import has_permission
    session = get_session(request.cookies.get('gla_session'))
    if not session:
        raise HTTPException(401)
    if session.get('role') != 'admin':
        raise HTTPException(403)
    return session, has_permission(session, 'manage_gmail')


def request_data(request):
    session, mail = authority(request)
    account = os.getenv('ZERNIO_WHATSAPP_ACCOUNT_ID', '') or os.getenv('WHATSAPP_COMMAND_ACCOUNT_ID', '')
    return snapshot(session['user_id'], account, mail)


@router.get('/api/v7/customer-followup')
def api(request: Request):
    from fastapi.encoders import jsonable_encoder
    return JSONResponse(jsonable_encoder(request_data(request)), headers=HEADERS)


@router.get('/api/v7/customer-followup/digest')
def daily(request: Request, day: date | None = None):
    from fastapi.encoders import jsonable_encoder
    data = request_data(request)
    day = day or (datetime.now(RIYADH).date() - timedelta(days=1))
    return JSONResponse(jsonable_encoder(digest(data, day)), headers=HEADERS)


@router.get('/api/v7/customer-followup/digest-status')
def digest_status(request: Request):
    from fastapi.encoders import jsonable_encoder
    from app.customer_followup_digest import public_status
    authority(request)
    return JSONResponse(jsonable_encoder(public_status()), headers=HEADERS)


@router.get('/customer-followup')
def page(request: Request):
    data = request_data(request)
    summary = digest(data, datetime.now(RIYADH).date() - timedelta(days=1))
    rows = []
    # Full bounded data remains available in the private JSON endpoint.
    for item in data['contacts'][:500]:
        values = [' / '.join(item['names']) or 'اسم غير محقق', item['channel'], item['scope'],
                  item['recipient'] or 'عنوان يحتاج تصحيحًا', str(item['attempts']),
                  str(item['inbound_observations']), LABELS[item['next_action']],
                  ', '.join(item['sources'])]
        rows.append('<tr>' + ''.join('<td>' + escape(v) + '</td>' for v in values) + '</tr>')
    coverage = ', '.join(escape(c['source'] + ': ' + c['status']) for c in data['coverage'])
    crm_rows = []
    for r in data['crm_followups'][:100]:
        values = [str(r['opportunity_id']), str(r['company_name']), str(r['due_at']),
                  str(r['stage']), str(r['recorded_outcome'] or 'لا توجد نتيجة مسجلة')]
        crm_rows.append('<tr>' + ''.join('<td>' + escape(v) + '</td>' for v in values) + '</tr>')
    return HTMLResponse('''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8">
      <meta name="viewport" content="width=device-width"><title>متابعة العملاء والفرص</title>
      <style>body{font:16px Tahoma;background:#0b2031;color:white;padding:24px}a{color:#ffd978}
      table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #496071}
      pre{white-space:pre-wrap}.scroll{overflow:auto}td{overflow-wrap:anywhere;max-width:300px}</style>
      <a href="/dashboard">الرئيسية</a> · <a href="/sales-review">مراجعة البريد</a> ·
      <a href="/whatsapp-inbox">محادثات واتساب</a><h1>متابعة العملاء والفرص</h1>
      <p>قراءة داخلية متجددة من السجلات الحالية. لا إرسال ولا أسعار ولا حجوزات ولا دمج تلقائي للعملاء.</p>
      <pre>''' + escape(summary['text']) + '''</pre><p>الأسماء المختلفة لنفس العنوان تحتاج مراجعة.
      السجل حسب عنوان التواصل والقناة، وليس تعدادًا للعملاء. هذه الصفحة للعرض فقط. <a href="/api/v7/customer-followup/digest-status">حالة إرسال الملخص الصباحي</a>.</p>
      <p>التغطية: ''' + coverage + '''</p><p>عرض أول 500 عنوان. <a href="/api/v7/customer-followup">السجل الخاص الكامل بصيغة JSON</a></p>
      <div class="scroll"><table><tr><th>الأسماء المسجلة</th><th>القناة</th><th>نطاق المصدر</th><th>العنوان</th><th>محاولات</th>
      <th>وارد غير مصنف</th><th>الإجراء الداخلي التالي</th><th>مراجع الأدلة</th></tr>'''
      + ''.join(rows) + '</table></div><h2>مهام المتابعة المفتوحة في CRM</h2><p>النتيجة أدناه من السجل الحالي، وليست استنتاجًا من رد أو محاولة إرسال. أول 100 مهمة.</p>'
      + '<div class="scroll"><table><tr><th>الفرصة</th><th>الشركة</th><th>الاستحقاق</th><th>المرحلة</th><th>النتيجة المسجلة</th></tr>'
      + ''.join(crm_rows) + '</table></div></html>', headers=HEADERS)
