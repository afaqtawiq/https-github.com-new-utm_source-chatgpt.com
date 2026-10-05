"""Transactional operational bookkeeping. No bank or outbound provider code."""
import hashlib
import json
import uuid
from decimal import Decimal
from fastapi import HTTPException
from psycopg.errors import UniqueViolation
from app.storage import db, utcnow
from app import finance_core as core
from app.finance_schema import LOCK_KEY


def fail(message, code=400):
    raise HTTPException(code, message)


def token(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        fail('معرّف تكرار الطلب مفقود أو غير صالح')


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def lock(c):
    c.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK_KEY,))


def audit(c, actor, action, entity_type, entity_id, detail):
    if not isinstance(detail, str):
        detail = json.dumps(detail, sort_keys=True, ensure_ascii=False, default=str)
    c.execute('INSERT INTO finance_audit(actor_id,action,entity_type,entity_id,detail,created_at) VALUES(%s,%s,%s,%s,%s,%s)',
              (actor, action, entity_type, entity_id, detail, utcnow()))


def identity(c, owner_id, counterparty_id=None):
    owner = c.execute('SELECT * FROM finance_party_display WHERE id=%s', (owner_id,)).fetchone()
    if not owner or owner['kind'] != 'owner' or not owner['confirmed']:
        fail('يلزم مالك حساب مستقل ومؤكد؛ لا يتم الدمج مع سجل العملاء')
    if counterparty_id is None:
        return owner
    party = c.execute('SELECT * FROM finance_party_display WHERE id=%s', (counterparty_id,)).fetchone()
    if not party or party['kind'] != 'counterparty' or not party['confirmed'] or owner_id == counterparty_id:
        fail('يلزم طرف مقابل مستقل ومؤكد')
    return owner, party


def replay(c, table, key, digest):
    prior = c.execute('SELECT * FROM '+table+' WHERE idempotency_key=%s', (key,)).fetchone()
    if prior and prior['payload_hash'] != digest:
        fail('معرّف الطلب استُخدم مع بيانات مختلفة؛ حدّث الصفحة', 409)
    return prior


def create_party(form, actor):
    name = core.clean(form.get('name'), 200, True)
    identity_ref = core.clean(form.get('identity_ref'), 200, True)
    kind = core.clean(form.get('kind'), 20, True)
    if kind not in ('owner', 'counterparty') or form.get('confirmed') != '1':
        fail('يجب تأكيد هوية الجهة ودورها صراحة')
    try:
        with db() as c:
            lock(c)
            row = c.execute('''INSERT INTO finance_parties(name,kind,identity_ref,confirmed,created_by,created_at)
                VALUES(%s,%s,%s,TRUE,%s,%s) RETURNING *''', (name, kind, identity_ref, actor, utcnow())).fetchone()
            audit(c, actor, 'party_confirmed', 'party', row['id'], row)
            return row['id']
    except UniqueViolation:
        fail('مرجع الهوية مسجل مسبقًا؛ لا يتم دمج الجهات تلقائيًا', 409)


