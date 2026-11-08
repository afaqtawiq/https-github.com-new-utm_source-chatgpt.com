"""WhatsApp command agent for the Afaq team: Claude with real platform tools.

Verified team numbers (AFAQ_TEAM / WHATSAPP_COMMAND_OWNER, provider identity only) write or speak freely.
Claude picks tools and runs them; the reply states only what the tools actually did.

- Read tools and internal records (drivers, shipments, customers, declarations, daily prospects) run at once.
- Anything that leaves the company (WhatsApp to a customer/driver, email) is prepared and needs the manager's
  short confirmation «نفذ CODE» in the same chat; nothing external is sent on interpretation alone.
- Secrets (passwords, OTP codes, IBAN/card numbers) are never sent or stored by these tools.
"""
import contextvars
import json
import os
import re
import secrets

import httpx

from app.customs_policy import CUSTOMS_FIRST_POLICY

from app import command_ai
from app import whatsapp_admin as admin

MODEL = os.getenv('COMMAND_AGENT_MODEL') or os.getenv('COMMAND_AI_MODEL', 'claude-sonnet-5')
CHAT = contextvars.ContextVar('afaq_command_chat', default=None)   # (sender, conversation_id)
CONFIRM_PREFIX = '__agent_action__:'
SECRET = re.compile(r'كلمة\s*(?:ال)?سر|كلمة\s*المرور|password|passcode|رمز\s*(?:ال)?تحقق|\bOTP\b|IBAN|ايبان|آيبان|\bSA\d{2}[0-9A-Z]{18,22}\b|\b(?:\d[ -]?){13,19}\b', re.I)

TOOLS = [
    {'name': 'search', 'description': 'Find customers, drivers or shipments by name, phone or reference.',
     'input_schema': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}},
    {'name': 'report', 'description': 'Activity summary for today or the last week.',
     'input_schema': {'type': 'object', 'properties': {'period': {'type': 'string', 'enum': ['today', 'week']}}, 'required': ['period']}},
    {'name': 'list_recent', 'description': 'List the latest records of one kind.',
     'input_schema': {'type': 'object', 'properties': {'kind': {'type': 'string', 'enum': ['shipments', 'drivers', 'customers', 'declarations', 'prospects', 'mail']}}, 'required': ['kind']}},
    {'name': 'shipment_status', 'description': 'Status of one shipment by its reference.',
     'input_schema': {'type': 'object', 'properties': {'reference': {'type': 'string'}}, 'required': ['reference']}},
    {'name': 'tariff', 'description': 'Saudi customs tariff (HS code and duty) lookup; give up to 3 Arabic and 3 English phrasings.',
     'input_schema': {'type': 'object', 'properties': {'ar': {'type': 'array', 'items': {'type': 'string'}}, 'en': {'type': 'array', 'items': {'type': 'string'}}}}},
    {'name': 'customs_question', 'description': 'Answer a question about customs procedures, documents or requirements from the approved knowledge.',
     'input_schema': {'type': 'object', 'properties': {'question': {'type': 'string'}}, 'required': ['question']}},
    {'name': 'add_driver', 'description': 'Register a driver for load offers.',
     'input_schema': {'type': 'object', 'properties': {'name': {'type': 'string'}, 'phone': {'type': 'string'}, 'vehicle': {'type': 'string'}}, 'required': ['name', 'phone']}},
    {'name': 'add_shipment', 'description': 'Create a shipment record.',
     'input_schema': {'type': 'object', 'properties': {'reference': {'type': 'string'}, 'origin': {'type': 'string'}, 'destination': {'type': 'string'}}, 'required': ['reference', 'origin', 'destination']}},
    {'name': 'add_customer', 'description': 'Add a customer/lead to the customer list.',
     'input_schema': {'type': 'object', 'properties': {'name': {'type': 'string'}, 'phone': {'type': 'string'}, 'email': {'type': 'string'}, 'city': {'type': 'string'}, 'notes': {'type': 'string'}}, 'required': ['name']}},
    {'name': 'update_declaration', 'description': 'Update a customs declaration follow-up: find it by customer name, bill or declaration number; set stage and optionally the declaration number. Stages: submitted, under_review, inspection, duties_due, duties_paid, released, delivered, closed.',
     'input_schema': {'type': 'object', 'properties': {'find': {'type': 'string'}, 'stage': {'type': 'string'}, 'declaration_number': {'type': 'string'}, 'note': {'type': 'string'}}, 'required': ['find', 'stage']}},
    {'name': 'record_declaration_billing', 'description': 'Record a customs declaration in the accounts using the owner-approved billing rules (الياسمين / عمران / سلة الرحائب) and create finance drafts. Use when staff send a declaration number with invoice value and the issuing company, e.g. «بيان 5 بتاريخ 3 الياسمين قيمة الفاتورة 500 الرسوم 200». supplier = the company that issued the invoice (from the Emirates). party = importer/exporter (default سلة الرحائب). duty = total FASAH fees if given.',
     'input_schema': {'type': 'object', 'properties': {'number': {'type': 'string'}, 'kind': {'type': 'string', 'enum': ['import', 'export']}, 'supplier': {'type': 'string'}, 'invoice_no': {'type': 'string'}, 'invoice_value': {'type': 'string'}, 'duty': {'type': 'string'}, 'other': {'type': 'string'}, 'party': {'type': 'string'}, 'date': {'type': 'string', 'description': 'YYYY-MM-DD, or just the day number if only a day was given'}}, 'required': ['number']}},
    {'name': 'customer_balance', 'description': 'Outstanding receivable balance of a customer/counterparty in finance (posted only), oldest claim, last payment, drafts awaiting approval. e.g. «كم على الياسمين».',
     'input_schema': {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']}},
    {'name': 'record_payment', 'description': 'Record money RECEIVED from a customer as a finance draft receipt (owner posts it later). e.g. «استلمنا 50000 من الياسمين حوالة 123». date YYYY-MM-DD optional; ref = transfer/cheque reference.',
     'input_schema': {'type': 'object', 'properties': {'name': {'type': 'string'}, 'amount': {'type': 'string'}, 'date': {'type': 'string'}, 'ref': {'type': 'string'}}, 'required': ['name', 'amount']}},
    {'name': 'broadcast_load', 'description': 'Offer a freight load to ALL registered drivers on WhatsApp (or only Saudi/UAE numbers). Use when staff send a load to be distributed to drivers. driver_price = the price offered to the driver. If only the owner price is given, ask the manager for the commission of this load (never assume a fixed commission). Needs the manager confirmation code before sending.',
     'input_schema': {'type': 'object', 'properties': {'origin': {'type': 'string'}, 'destination': {'type': 'string'}, 'weight': {'type': 'string', 'description': 'tons'}, 'driver_price': {'type': 'string'}, 'unloading': {'type': 'string'}, 'payment': {'type': 'string'}, 'audience': {'type': 'string', 'enum': ['all', 'saudi', 'uae']}}, 'required': ['origin', 'destination', 'weight', 'driver_price']}},
    {'name': 'negotiate_owner', 'description': 'Start a natural WhatsApp conversation with a load owner (by phone) to collect the load details and price. origin/destination = the route if known. load_ref = a captured Naqliat load (e.g. «فاوض NQ-12») — then phone/route come from it. Needs the manager confirmation code before the first message.',
     'input_schema': {'type': 'object', 'properties': {'phone': {'type': 'string'}, 'origin': {'type': 'string'}, 'destination': {'type': 'string'}, 'load_ref': {'type': 'string'}}}},
    {'name': 'assign_driver', 'description': 'Manager assigns a broadcast load to a driver who accepted it and links driver and load owner (each gets the other\'s contact). e.g. «اسند AFT-7 للسائق 0551234567»; without a phone the first driver who accepted. Needs the confirmation code.',
     'input_schema': {'type': 'object', 'properties': {'ref': {'type': 'string'}, 'driver_phone': {'type': 'string'}}, 'required': ['ref']}},
    {'name': 'load_acceptances', 'description': 'Which drivers accepted a broadcast load (e.g. «مين وافق على AFT-7»).',
     'input_schema': {'type': 'object', 'properties': {'ref': {'type': 'string'}}, 'required': ['ref']}},
    {'name': 'track_container', 'description': 'Register or update a container to follow until it is RETURNED EMPTY: last free day (free_until, YYYY-MM-DD), delivery date, return place (depot/yard), customer and driver phones, bill, confirmed daily cost. test=true for a trial container. e.g. «سجل الحاوية MSKU1234567 العميل الحياة آخر يوم مجاني 10/11 الإرجاع ساحة جدة سائق 0551234567».',
     'input_schema': {'type': 'object', 'properties': {'container': {'type': 'string'}, 'customer': {'type': 'string'}, 'customer_phone': {'type': 'string'}, 'driver_phone': {'type': 'string'}, 'bill': {'type': 'string'}, 'free_until': {'type': 'string'}, 'delivered_on': {'type': 'string'}, 'return_place': {'type': 'string'}, 'daily_cost': {'type': 'string'}, 'test': {'type': 'boolean'}}, 'required': ['container']}},
    {'name': 'container_update', 'description': 'Container status: delivered (to customer), driver_returned (driver SAYS it was returned — stays open), returned (ONLY with proof: EIR/receipt number or who confirmed, put it in note).',
     'input_schema': {'type': 'object', 'properties': {'container': {'type': 'string'}, 'event': {'type': 'string', 'enum': ['delivered', 'driver_returned', 'returned']}, 'note': {'type': 'string'}, 'date': {'type': 'string'}}, 'required': ['container', 'event']}},
    {'name': 'containers_status', 'description': 'Open containers not yet returned, with days left / overdue and cost so far. Optional filter (container or customer).',
     'input_schema': {'type': 'object', 'properties': {'filter': {'type': 'string'}}}},
    {'name': 'party_statement', 'description': 'Monthly account statement of a client (عمران/إقبال، الياسمين، سلة الرحائب) from recorded declaration claims: count, total claim, payments, net, printable link. month = YYYY-MM. e.g. «كشف عمران لشهر اكتوبر».',
     'input_schema': {'type': 'object', 'properties': {'party': {'type': 'string'}, 'month': {'type': 'string'}}, 'required': ['party', 'month']}},
    {'name': 'runner_task', 'description': 'Manager only. Create a task for the WORK COMPUTER browser: download_test (first trial), read_page (url), download_file (url), fill_form (url + fields [{label,value}] + optional submit_label; submitting waits for the manager approval), fasah_declarations (which import/export, party = importer/exporter name filter e.g. «سلة», since YYYY-MM-DD, pages 1-20 — read-only list; new unbilled سلة الرحائب declarations are then prepared for billing with a confirmation code), fasah_details (number — read one declaration invoice and fees). Allowed sites only; never passwords/OTP.',
     'input_schema': {'type': 'object', 'properties': {'kind': {'type': 'string', 'enum': ['download_test', 'read_page', 'download_file', 'fill_form', 'fasah_declarations', 'fasah_details']}, 'url': {'type': 'string'}, 'which': {'type': 'string'}, 'party': {'type': 'string'}, 'since': {'type': 'string'}, 'pages': {'type': 'string'}, 'number': {'type': 'string'}, 'fields': {'type': 'array', 'items': {'type': 'object', 'properties': {'label': {'type': 'string'}, 'value': {'type': 'string'}}}}, 'submit_label': {'type': 'string'}}, 'required': ['kind']}},
    {'name': 'fasah_tracking', 'description': 'Live status of open FASAH declarations read by the work computer every 2 hours (under review, waiting duties, inspection, released). Optional filter (number or importer name). e.g. «حالة البيانات في فسح» «وش وضع بيانات سلة».',
     'input_schema': {'type': 'object', 'properties': {'filter': {'type': 'string'}}}},
    {'name': 'fasah_importer_phone', 'description': 'Manager only. Save the WhatsApp number of an importer AS ITS NAME APPEARS IN FASAH, so status-change messages to that customer can be prepared (sent only after «نفذ»). e.g. «رقم المستورد سلة الرحائب 0551234567».',
     'input_schema': {'type': 'object', 'properties': {'name': {'type': 'string'}, 'phone': {'type': 'string'}}, 'required': ['name', 'phone']}},
    {'name': 'prospect_replies', 'description': 'Which contacted prospect companies replied to the agent outreach and how (interested, asked price, not interested, stop), with quotes prepared. Optional days (default 7). e.g. «مين رد من العملاء المحتملين» «ردود حملة التعريف».',
     'input_schema': {'type': 'object', 'properties': {'days': {'type': 'string'}}}},
    {'name': 'customer_care', 'description': 'Existing customers programme: transport offer to customers we clear for, and win-back messages to customers inactive 60+ days. action=prepare prepares a batch now (sent only after «نفذ»); action=status shows results. e.g. «جهز رسائل العملاء» «نتائج رسائل العملاء الحاليين».',
     'input_schema': {'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['prepare', 'status']}}, 'required': ['action']}},
    {'name': 'runner_deny', 'description': 'Manager refuses a work-computer approval request («ارفض الطلب 4»).',
     'input_schema': {'type': 'object', 'properties': {'approval': {'type': 'string'}}, 'required': ['approval']}},
    {'name': 'runner_status', 'description': 'Steps, result and files of a work-computer task (latest if no id).',
     'input_schema': {'type': 'object', 'properties': {'task': {'type': 'string'}}}},
    {'name': 'runner_stop', 'description': 'Stop a work-computer task now («أوقف المهمة 3»).',
     'input_schema': {'type': 'object', 'properties': {'task': {'type': 'string'}}, 'required': ['task']}},
    {'name': 'whatsapp_templates', 'description': 'Approval status in Meta of the WhatsApp templates (owner inquiry, driver offer, marketing). e.g. «حالة القوالب».',
     'input_schema': {'type': 'object', 'properties': {}}},
    {'name': 'approve_owner_load', 'description': 'Manager approves a collected load file and sets OUR commission; the load is then offered to all drivers at owner price minus commission. e.g. «اعتمد الحمولة 4 عمولة 300».',
     'input_schema': {'type': 'object', 'properties': {'file': {'type': 'string'}, 'commission': {'type': 'string'}}, 'required': ['file', 'commission']}},
    {'name': 'owner_load_status', 'description': 'Show what was collected so far from a load owner (file number).',
     'input_schema': {'type': 'object', 'properties': {'file': {'type': 'string'}}, 'required': ['file']}},
    {'name': 'broadcast_status', 'description': 'Delivery status of a load broadcast (e.g. «حالة الإرسال AFT-12»); latest if no reference.',
     'input_schema': {'type': 'object', 'properties': {'ref': {'type': 'string'}}}},
    {'name': 'approve_prospects', 'description': "Approve today's pending daily prospects for contact (all, or those whose company name contains a text).",
     'input_schema': {'type': 'object', 'properties': {'company_contains': {'type': 'string'}}}},
    {'name': 'list_employees', 'description': 'List company employees registered for the WhatsApp team lane.',
     'input_schema': {'type': 'object', 'properties': {}}},
    {'name': 'add_employee', 'description': 'Register a company employee (name, mobile, job title) so they can use team commands on WhatsApp. Manager only; needs the confirmation code.',
     'input_schema': {'type': 'object', 'properties': {'name': {'type': 'string'}, 'phone': {'type': 'string'}, 'title': {'type': 'string'}}, 'required': ['name', 'phone']}},
    {'name': 'remove_employee', 'description': "Stop an employee's WhatsApp team access (by name or phone). Manager only; needs the confirmation code.",
     'input_schema': {'type': 'object', 'properties': {'who': {'type': 'string'}}, 'required': ['who']}},
    {'name': 'send_whatsapp', 'description': 'Prepare a WhatsApp message to a team member (by name/department) or any phone number. It is sent only after the manager confirms with the code.',
     'input_schema': {'type': 'object', 'properties': {'to': {'type': 'string'}, 'text': {'type': 'string'}}, 'required': ['to', 'text']}},
    {'name': 'send_email', 'description': 'Prepare an email from the official mailbox. It is sent only after the manager confirms with the code.',
     'input_schema': {'type': 'object', 'properties': {'to': {'type': 'string'}, 'subject': {'type': 'string'}, 'body': {'type': 'string'}}, 'required': ['to', 'subject', 'body']}},
]

SYSTEM = ('أنت مساعد الأوامر لفريق آفاق طويق (تخليص جمركي ونقل، جدة) على واتساب. المرسل موظف موثق من الفريق. '
          'نفّذ ما يطلبه باستخدام الأدوات المتاحة، ويمكنك استدعاء أكثر من أداة. اللهجات السعودية والخليجية شائعة '
          '(سواق=سائق، ضيف=أضف، وريني=اعرض). لا تخترع بيانات غير موجودة في الرسالة أو نتائج الأدوات، وإذا نقصت معلومة '
          'ضرورية فاسأل عنها باختصار. لا تقل إنك نفذت شيئًا لم تؤكده نتيجة أداة. أدوات الإرسال تجهز الرسالة فقط وتعيد رمز '
          'تأكيد؛ اذكر للمرسل أن يكتب «نفذ» مع الرمز. إذا طلب شيئًا لا تغطيه الأدوات (حذف، دفع، تعديل أسعار معتمدة، نشر) '
          'فاشرح أنه يتم من البرنامج. الرد النهائي بالعربية، قصير وواضح، بلا مقدمات.')


# ------------------------------------------------------------------ tool implementations

def _clean(value, limit=300):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]


def _member():
    try:
        from app.team import ROLE
        return ROLE.get() or {}
    except ImportError:
        return {}


def _pending(c, action):
    chat = CHAT.get()
    if not chat:
        return 'تعذر تجهيز التأكيد في هذه المحادثة.'
    token = secrets.token_hex(3).upper()
    c.execute('''INSERT INTO whatsapp_voice_pending(token,sender,conversation_id,command,expires_at)
        VALUES(%s,%s,%s,%s,NOW()+INTERVAL '15 minutes')''', (token, chat[0], chat[1], CONFIRM_PREFIX + json.dumps(action, ensure_ascii=False)))
    return token


def tool_search(c, a):
    return command_ai._search(c, a.get('query'))


def tool_report(c, a):
    return command_ai._report(c, a.get('period'))


def tool_list_recent(c, a):
    kind = a.get('kind')
    def table_exists(name):
        return c.execute('SELECT to_regclass(%s) t', (name,)).fetchone()['t'] is not None
    if kind == 'shipments':
        return admin.afaaq_command(c, 'اعرض الشحنات')
    if kind == 'drivers':
        return admin.afaaq_command(c, 'اعرض السائقين')
    if kind == 'customers':
        return admin.afaaq_command(c, 'اعرض العملاء')
    if kind == 'declarations' and table_exists('customs_declarations'):
        from app.declarations import STAGE_LABELS
        rows = c.execute("SELECT id,customer_name,declaration_number,bill_number,stage FROM customs_declarations WHERE stage NOT IN ('closed') ORDER BY updated_at DESC LIMIT 10").fetchall()
        return '\n'.join(f"{r['id']} · {r['customer_name']} · بيان {r['declaration_number'] or '-'} · {STAGE_LABELS.get(r['stage'], r['stage'])}" for r in rows) or 'لا توجد بيانات قيد المتابعة.'
    if kind == 'prospects' and table_exists('daily_prospects'):
        rows = c.execute("SELECT status,COUNT(*) n FROM daily_prospects WHERE batch_date=(now() AT TIME ZONE 'Asia/Riyadh')::date GROUP BY status").fetchall()
        return 'مرشحو اليوم: ' + (', '.join(f"{r['status']}: {r['n']}" for r in rows) or 'لا يوجد')
    if kind == 'mail' and table_exists('mail_agent_items'):
        rows = c.execute('''SELECT a.category,a.action,i.subject,i.sender FROM mail_agent_items a JOIN spacemail_inbox i ON i.id=a.inbox_id
            WHERE a.action IN ('draft','preview','send_failed') ORDER BY a.inbox_id DESC LIMIT 8''').fetchall()
        return ('رسائل بريد تنتظر الاعتماد:\n' + '\n'.join(f"· {r['subject']} — {r['sender']}" for r in rows)) if rows else 'لا توجد رسائل بريد تنتظر الاعتماد.'
    return 'لا تتوفر هذه القائمة.'


def tool_shipment_status(c, a):
    return admin.shipment_status(c, re.sub(r'[^A-Za-z0-9_-]', '', str(a.get('reference') or ''))[:60])


def tool_tariff(c, a):
    from app import tariff_lookup
    return tariff_lookup.as_text(tariff_lookup.search_many(a.get('ar'), a.get('en')))


def tool_customs_question(c, a):
    return command_ai.answer_question(a.get('question')) or 'تعذر الإجابة الآن.'


def tool_add_driver(c, a):
    name, number = _clean(a.get('name'), 100), re.sub(r'[^\d+]', '', str(a.get('phone') or ''))
    command = f'اضف السائق {name} ورقمه {number}' + (f" ومركبته {_clean(a.get('vehicle'), 100)}" if _clean(a.get('vehicle')) else '')
    return admin.afaaq_command(c, admin.normalize(command))


def tool_add_shipment(c, a):
    reference = re.sub(r'[^A-Za-z0-9_-]', '', str(a.get('reference') or ''))[:60]
    if not reference:
        return 'مرجع الشحنة مطلوب بأحرف وأرقام إنجليزية.'
    return admin.afaaq_command(c, admin.normalize(f"اضف شحنة مرجع {reference} من {_clean(a.get('origin'), 100)} الى {_clean(a.get('destination'), 100)}"))


def tool_add_customer(c, a):
    from app.marketing_content import email_address, whatsapp_number
    name = _clean(a.get('name'), 200)
    if len(name) < 2:
        return 'اسم العميل مطلوب.'
    phone = whatsapp_number(a.get('phone')) if a.get('phone') else ''
    email = email_address(a.get('email')) if a.get('email') else ''
    if a.get('phone') and not phone:
        return 'رقم الجوال غير صالح.'
    if phone and c.execute("SELECT 1 FROM accounts WHERE regexp_replace(coalesce(phone,''),'[^0-9]','','g')=%s", (phone.lstrip('+'),)).fetchone():
        return 'هذا الرقم مسجل لعميل بالفعل؛ لم أنشئ سجلًا مكررًا.'
    notes = 'أضيف بأمر واتساب من ' + (_member().get('name') or 'الفريق') + (' | ' + _clean(a.get('city'), 60) if a.get('city') else '') + (' | ' + _clean(a.get('notes'), 300) if a.get('notes') else '')
    row = c.execute('''INSERT INTO accounts(name,country,status,notes,phone,email,created_at,updated_at)
        VALUES(%s,'السعودية','lead',%s,%s,%s,NOW(),NOW()) RETURNING id''', (name, notes, phone or None, email or None)).fetchone()
    return f"تمت إضافة العميل {name} برقم سجل {row['id']}."


def tool_update_declaration(c, a):
    from app.declarations import STAGE_LABELS, customer_message
    stage = a.get('stage')
    if stage not in STAGE_LABELS:
        return 'المرحلة غير معروفة. المراحل: ' + '، '.join(STAGE_LABELS.values())
    find = _clean(a.get('find'), 100)
    rows = c.execute('''SELECT * FROM customs_declarations WHERE stage<>'closed' AND (customer_name ILIKE %s OR bill_number=%s OR declaration_number=%s)
        ORDER BY updated_at DESC LIMIT 3''', ('%' + find + '%', find, find)).fetchall()
    if not rows:
        return f'لم أجد بيانًا مفتوحًا يطابق «{find}».'
    if len(rows) > 1:
        return 'وجدت أكثر من بيان؛ حدد رقم البيان أو البوليصة:\n' + '\n'.join(f"{r['id']} · {r['customer_name']} · بوليصة {r['bill_number']}" for r in rows)
    d = dict(rows[0])
    number = _clean(a.get('declaration_number'), 60)
    if number and not re.fullmatch(r'[A-Za-z0-9\-/]{3,60}', number):
        return 'رقم البيان غير صالح.'
    d['declaration_number'] = number or d['declaration_number']
    message = customer_message(dict(d, stage=stage), stage) if stage != d['stage'] else ''
    c.execute('UPDATE customs_declarations SET stage=%s,declaration_number=%s,updated_at=NOW() WHERE id=%s', (stage, d['declaration_number'], d['id']))
    c.execute('''INSERT INTO customs_declaration_events(declaration_id,stage,note,customer_message,message_status,created_by,created_at)
        VALUES(%s,%s,%s,%s,%s,(SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1),NOW())''',
              (d['id'], stage, 'واتساب: ' + _clean(a.get('note'), 300), message, 'draft' if message else 'none'))
    return (f"تم تحديث بيان {d['customer_name']} إلى «{STAGE_LABELS[stage]}»" + (f" ورقم البيان {d['declaration_number']}" if d['declaration_number'] else '') +
            ('. رسالة العميل جاهزة في صفحة البيان للإرسال.' if message else '.'))


def tool_record_declaration_billing(c, a):
    import datetime as _dt
    from app import billing_rules
    from app.prospect_autopilot import system_user
    date = None
    raw = str(a.get('date') or '').strip()
    if raw:
        try:
            date = _dt.date.fromisoformat(raw)
        except ValueError:
            today = _dt.date.today()
            date = today.replace(day=int(raw)) if raw.isdigit() and 1 <= int(raw) <= 28 else None
    try:
        _, _, message = billing_rules.record({**a, 'date': date}, system_user())
    except ValueError as exc:
        return 'تعذر التسجيل: ' + str(exc)
    return message


def tool_customer_balance(c, a):
    from app import collections_desk as collections
    return collections.customer_balance_text(a.get('name'))


def tool_record_payment(c, a):
    import datetime as _dt
    from app import collections_desk as collections
    from app.prospect_autopilot import system_user
    try:
        date = _dt.date.fromisoformat(str(a.get('date'))) if a.get('date') else None
    except ValueError:
        date = None
    return collections.record_payment(a.get('name'), a.get('amount'), system_user(), date=date, ref=_clean(a.get('ref'), 80))


def tool_broadcast_load(c, a):
    from app import load_broadcast
    load, count, error = load_broadcast.prepare(a)
    if error:
        return error + '. أكمل البيانات وأعد الطلب.'
    if not count:
        return 'لا يوجد سائقون مسجلون لهذه الفئة.'
    token = _pending(c, {'tool': 'broadcast_load', **load})
    return (f"جاهز لإرسال الحمولة إلى {count} سائق:\n" + load_broadcast.message('AFT-…', load) +
            f"\nللإرسال اكتب: نفذ {token}")


def tool_negotiate_owner(c, a):
    from app import owner_negotiation
    ref = re.search(r'NQ\s*-?\s*(\d+)', str(a.get('load_ref') or ''), re.I)
    if ref:
        from app import transport_desk
        transport_desk.init()
        chat = CHAT.get()
        if not chat:
            return 'تعذر تجهيز التأكيد في هذه المحادثة.'
        return transport_desk.offer_negotiation(c, chat[0], chat[1], int(ref.group(1)))
    phone = owner_negotiation.digits(a.get('phone'))
    if len(phone) < 11:
        return 'رقم صاحب الحمولة غير واضح.'
    if not _clean(a.get('origin')) or not _clean(a.get('destination')):
        return 'اذكر مسار الحمولة (من وإلى) لأفتح المحادثة برسالة معتمدة.'
    token = _pending(c, {'tool': 'negotiate_owner', 'phone': phone, 'origin': _clean(a.get('origin'), 60), 'destination': _clean(a.get('destination'), 60)})
    return f"جاهز لبدء المحادثة مع صاحب الحمولة +{phone} بخصوص {_clean(a.get('origin'))} → {_clean(a.get('destination'))}. للبدء اكتب: نفذ {token}"


def tool_approve_owner_load(c, a):
    from app import owner_negotiation
    if not _member().get('manager'):
        return 'اعتماد الحمولة وتحديد العمولة للمدير فقط.'
    return owner_negotiation.approve(a.get('file'), a.get('commission'), _member().get('name') or '')


def tool_owner_load_status(c, a):
    import json as _json
    from app import owner_negotiation
    owner_negotiation.init()
    m = re.search(r'\d+', str(a.get('file') or ''))
    row = c.execute('SELECT * FROM owner_negotiations WHERE id=%s', (int(m.group(0)),)).fetchone() if m else None
    if not row:
        return 'لا يوجد ملف بهذا الرقم.'
    return f"ملف {row['id']} — الحالة: {row['status']}\n" + (owner_negotiation.summary(_json.loads(row['fields'] or '{}')) or 'لا تفاصيل بعد.')


def tool_assign_driver(c, a):
    from app import transport_desk
    if not _member().get('manager'):
        return 'إسناد الحمولة للسائق للمدير فقط.'
    chat = CHAT.get()
    if not chat:
        return 'تعذر تجهيز التأكيد في هذه المحادثة.'
    return transport_desk.prepare_assign(c, chat[0], chat[1], a.get('ref'), a.get('driver_phone') or '')


def tool_load_acceptances(c, a):
    from app import transport_desk
    transport_desk.init()
    m = re.search(r'(\d+)', str(a.get('ref') or ''))
    if not m:
        return 'اذكر رقم الحمولة مثل AFT-7.'
    rows = transport_desk.accepted_list(c, int(m.group(1)))
    if not rows:
        return f'لم يوافق أي سائق على AFT-{m.group(1)} بعد.'
    return f'الموافقون على AFT-{m.group(1)}:\n' + '\n'.join(f"• {r.get('driver_name') or 'سائق'} +{r['phone']}" + (f" — {r['vehicle_type']}" if r.get('vehicle_type') else '') for r in rows)


def tool_track_container(c, a):
    from app import container_returns
    return container_returns.track(a, _member().get('name') or '')


def tool_container_update(c, a):
    from app import container_returns
    return container_returns.update(a, _member().get('name') or '')


def tool_containers_status(c, a):
    from app import container_returns
    return container_returns.status_text(a.get('filter') or '')


def tool_fasah_tracking(c, a):
    from app import fasah_tracking
    return fasah_tracking.status_text(a.get('filter') or '')


def tool_fasah_importer_phone(c, a):
    if not _member().get('manager'):
        return 'حفظ أرقام العملاء للمتابعة للمدير فقط.'
    from app import fasah_tracking
    return fasah_tracking.save_contact(a.get('name'), a.get('phone'), _member().get('name') or '')


def tool_prospect_replies(c, a):
    from app import prospect_replies
    days = int(re.sub(r'\D', '', str(a.get('days') or '7')) or 7)
    return prospect_replies.status_text(max(1, min(days, 60)))


def tool_customer_care(c, a):
    from app import customer_care
    if a.get('action') == 'prepare':
        if not _member().get('manager'):
            return 'تجهيز رسائل العملاء للمدير فقط.'
        return customer_care.prepare() or 'لا يوجد عملاء مستحقون للرسائل الآن (الكل تواصلنا معه مؤخرًا أو بدون رقم).'
    return customer_care.status_text()


def tool_party_statement(c, a):
    from app import statement_import
    m = re.search(r'(\d{4})-(\d{1,2})', str(a.get('month') or ''))
    if not m:
        return 'اذكر الشهر، مثل 2026-10.'
    return statement_import.statement_text(a.get('party') or '', f'{m.group(1)}-{int(m.group(2)):02d}')


def tool_runner_task(c, a):
    from app import agent_runner
    if not _member().get('manager'):
        return 'مهام جهاز العمل للمدير فقط.'
    return agent_runner.create_task(a.get('kind'), {'url': a.get('url'), 'which': a.get('which'), 'fields': a.get('fields'),
                                                    'submit_label': a.get('submit_label'), 'party': a.get('party'), 'since': a.get('since'),
                                                    'pages': a.get('pages'), 'number': a.get('number')}, _member().get('name') or '')[1]


def tool_runner_deny(c, a):
    from app import agent_runner
    if not _member().get('manager'):
        return 'للمدير فقط.'
    m = re.search(r'\d+', str(a.get('approval') or ''))
    return agent_runner.decide(int(m.group(0)), False, _member().get('name') or 'المدير') if m else 'اذكر رقم الطلب.'


def tool_runner_status(c, a):
    from app import agent_runner
    if not _member().get('manager'):
        return 'تفاصيل مهام جهاز العمل للمدير فقط.'
    m = re.search(r'\d+', str(a.get('task') or ''))
    return agent_runner.task_text(int(m.group(0)) if m else None)


def tool_runner_stop(c, a):
    from app import agent_runner
    if not _member():
        return 'غير مخول.'
    m = re.search(r'\d+', str(a.get('task') or ''))
    return agent_runner.stop_task(int(m.group(0))) if m else 'اذكر رقم المهمة.'


def tool_whatsapp_templates(c, a):
    from app import transport_desk
    return transport_desk.templates_text()


def tool_broadcast_status(c, a):
    from app import load_broadcast
    return load_broadcast.status_text(a.get('ref'))


def tool_approve_prospects(c, a):
    from app import daily_prospects as dp
    contains = _clean(a.get('company_contains'), 100)
    rows = c.execute('''SELECT id FROM daily_prospects WHERE status='pending' AND batch_date=(now() AT TIME ZONE 'Asia/Riyadh')::date
        AND (%s='' OR company_name ILIKE %s) ORDER BY score DESC LIMIT 50''', (contains, '%' + contains + '%')).fetchall()
    if not rows:
        return 'لا يوجد مرشحون بانتظار المراجعة يطابقون الطلب.'
    user = c.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()['id']
    changed = dp.decide([r['id'] for r in rows], 'approve', user)
    return f'تم اعتماد {changed} من مرشحي اليوم للتواصل؛ روابط واتساب جاهزة في صفحة «مرشحو اليوم».'


def _employee_phone(value):
    from app.team import phone
    digits = phone(str(value or ''))
    return '+' + digits if re.fullmatch(r'9665\d{8}', digits or '') else ''


def tool_list_employees(c, a):
    from app.team import team
    members = team()
    if not members:
        return 'لا يوجد موظفون مسجلون.'
    return 'فريق آفاق المسجل على واتساب:\n' + '\n'.join(
        f"· {m['name'] or '—'}{' (' + m['role'] + ')' if m.get('role') else ''} · +{n}{' · مدير' if m.get('manager') else ''}" for n, m in members.items())


def tool_add_employee(c, a):
    if not _member().get('manager'):
        return 'إضافة الموظفين للمدير فقط.'
    name, title = _clean(a.get('name'), 100), _clean(a.get('title'), 100)
    number = _employee_phone(a.get('phone'))
    if len(name) < 2 or not number:
        return 'اسم الموظف ورقم جوال سعودي صحيح مطلوبان.'
    from app.team import team
    if number.lstrip('+') in team():
        return 'هذا الرقم مسجل في الفريق بالفعل.'
    token = _pending(c, {'tool': 'add_employee', 'name': name, 'phone': number, 'title': title})
    return f'جاهز لإضافة {name} ({title or "بدون مسمى"}) برقم {number} إلى فريق واتساب بصلاحيات موظف (ليس مدير). رمز التأكيد: {token}'


def tool_remove_employee(c, a):
    if not _member().get('manager'):
        return 'إيقاف الموظفين للمدير فقط.'
    who = _clean(a.get('who'), 100)
    number = _employee_phone(who)
    row = c.execute('SELECT id,name,phone FROM team_employees WHERE active AND (phone=%s OR name ILIKE %s) LIMIT 2', (number or '#', '%' + who + '%')).fetchall()
    if len(row) != 1:
        return 'حدد الموظف برقمه؛ لم أجد تطابقًا واحدًا في الموظفين المضافين من واتساب (أعضاء الإعداد الأساسي يُعدّلون من الإعدادات).'
    token = _pending(c, {'tool': 'remove_employee', 'id': row[0]['id'], 'name': row[0]['name']})
    return f"جاهز لإيقاف صلاحية {row[0]['name']} ({row[0]['phone']}). رمز التأكيد: {token}"


def tool_send_whatsapp(c, a):
    text = _clean(a.get('text'), 900)
    if not text or not _clean(a.get('to')):
        return 'المستلم ونص الرسالة مطلوبان.'
    if SECRET.search(text):
        return 'لا أرسل كلمات مرور أو رموز تحقق أو أرقام حسابات وبطاقات عبر واتساب.'
    from app.manager_actions import resolve
    number, label = resolve(a.get('to'))
    if not number:
        return f'لم أتعرف على المستلم «{label}». اكتب رقمه أو اسمه كما في فريق آفاق.'
    token = _pending(c, {'tool': 'send_whatsapp', 'to': a.get('to'), 'text': text})
    return f'جاهزة للإرسال إلى {label} (+{number.lstrip("+")}): «{text}». رمز التأكيد: {token}'


def tool_send_email(c, a):
    from app.marketing_content import email_address
    to = email_address(a.get('to'))
    subject, body = _clean(a.get('subject'), 200), str(a.get('body') or '').strip()[:6000]
    if not to or not subject or len(body) < 10:
        return 'البريد والعنوان والنص مطلوبة.'
    if SECRET.search(subject + ' ' + body):
        return 'لا أرسل كلمات مرور أو رموز تحقق أو أرقام حسابات وبطاقات بالبريد.'
    token = _pending(c, {'tool': 'send_email', 'to': to, 'subject': subject, 'body': body})
    return f'البريد جاهز إلى {to} بعنوان «{subject}». رمز التأكيد: {token}'


HANDLERS = {t['name']: globals()['tool_' + t['name']] for t in TOOLS}
INTERNAL_WRITE = {'add_driver', 'add_shipment', 'add_customer', 'update_declaration', 'approve_prospects'}
EXTERNAL = {'send_whatsapp', 'send_email', 'add_employee', 'remove_employee'}


def execute_confirmed(c, payload):
    """Run a prepared external action after «نفذ CODE» from the same verified chat."""
    member = _member()
    if not member.get('manager'):
        return 'الإرسال خارج الشركة يحتاج تأكيد المدير؛ لم يُرسل شيء.'
    action = json.loads(payload)
    if action.get('tool') == 'add_employee':
        from app.employees import init
        init()
        row = c.execute('''INSERT INTO team_employees(name,short,phone,title,added_by) VALUES(%s,%s,%s,%s,%s)
            ON CONFLICT(phone) DO UPDATE SET active=TRUE,name=EXCLUDED.name,title=EXCLUDED.title,updated_at=NOW() RETURNING id''',
            (action['name'], ' '.join(action['name'].split()[:2]) if re.match(r'^[اأ]بو\s', action['name']) else action['name'].split()[0],
             action['phone'], action.get('title') or '', member.get('name') or '')).fetchone()
        return f"✅ أُضيف {action['name']} إلى فريق آفاق (رقم {action['phone']}). يقدر الآن يرسل أوامر للوكيل من واتساب بصلاحيات موظف."
    if action.get('tool') == 'remove_employee':
        c.execute('UPDATE team_employees SET active=FALSE,updated_at=NOW() WHERE id=%s', (action['id'],))
        return f"✅ أُوقفت صلاحية {action['name']} على واتساب."
    if action.get('tool') == 'send_whatsapp':
        from app.manager_actions import send_message
        return send_message(c, {'to': action['to'], 'text': action['text']})
    if action.get('tool') == 'record_bank_payments':
        from app import bank_reconcile
        return bank_reconcile.record(int(action['batch']), 'مطابقة كشف البنك — ' + (member.get('name') or 'المدير'))
    if action.get('tool') == 'customer_care_send':
        from app import customer_care
        return customer_care.start_send(action['batch'])
    if action.get('tool') == 'negotiate_owner':
        from app import owner_negotiation
        return owner_negotiation.start(action, member.get('name') or '')
    if action.get('tool') == 'record_billing':
        import datetime as _dt
        from app import billing_rules
        from app.prospect_autopilot import system_user
        out = []
        for d in action.get('items') or []:
            d = dict(d)
            if d.get('date') and isinstance(d['date'], str):
                for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
                    try:
                        d['date'] = _dt.datetime.strptime(d['date'], fmt).date()
                        break
                    except ValueError:
                        continue
                else:
                    d['date'] = None
            try:
                out.append('• ' + billing_rules.record(d, system_user())[2].split('\n')[0] + (' — ' + str(d.get('number')) if d.get('number') else ''))
            except Exception as exc:
                out.append('• ' + str(d.get('number')) + ': ' + str(exc)[:100])
        return '✅ ' + str(action.get('label') or 'التسجيل') + '\n' + '\n'.join(out) + '\nالقيود مسودات في صفحة المالية بانتظار ترحيلك.'
    if action.get('tool') == 'runner_approve':
        from app import agent_runner
        return agent_runner.decide(action['approval_id'], True, member.get('name') or 'المدير')
    if action.get('tool') == 'publish_video':
        from app import video_publish
        return video_publish.publish(action['video_id'], member.get('name') or '')
    if action.get('tool') == 'assign_driver':
        from app import transport_desk
        return transport_desk.assign(action)
    if action.get('tool') == 'broadcast_load':
        from app import load_broadcast
        return load_broadcast.start(action, member.get('name') or '')
    if action.get('tool') == 'send_email':
        from app import spacemail
        user = c.execute('''SELECT s.user_id FROM spacemail_connections s JOIN users u ON u.id=s.user_id
            WHERE s.enabled AND s.address=%s AND u.role='admin' ORDER BY s.user_id LIMIT 1''', (spacemail.ADDRESS,)).fetchone()
        if not user:
            return 'البريد الرسمي غير متصل؛ لم يُرسل شيء.'
        try:
            mid = spacemail.send(user['user_id'], action['to'], action['subject'], action['body'])
        except Exception as exc:
            return 'تعذر إرسال البريد (' + type(exc).__name__ + '). لم أعد المحاولة.'
        c.execute("INSERT INTO activity(user_id,action,entity_type,summary,created_at) VALUES(%s,'whatsapp_command_email','email',%s,NOW())",
                  (user['user_id'], 'إلى ' + action['to'] + ': ' + action['subject']))
        return f"✅ أُرسل البريد إلى {action['to']} من {spacemail.ADDRESS}."
    return 'إجراء غير معروف؛ لم يُنفذ شيء.'


# ------------------------------------------------------------------ the loop

def call_model(messages, system):
    key = os.getenv('ANTHROPIC_API_KEY', '')
    body = {'model': MODEL, 'max_tokens': 1200, 'system': system, 'tools': TOOLS, 'messages': messages}
    with httpx.Client(timeout=45) as client:
        response = client.post('https://api.anthropic.com/v1/messages', json=body,
                               headers={'x-api-key': key, 'anthropic-version': '2023-06-01'})
        response.raise_for_status()
    return response.json()


def run_agent(c, raw):
    if command_ai.LEGACY_MODEL_DISABLED.get():
        return None
    # Do not allow the team model to guess product conformity from static text.
    # Actions mentioning SABER retain the existing tool and confirmation route.
    if command_ai.is_saber_information_question(raw):
        return command_ai.answer_saber_question(raw)
    if not os.getenv('ANTHROPIC_API_KEY'):
        return None
    member = _member()
    history = []
    try:
        from app.team import CONTEXT
        for item in ((CONTEXT.get() or {}).get('history') or [])[-4:]:
            history.append(f"الموظف: {item['command'][:400]}\nالمساعد: {item['reply'][:400]}")
    except ImportError:
        pass
    system = SYSTEM + CUSTOMS_FIRST_POLICY + ('\nالمرسل: ' + (member.get('name') or 'عضو الفريق') + ('، وهو المدير.' if member.get('manager') else '، ليس المدير؛ رسائل العملاء الخارجية تحتاج تأكيد المدير.'))
    if history:
        system += '\nآخر المحادثة للسياق فقط:\n' + '\n'.join(history)
    messages = [{'role': 'user', 'content': raw[:2000]}]
    for _ in range(6):
        try:
            data = call_model(messages, system)
        except (httpx.HTTPError, ValueError, KeyError):
            return None
        content = data.get('content') or []
        uses = [b for b in content if b.get('type') == 'tool_use']
        if not uses:
            text = ''.join(b.get('text', '') for b in content if b.get('type') == 'text').strip()
            return text[:3500] or None
        messages.append({'role': 'assistant', 'content': content})
        results = []
        for use in uses:
            name, args = use.get('name'), use.get('input') or {}
            handler = HANDLERS.get(name)
            if not handler:
                output = 'أداة غير معروفة.'
            else:
                try:
                    c.execute('SAVEPOINT command_agent_tool')
                    output = handler(c, args)
                    c.execute('RELEASE SAVEPOINT command_agent_tool')
                except Exception as exc:
                    c.execute('ROLLBACK TO SAVEPOINT command_agent_tool')
                    output = 'تعذر تنفيذ الأداة: ' + type(exc).__name__
            results.append({'type': 'tool_result', 'tool_use_id': use['id'], 'content': str(output)[:3000]})
        messages.append({'role': 'user', 'content': results})
    return 'نفذت الخطوات المتاحة لكن الطلب طويل؛ قسّمه إلى أوامر أقصر.'


# ------------------------------------------------------------------ wiring

_previous_run_ai_command = command_ai.run_ai_command


def run_ai_command(c, raw):
    reply = run_agent(c, raw)
    return reply if reply else _previous_run_ai_command(c, raw)


command_ai.run_ai_command = run_ai_command

_previous_run_command = admin.run_command


def run_command(c, raw, event_id):
    if str(raw).startswith(CONFIRM_PREFIX):
        return execute_confirmed(c, str(raw)[len(CONFIRM_PREFIX):])
    return _previous_run_command(c, raw, event_id)


admin.run_command = run_command

_previous_admin_reply = admin.admin_reply


async def admin_reply(c, payload, sender):
    token = CHAT.set((sender, (payload.get('conversation') or {}).get('id')))
    try:
        return await _previous_admin_reply(c, payload, sender)
    finally:
        CHAT.reset(token)


admin.admin_reply = admin_reply