def rename_owner(owner_id, actor, form):
    """Correct a display name without changing the confirmed financial identity."""
    allowed = {'csrf','idempotency_key','name','expected_revision','reason','confirmation'}
    if set(form) - allowed:
        fail('التعديل متاح لاسم العرض فقط')
    name = core.clean(form.get('name'), 200, True)
    reason = core.clean(form.get('reason'), 1000, True)
    revision = core.clean(form.get('expected_revision'), 20, True)
    if not revision.isascii() or not revision.isdigit():
        fail('نسخة اسم العرض غير صالحة؛ حدّث الصفحة')
    if form.get('confirmation') != '1':
        fail('أكد تصحيح اسم العرض لنفس صاحب الحساب دون نقل الأرصدة')
    key = token(form.get('idempotency_key'))
    payload = {'owner_id':owner_id, 'name':name, 'reason':reason, 'previous_revision':int(revision)}
    digest = fingerprint(payload)
    with db() as c:
        lock(c)
        if replay(c, 'finance_owner_name_changes', key, digest):
            return
        owner = identity(c, owner_id)
        if owner['name_revision'] != int(revision):
            fail('تغير اسم العرض منذ فتح النموذج؛ حدّث الصفحة قبل التصحيح', 409)
        if owner['name'] == name:
            fail('اسم العرض مطابق للاسم الحالي؛ لا يوجد تغيير')
        c.execute('''INSERT INTO finance_owner_name_changes
            (owner_id,name,previous_name,previous_revision,reason,idempotency_key,payload_hash,created_by,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (owner_id,name,owner['name'],int(revision),reason,key,digest,actor,utcnow()))
        audit(c, actor, 'owner_display_name_changed', 'party', owner_id,
              {'previous_name':owner['name'], 'name':name, 'reason':reason, 'previous_revision':int(revision)})


def create_document(form, actor):
    payload = core.parse_document(form)
    if payload['kind'] not in core.OPENING_KINDS:
        # Preserve fingerprints of ordinary requests created before this
        # additive upgrade so an interrupted form can still replay safely.
        payload.pop('opening_cutoff')
        payload.pop('opening_confirmation_ref')
    key = token(form.get('idempotency_key'))
    digest = fingerprint(payload)
    try:
        with db() as c:
            lock(c)
            prior = replay(c, 'finance_documents', key, digest)
            if prior:
                return prior['id']
            identity(c, payload['owner_id'], payload['counterparty_id'])
            if payload['shipment_id']:
                shipment = c.execute('SELECT id,is_test FROM shipments WHERE id=%s', (payload['shipment_id'],)).fetchone()
                if not shipment or shipment['is_test']:
                    fail('الشحنة غير موجودة أو تجريبية؛ لا تسجل كحركة مالية فعلية')
            previous = c.execute("SELECT id FROM finance_documents WHERE owner_id=%s AND source_ref=%s AND source_locator=%s AND kind=%s AND status IN ('void','reversed') ORDER BY id DESC LIMIT 1",
                (payload['owner_id'],payload['source_ref'],payload['source_locator'],payload['kind'])).fetchone()
            if previous:
                payload['supersedes_id'] = previous['id']
            keys = list(payload)
            row = c.execute('INSERT INTO finance_documents('+','.join(keys)+',idempotency_key,payload_hash,created_by,created_at) VALUES('
                + ','.join(['%s'] * (len(keys)+4)) + ') RETURNING *', tuple(payload.values())+(key,digest,actor,utcnow())).fetchone()
            audit(c, actor, 'document_created', 'document', row['id'], payload)
            return row['id']
    except UniqueViolation:
        fail('صف المصدر مسجل مسبقًا؛ لا تُكرر الحركة من نفس المصدر', 409)


def document(c, doc_id):
    item = c.execute('SELECT * FROM finance_documents WHERE id=%s FOR UPDATE', (doc_id,)).fetchone()
    if not item:
        fail('الحركة غير موجودة', 404)
    return item


def rounding_required(item):
    return bool(item['currency'] and Decimal(core.display_minor(item['amount_minor'], item['currency'])) != item['source_amount'])


def guard_opening_period(c, item):
    """Called under the transaction lock at both review and posting.

    No automatic conversion of old detail, gross claims or settlements. A single
    approved net opening establishes an inclusive historical cutoff for this
    exact owner/counterparty/currency AND receivable/payable side only.
    """
    side = core.KINDS[item['kind']][0]
    existing = c.execute('''SELECT id,kind,opening_cutoff FROM finance_documents
        WHERE owner_id=%s AND counterparty_id=%s AND currency=%s AND status='posted' AND id<>%s''',
        (item['owner_id'],item['counterparty_id'],item['currency'],item['id'])).fetchall()
    if item['kind'] in core.OPENING_KINDS:
        if any(core.KINDS[d['kind']][0] == side for d in existing):
            fail('يجب اعتماد الرصيد الافتتاحي قبل حركات الجانب المحدد من الذمم؛ يوجد رصيد افتتاحي أو حركات مرحّلة للحساب', 409)
    else:
        for prior in existing:
            if prior['kind'] in core.OPENING_KINDS and core.KINDS[prior['kind']][0] == side and item['document_date'] <= prior['opening_cutoff']:
                fail('الحركة ضمن الفترة المشمولة بالرصيد الافتتاحي؛ يمنع إعادة تسجيل المطالبات أو التسويات التاريخية', 409)


def review_document(doc_id, actor, form):
    reason = core.clean(form.get('reason'), 1000)
    if form.get('confirmation') != '1':
        fail('أكد مراجعة هوية الأطراف والمصدر وعدم تكرار الحركة')
    with db() as c:
        lock(c)
        item = document(c, doc_id)
        if item['status'] == 'reviewed':
            return
        if item['status'] != 'draft':
            fail('المراجعة متاحة للمسودة فقط', 409)
        identity(c, item['owner_id'], item['counterparty_id'])
        issues = core.validation_issues(item)
        if issues:
            fail('؛ '.join(issues))
        guard_opening_period(c, item)
        opening_ack = item['kind'] in core.OPENING_KINDS and form.get('opening_ack') == '1'
        if item['kind'] in core.OPENING_KINDS and not opening_ack:
            fail('أكد صافي الرصيد الافتتاحي وتاريخ القطع وشمول التسويات السابقة وعدم تكرارها')
        if rounding_required(item) and form.get('rounding_ack') != '1':
            fail('أكد فرق تقريب المصدر إلى أصغر وحدة للعملة؛ الأصل محفوظ')
        c.execute("UPDATE finance_documents SET status='reviewed',reviewed_by=%s,reviewed_at=%s,rounding_ack=%s,opening_review_ack=%s WHERE id=%s",
                  (actor, utcnow(), form.get('rounding_ack') == '1', opening_ack, doc_id))
        audit(c, actor, 'document_reviewed', 'document', doc_id, {'source_amount': item['source_amount'], 'amount_minor': item['amount_minor'], 'currency': item['currency'], 'rounding_ack': form.get('rounding_ack') == '1', 'opening_cutoff':item['opening_cutoff'], 'opening_confirmation_ref':item['opening_confirmation_ref'], 'opening_review_ack':opening_ack, 'reason': reason})


def post_document(doc_id, actor, form):
    reason = core.clean(form.get('reason'), 1000)
    if form.get('confirmation') != '1':
        fail('يلزم اعتماد إداري صريح لترحيل الحركة')
    try:
        with db() as c:
            lock(c)
            item = document(c, doc_id)
            if item['status'] == 'posted':
                return
            if item['status'] != 'reviewed':
                fail('راجع الحركة قبل الترحيل', 409)
            identity(c, item['owner_id'], item['counterparty_id'])
            issues = core.validation_issues(item)
            if issues:
                fail('؛ '.join(issues))
            guard_opening_period(c, item)
            if item['kind'] in core.OPENING_KINDS and (not item['opening_review_ack'] or form.get('opening_ack') != '1'):
                fail('يلزم اعتماد صريح لصافي الرصيد الافتتاحي والفترة التاريخية المشمولة')
            if rounding_required(item) and not item['rounding_ack']:
                fail('تقريب المصدر غير معتمد')
            side, sign = core.KINDS[item['kind']]
            # Duplicate business-event gate across payable/expense and cash/non-cash credits.
            duplicates = c.execute('''SELECT id,kind FROM finance_documents
                WHERE owner_id=%s AND counterparty_id=%s AND economic_ref=%s AND status='posted' AND id<>%s''',
                (item['owner_id'], item['counterparty_id'], item['economic_ref'], doc_id)).fetchall()
            if any(core.KINDS[d['kind']] == (side, sign) for d in duplicates):
                fail('الحركة الاقتصادية مرحّلة مسبقًا؛ راجع المصدر بدل مضاعفة الرصيد', 409)
            c.execute("UPDATE finance_documents SET status='posted',posted_by=%s,posted_at=%s WHERE id=%s", (actor,utcnow(),doc_id))
            c.execute('INSERT INTO finance_entries(document_id,phase,side,signed_minor,actor_id,created_at) VALUES(%s,%s,%s,%s,%s,%s)',
                      (doc_id, 'posting', side, sign * item['amount_minor'], actor, utcnow()))
            audit(c, actor, 'document_posted', 'document', doc_id, {'side':side, 'signed_minor':sign * item['amount_minor'], 'currency':item['currency'], 'kind':item['kind'], 'opening_cutoff':item['opening_cutoff'], 'opening_confirmation_ref':item['opening_confirmation_ref'], 'reason':reason})
    except UniqueViolation:
        fail('الحركة مرحّلة مسبقًا؛ راجع مرجع الحركة', 409)


def reverse_document(doc_id, actor, form):
    reason = core.clean(form.get('reason'), 1000, True)
    if form.get('confirmation') != '1':
        fail('يلزم اعتماد إداري صريح للعكس')
    with db() as c:
        lock(c)
        item = document(c, doc_id)
        if item['status'] == 'reversed':
            if item['reversal_reason'] != reason:
                fail('تم عكس الحركة سابقًا بسبب مختلف', 409)
            return
        if item['status'] != 'posted':
            fail('العكس متاح للحركات المرحّلة فقط', 409)
        if item['kind'] in core.OPENING_KINDS:
            later = c.execute("SELECT kind FROM finance_documents WHERE owner_id=%s AND counterparty_id=%s AND currency=%s AND status='posted' AND id<>%s",(item['owner_id'],item['counterparty_id'],item['currency'],doc_id)).fetchall()
            if any(core.KINDS[d['kind']][0] == core.KINDS[item['kind']][0] for d in later):
                fail('راجع واعكس الحركات اللاحقة من جانب الذمم نفسه أولًا قبل تصحيح الرصيد الافتتاحي', 409)
        side, sign = core.KINDS[item['kind']]
        c.execute('INSERT INTO finance_entries(document_id,phase,side,signed_minor,actor_id,created_at) VALUES(%s,%s,%s,%s,%s,%s)',
                  (doc_id, 'reversal', side, -sign * item['amount_minor'], actor, utcnow()))
        affected = c.execute('''UPDATE finance_allocations SET reversed_at=%s WHERE (credit_id=%s OR document_id=%s)
            AND reversed_at IS NULL RETURNING id''', (utcnow(),doc_id,doc_id)).fetchall()
        for allocation in affected:
            audit(c, actor, 'allocation_reversed', 'allocation', allocation['id'], {'trigger_document_id':doc_id, 'reason':reason})
        c.execute("UPDATE finance_documents SET status='reversed',reversed_by=%s,reversed_at=%s,reversal_reason=%s WHERE id=%s", (actor,utcnow(),reason,doc_id))
        audit(c, actor, 'document_reversed', 'document', doc_id, {'reason':reason, 'allocations_reversed':[a['id'] for a in affected]})


def void_document(doc_id, actor, form):
    reason = core.clean(form.get('reason'), 1000, True)
    with db() as c:
        lock(c)
        item = document(c, doc_id)
        if item['status'] == 'void':
            return
        if item['status'] not in ('draft','reviewed'):
            fail('استخدم العكس للحركة المرحّلة', 409)
        c.execute("UPDATE finance_documents SET status='void',reversed_by=%s,reversed_at=%s,reversal_reason=%s WHERE id=%s", (actor,utcnow(),reason,doc_id))
        audit(c, actor, 'document_voided', 'document', doc_id, reason)


def allocated(c, doc_id):
    return c.execute('''SELECT COALESCE(SUM(amount_minor),0) n FROM finance_allocations
        WHERE (credit_id=%s OR document_id=%s) AND reversed_at IS NULL''', (doc_id,doc_id)).fetchone()['n']


def create_allocation(form, actor):
    try:
        credit_id, doc_id = int(form.get('credit_id','')), int(form.get('document_id',''))
    except (ValueError, TypeError):
        fail('مراجع التخصيص غير صالحة')
    key = token(form.get('idempotency_key'))
    with db() as c:
        lock(c)
        credit, debit = document(c, credit_id), document(c, doc_id)
        amount = core.exact_minor(form.get('amount'), credit['currency'])
        digest = fingerprint({'credit_id':credit_id,'document_id':doc_id,'amount_minor':amount})
        prior = replay(c, 'finance_allocations', key, digest)
        if prior:
            return prior['id']
        if credit['status'] != 'posted' or debit['status'] != 'posted':
            fail('التخصيص بين حركتين مرحّلتين فقط', 409)
        if any(credit[k] != debit[k] for k in ('owner_id','counterparty_id','currency')):
            fail('يلزم تطابق المالك والطرف والعملة؛ لا تحويل عملات أو مقاصة بين جهات')
        side, sign = core.KINDS[credit['kind']]
        if sign != -1 or core.KINDS[debit['kind']] != (side, 1):
            fail('يجب تخصيص تسوية إلى مطالبة أو التزام من نفس الجانب')
        if debit['kind'] in core.OPENING_KINDS and credit['document_date'] <= debit['opening_cutoff']:
            fail('لا يخصص للرصيد الافتتاحي قبض أو تسوية ضمن الفترة التاريخية المشمولة', 409)
        if amount > credit['amount_minor'] - allocated(c, credit_id) or amount > debit['amount_minor'] - allocated(c, doc_id):
            fail('المبلغ يتجاوز الرصيد غير المخصص', 409)
        item = c.execute('''INSERT INTO finance_allocations(credit_id,document_id,amount_minor,idempotency_key,payload_hash,created_by,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id''', (credit_id,doc_id,amount,key,digest,actor,utcnow())).fetchone()
        audit(c, actor, 'allocation_created', 'allocation', item['id'], {'credit_id':credit_id,'document_id':doc_id,'amount_minor':amount,'currency':credit['currency']})
        return item['id']


def create_rule(form, actor):
    try:
        owner_id = int(form.get('owner_id',''))
    except (ValueError, TypeError):
        fail('اختر مالك الحساب')
    rate = core.decimal_amount(form.get('rate'))
    if rate > 100 or rate.as_tuple().exponent < -4:
        fail('النسبة من أكبر من صفر إلى 100 وبحد أقصى أربع منازل')
    payload = {'owner_id':owner_id, 'company_scope':core.clean(form.get('company_scope'), 1000, True),
               'rate':rate, 'basis':core.clean(form.get('basis'), 1000, True)}
    key, digest = token(form.get('idempotency_key')), fingerprint(payload)
    with db() as c:
        lock(c)
        prior = replay(c, 'finance_entitlement_rules', key, digest)
        if prior:
            return prior['id']
        identity(c, owner_id)
        row = c.execute('''INSERT INTO finance_entitlement_rules(owner_id,company_scope,rate,basis,idempotency_key,payload_hash,created_by,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''', tuple(payload.values())+(key,digest,actor,utcnow())).fetchone()
        audit(c, actor, 'inactive_rule_created', 'rule', row['id'], payload)
        return row['id']


def enrich(c, item):
    item = dict(item)
    side, sign = core.KINDS[item['kind']]
    item.update(side=side, direction='credit' if sign < 0 else 'debit', validation_issues=core.validation_issues(item),
                rounding_required=rounding_required(item))
    item['source_amount'] = str(item['source_amount'])
    amount = item['amount_minor']
    used = allocated(c, item['id'])
    item['amount_display'] = core.display_minor(amount, item['currency']) if item['currency'] else item['source_amount'] + ' (عملة غير مؤكدة)'
    item['rounded_amount_display'] = item['amount_display']
    item['allocated_display'] = core.display_minor(used, item['currency']) if item['currency'] else '—'
    remaining = 0 if item['status'] in ('reversed','void') else amount-used if amount is not None else None
    item['remaining_display'] = core.display_minor(remaining, item['currency']) if item['currency'] else '—'
    return item


DOCUMENT_SELECT = '''SELECT d.*,o.name owner_name,p.name counterparty_name FROM finance_documents d
 JOIN finance_party_display o ON o.id=d.owner_id JOIN finance_party_display p ON p.id=d.counterparty_id'''


def audit_rows(c, doc_id=None):
    where = " WHERE a.entity_type='document' AND a.entity_id=%s" if doc_id else ''
    return c.execute('SELECT a.*,u.name actor_name FROM finance_audit a JOIN users u ON u.id=a.actor_id'+where+' ORDER BY a.id DESC LIMIT 100', (doc_id,) if doc_id else ()).fetchall()


def dashboard_data():
    with db() as c:
        parties = c.execute('SELECT * FROM finance_party_display ORDER BY kind,id').fetchall()
        documents = [enrich(c,d) for d in c.execute(DOCUMENT_SELECT+' ORDER BY d.id DESC LIMIT 200').fetchall()]
        summary = c.execute('''SELECT o.name owner_name,p.name counterparty_name,d.owner_id,d.counterparty_id,d.currency,
          COALESCE(SUM(e.signed_minor) FILTER(WHERE e.side='receivable'),0) receivable_minor,
          COALESCE(SUM(e.signed_minor) FILTER(WHERE e.side='payable'),0) payable_minor,
          COUNT(DISTINCT d.id) FILTER(WHERE d.status='posted' AND d.kind IN ('opening_payable','payable','expense')) payable_document_count
          FROM finance_entries e JOIN finance_documents d ON d.id=e.document_id
          JOIN finance_party_display o ON o.id=d.owner_id JOIN finance_party_display p ON p.id=d.counterparty_id
          WHERE d.status IN ('posted','reversed')
          GROUP BY d.owner_id,d.counterparty_id,o.name,p.name,d.currency ORDER BY o.name,p.name,d.currency''').fetchall()
        for item in summary:
            for side in ('receivable','payable'):
                item[side+'_display'] = core.display_minor(item[side+'_minor'], item['currency'])
        rules = c.execute('SELECT r.*,p.name owner_name FROM finance_entitlement_rules r JOIN finance_party_display p ON p.id=r.owner_id ORDER BY r.id DESC').fetchall()
        return parties, documents, summary, audit_rows(c), rules, core.owner_balance_totals(summary)


def detail_data(doc_id):
    with db() as c:
        item = c.execute(DOCUMENT_SELECT+' WHERE d.id=%s', (doc_id,)).fetchone()
        if not item:
            fail('الحركة غير موجودة',404)
        item = enrich(c,item)
        allocations = c.execute('SELECT * FROM finance_allocations WHERE credit_id=%s OR document_id=%s ORDER BY id', (doc_id,doc_id)).fetchall()
        for allocation in allocations:
            allocation['amount_display'] = core.display_minor(allocation['amount_minor'],item['currency'])
        candidates = []
        if item['status']=='posted':
            opposite = (item['side'], -core.KINDS[item['kind']][1])
            for candidate in c.execute(DOCUMENT_SELECT+" WHERE d.owner_id=%s AND d.counterparty_id=%s AND d.currency=%s AND d.status='posted' ORDER BY d.id", (item['owner_id'],item['counterparty_id'],item['currency'])).fetchall():
                if core.KINDS[candidate['kind']] == opposite and allocated(c,candidate['id']) < candidate['amount_minor']:
                    candidates.append(enrich(c,candidate))
        return item, allocations, audit_rows(c,doc_id), candidates


def statement_data(owner_id, counterparty_id, currency, side):
    currency = core.currency_code(currency)
    if side not in ('receivable','payable'):
        fail('جانب الكشف غير صالح')
    with db() as c:
        owner, party = identity(c, owner_id, counterparty_id)
        # Posting order is stable; reversal uses its own timestamp, never backdates history.
        entries = c.execute('''SELECT e.*,d.document_date,d.kind,d.source_ref,d.source_locator,d.invoice_ref,d.customs_ref,
            d.economic_ref,d.source_amount_raw,d.amount_basis,d.status,d.opening_cutoff,d.opening_confirmation_ref FROM finance_entries e
            JOIN finance_documents d ON d.id=e.document_id WHERE d.owner_id=%s AND d.counterparty_id=%s AND d.currency=%s AND e.side=%s
            ORDER BY e.id''', (owner_id,counterparty_id,currency,side)).fetchall()
        running = 0
        for entry in entries:
            running += entry['signed_minor']
            entry['id'] = entry['document_id']
            entry['status'] = 'reversal' if entry['phase']=='reversal' else 'posted'
            # Receivable increases are debits; payable increases are credits.
            accounting_sign = entry['signed_minor'] if side == 'receivable' else -entry['signed_minor']
            entry['debit_display'] = core.display_minor(max(accounting_sign,0), currency)
            entry['credit_display'] = core.display_minor(max(-accounting_sign,0), currency)
            entry['running_display'] = core.display_minor(running,currency)
        return owner, party, entries, core.display_minor(running,currency)
