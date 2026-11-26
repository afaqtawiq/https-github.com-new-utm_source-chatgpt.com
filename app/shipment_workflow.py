"""Owner (22 Nov 2026): the office must run a shipment end to end like a real clearance office:
  1) check the importer's FASAH authorization (active / expiring / expired / none) → ask the importer to issue or renew it
     with our establishment name and licence number;
  2) check the documents → ask for whatever is missing;
  3) check the arrival date → send the customer the arrival report;
  4) print the declaration from FASAH (desktop runner, read-only) → send it to the customer;
  5) ask the shipping line for the delivery order (D/O);
  6) then duties → release → trucking → delivery to the warehouse → empty container returned to the line.

Every message to the customer or the line is prepared with a «نفذ CODE» for the manager (never sent on its own).
The checklist lives on the shipment file (app.shipment_files) so every employee sees where the shipment stands.
"""
import datetime as dt
import json
import re

from app.storage import db, utcnow

RIYADH = dt.timezone(dt.timedelta(hours=3))
COMPANY = 'مؤسسة آفاق طويق للتخليص الجمركي'
LICENSE = '2513'
CONTACT = '0530130435'
DOCS = [('bl', 'بوليصة الشحن'), ('invoice', 'الفاتورة التجارية'), ('packing', 'قائمة التعبئة (Packing List)'),
        ('origin', 'شهادة المنشأ')]
DOC_AR = dict(DOCS)
KIND_TO_DOC = {'shipping_document': 'bl', 'commercial_invoice': 'invoice', 'packing_list': 'packing',
               'certificate_of_origin': 'origin'}
DOC_WORDS = {'bl': ('بوليص', 'bill', 'b/l'), 'invoice': ('فاتور', 'invoice'), 'packing': ('تعبئ', 'packing'),
             'origin': ('منشأ', 'origin')}
PREPARED_HOURS = 20
_READY = False
GENERIC = {'مؤسسه', 'شركه', 'للتجاره', 'التجاريه', 'التجاره', 'المحدوده', 'محدوده', 'for', 'trading', 'co', 'company', 'est',
           'ltd', 'the', 'and', 'وشركاه', 'شركة', 'مؤسسة'}


def init():
    global _READY
    if _READY:
        return
    from app import shipment_files
    shipment_files.init()
    with db() as c:
        c.execute("ALTER TABLE shipment_files ADD COLUMN IF NOT EXISTS docs TEXT NOT NULL DEFAULT '[\"bl\"]'")
        c.execute("ALTER TABLE shipment_files ADD COLUMN IF NOT EXISTS steps TEXT NOT NULL DEFAULT '{}'")
    _READY = True


# ------------------------------------------------------------------ helpers
def _norm(text):
    text = re.sub(r'[إأآ]', 'ا', str(text or '').lower())
    text = text.replace('ة', 'ه').replace('ى', 'ي')
    return re.sub(r'[^\w\s]', ' ', text)


def _token_sets(name):
    """Token sets of the Arabic part and the Latin part of a name (B/Ls often carry both)."""
    text = str(name or '')
    out = []
    for part in (' '.join(re.findall(r'[\u0600-\u06FF]+', text)), ' '.join(re.findall(r'[A-Za-z]+', text))):
        words = [w[2:] if w.startswith('ال') and len(w) > 4 else w for w in _norm(part).split()]
        words = {w for w in words if len(w) > 2 and w not in GENERIC}
        if words:
            out.append(words)
    return out


def same_party(a, b):
    for ta in _token_sets(a):
        for tb in _token_sets(b):
            small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
            common = small & big
            if len(common) >= max(1, min(len(small), 2)) and len(common) / len(small) >= 0.66:
                return True
    return False


def _steps(row):
    try:
        return json.loads(row.get('steps') or '{}')
    except ValueError:
        return {}


def _docs(row):
    try:
        return json.loads(row.get('docs') or '["bl"]')
    except ValueError:
        return ['bl']


def _save(row_id, steps=None, docs=None, stage=None, log=None):
    from app.shipment_files import _log
    with db() as c:
        row = c.execute('SELECT * FROM shipment_files WHERE id=%s', (row_id,)).fetchone()
        c.execute('''UPDATE shipment_files SET steps=COALESCE(%s,steps), docs=COALESCE(%s,docs), stage=COALESCE(%s,stage),
            history=%s, updated_at=%s WHERE id=%s''',
                  (json.dumps(steps, ensure_ascii=False) if steps is not None else None,
                   json.dumps(docs) if docs is not None else None, stage,
                   _log(row, log) if log else row['history'], utcnow(), row_id))


def _mark(row_id, key, status, **extra):
    with db() as c:
        row = c.execute('SELECT steps FROM shipment_files WHERE id=%s', (row_id,)).fetchone()
    steps = _steps(row)
    steps[key] = dict(steps.get(key) or {}, status=status, at=dt.datetime.now(RIYADH).isoformat(timespec='minutes'), **extra)
    _save(row_id, steps=steps)
    return steps


def _fresh(step):
    try:
        at = dt.datetime.fromisoformat(step.get('at'))
    except (TypeError, ValueError):
        return False
    return (dt.datetime.now(RIYADH) - at).total_seconds() < PREPARED_HOURS * 3600


def _eta(row):
    return row['eta'].astimezone(RIYADH).strftime('%d/%m/%Y الساعة %H:%M') if row.get('eta') else 'غير مؤكد بعد'


def _hello(row):
    return f"السلام عليكم{' أ. ' + row['contact_name'] if row.get('contact_name') else ''}،\nمعكم آفاق طويق للتخليص الجمركي بخصوص شحنتكم — بوليصة {row['bill_no']}."


def _sign():
    return f'\n\nآفاق طويق للتخليص الجمركي والنقل — ترخيص {LICENSE}\nللتواصل: {CONTACT} · info@afaqtawiqs.net'


# ------------------------------------------------------------------ 1) authorization
def authorization(row):
    """(state, line). state: active / expiring / expired / missing / unknown."""
    try:
        from app import fasah_authorizations as fa
        fa.init()
    except Exception:
        return 'unknown', 'تعذر فتح سجل التفاويض.'
    today = dt.datetime.now(RIYADH).date()
    with db() as c:
        rows = c.execute('SELECT * FROM fasah_authorizations').fetchall()
        last = c.execute('SELECT MAX(updated_at) t FROM fasah_authorizations').fetchone()['t']
    if not rows:
        return 'unknown', 'لم تُقرأ قائمة التفاويض من فسح بعد.'
    hits = [r for r in rows if same_party(row['customer'], r['importer'])]
    stamp = last.astimezone(RIYADH).strftime('%d/%m %H:%M') if last else '—'
    if not hits:
        return 'missing', f'لا يوجد تفويض باسم العميل في قائمة فسح (آخر قراءة {stamp}).'
    best = max(hits, key=lambda r: r.get('end_date') or dt.date.min)
    end = best.get('end_date')
    if not end:
        return 'active', f"يوجد تفويض ({best['importer']}) لكن تاريخ انتهائه غير ظاهر — آخر قراءة {stamp}."
    left = (end - today).days
    if left < 0:
        return 'expired', f"التفويض منتهٍ منذ {end.isoformat()} ({best['importer']})."
    if left <= 30:
        return 'expiring', f"التفويض ساري حتى {end.isoformat()} (باقي {left} يوم) — يُفضّل التجديد."
    return 'active', f"✅ التفويض ساري حتى {end.isoformat()} (باقي {left} يوم)."


def authorization_message(row, state):
    why = {'expired': 'تفويضكم لنا في منصة فسح منتهٍ',
           'expiring': 'تفويضكم لنا في منصة فسح قرب ينتهي',
           'missing': 'ما ظهر لنا تفويض منكم في منصة فسح'}.get(state, 'نحتاج تفويضكم في منصة فسح')
    return (_hello(row) + f'\n\n{why}، ونحتاجه قبل تقديم البيان الجمركي. نأمل إصدار/تجديد التفويض للمخلص التالي:'
            f'\n• اسم المؤسسة: {COMPANY}\n• رقم الترخيص: {LICENSE}'
            '\n\nوإفادتنا بعد الإصدار حتى نقدّم البيان قبل وصول الشحنة ونتجنب رسوم الأرضيات. شاكرين لكم.' + _sign())


# ------------------------------------------------------------------ 2) documents
def missing_docs(row):
    have = set(_docs(row))
    return [k for k, _ in DOCS if k not in have]


def documents_message(row, missing):
    items = '\n'.join('• ' + DOC_AR[k] for k in missing)
    return (_hello(row) + f'\n\nلتجهيز البيان الجمركي ينقصنا المستندات التالية:\n{items}'
            '\n\nنأمل إرسالها (PDF) على هذا الرقم أو البريد. وإذا البضاعة تحتاج شهادة مطابقة (سابر) أو فسح الغذاء والدواء '
            'نبلغكم بها بعد مراجعة البند.' + _sign())


def note_document(fields):
    """A document was read (WhatsApp/office). If it belongs to an open shipment file, tick it on the checklist."""
    init()
    kind = KIND_TO_DOC.get((fields or {}).get('document_kind'))
    title = ' '.join(str(fields.get(k) or '') for k in ('document_title', 'title', 'summary')).lower()
    if not kind:
        kind = next((k for k, words in DOC_WORDS.items() if any(w in title for w in words)), None)
    if not kind:
        return None
    from app.shipment_files import _bill
    bill = _bill(fields.get('bill_no'))
    with db() as c:
        rows = c.execute("SELECT * FROM shipment_files WHERE stage NOT IN ('closed','returned')").fetchall()
    party = fields.get('consignee') or fields.get('importer') or fields.get('buyer') or ''
    targets = [r for r in rows if bill and r['bill_no'] == bill] or \
        [r for r in rows if party and same_party(party, r['customer'])]
    for row in targets[:4]:
        docs = _docs(row)
        if kind not in docs:
            docs.append(kind)
            _save(row['id'], docs=docs, log='استلمنا ' + DOC_AR[kind])
    return '، '.join(r['bill_no'] for r in targets[:4]) or None


# ------------------------------------------------------------------ 3) arrival report
def arrival_message(row):
    boxes = json.loads(row['containers'] or '[]')
    lines = [_hello(row), '', '🚢 تقرير وصول الشحنة:',
             f"• الخط الملاحي: {row.get('shipping_line') or '—'}",
             f"• السفينة: {row.get('vessel') or '—'} {row.get('voyage') or ''}".rstrip(),
             f"• من {row.get('pol') or '—'} إلى {row.get('pod') or 'ميناء جدة الإسلامي'}",
             f'• موعد الوصول المتوقع: {_eta(row)}',
             f"• الحاويات ({len(boxes)}): {'، '.join(boxes) if boxes else '—'}",
             '', _arrival_tail(row)]
    return '\n'.join(lines) + _sign()


def _transit(row):
    """(destination_ar, exit_port) when the file is transit, else None (owner, 26 Nov 2026)."""
    if (row.get('movement') or '') != 'transit':
        return None
    from app import customs_movement as cm
    code = row.get('destination') or ''
    return cm.COUNTRIES.get(code, ('خارج السعودية',))[0], cm.EXIT_PORT.get(code, '')


def _arrival_tail(row):
    transit = _transit(row)
    if transit:
        return (f'نتابع الوصول وبيان العبور (الترانزيت) ونبلغكم بكل مرحلة حتى خروج الشحنة إلى {transit[0]}'
                + (f' عبر {transit[1]}' if transit[1] else '') + '.')
    return 'نتابع الوصول والبيان الجمركي ونبلغكم بكل مرحلة حتى تسليم البضاعة في مستودعكم.'


# ------------------------------------------------------------------ 4) declaration print
def declaration_message(row, link):
    return (_hello(row) + f"\n\n📄 تم تقديم البيان الجمركي رقم {row['declaration_no']} على منصة فسح، وهذه نسخة البيان:\n{link}"
            '\n\nنتابع المعاينة وسداد الرسوم والفسح ونبلغكم أولًا بأول.' + _sign())


def request_declaration_print(row, actor='فيصل'):
    from app import agent_runner
    tid, msg = agent_runner.create_task('fasah_release_notice', {'which': 'import', 'number': row['declaration_no'], 'pages': 5,
                                                                 'doc': 'declaration', 'bill': row['bill_no']}, actor)
    if tid:
        _mark(row['id'], 'declaration', 'printing', task=tid)
    return msg


def after_declaration_pdf(task, params, f):
    """Runner downloaded the declaration PDF: private link + a «نفذ» code to send it to the customer."""
    import secrets
    from app import fasah_docs
    from app.daily_poster import base_url
    fasah_docs.init()
    init()
    number = str(params.get('number') or '')
    token = secrets.token_urlsafe(18)
    with db() as c:
        c.execute('''INSERT INTO fasah_documents(number,kind,doc,task_id,file_id,token,status,created_at,expires_at)
            VALUES(%s,'import','declaration',%s,%s,%s,'ready',%s,%s)
            ON CONFLICT(number,kind,doc) DO UPDATE SET task_id=EXCLUDED.task_id,file_id=EXCLUDED.file_id,token=EXCLUDED.token,
            status='ready',expires_at=EXCLUDED.expires_at''',
                  (number, task['id'], f['id'], token, utcnow(), utcnow() + dt.timedelta(days=fasah_docs.LINK_DAYS)))
        row = c.execute('SELECT * FROM shipment_files WHERE bill_no=%s OR declaration_no=%s LIMIT 1',
                        (str(params.get('bill') or ''), number)).fetchone()
    link = base_url() + '/fasah/notice/' + token + '.pdf'
    if not row:
        return f'📄 نسخة البيان {number} جاهزة: {link}'
    _mark(row['id'], 'declaration', 'ready', link=link)
    lines = [f"📄 طبعت البيان {number} من فسح لشحنة {row['customer'] or row['bill_no']}:", link]
    code = _prepare(row, 'declaration', declaration_message(row, link), 'البيان الجمركي ' + number)
    lines.append(code or 'رقم/إيميل العميل غير مسجل في ملف الشحنة؛ أضفه ثم اكتب «سيّر الشحنة ' + row['bill_no'] + '».')
    return '\n'.join(lines)


# ------------------------------------------------------------------ 5) delivery order from the line
def line_contact(row):
    line = (row.get('shipping_line') or row.get('vessel') or '').split()
    if not line:
        return None
    try:
        with db() as c:
            if not c.execute("SELECT to_regclass('shipping_agent_contacts') t").fetchone()['t']:
                return None
            hits = c.execute('''SELECT a.name, k.email, k.purpose FROM shipping_agents a JOIN shipping_agent_contacts k ON k.agent_id=a.id
                WHERE a.name ILIKE %s AND k.email IS NOT NULL ORDER BY (k.purpose ILIKE '%%D/O%%') DESC, k.id''',
                             ('%' + line[0] + '%',)).fetchall()
    except Exception:
        return None
    return hits[0] if hits else None


def do_message(row):
    boxes = json.loads(row['containers'] or '[]')
    subject = f"Delivery Order request — B/L {row['bill_no']} — {row.get('vessel') or ''} {row.get('voyage') or ''}".strip()
    body = (f"Dear {row.get('shipping_line') or 'Line'} Import Team,\n\n"
            f"Kindly issue the Delivery Order for the below shipment and advise any charges due:\n"
            f"• B/L: {row['bill_no']}\n• Consignee: {row['customer']}\n"
            f"• Vessel/Voyage: {row.get('vessel') or '-'} {row.get('voyage') or ''}\n"
            f"• ETA: {row['eta'].astimezone(RIYADH).strftime('%d %b %Y %H:%M') if row.get('eta') else 'TBC'}\n"
            f"• Containers ({len(boxes)}): {', '.join(boxes) or '-'}\n"
            + (f"• Customs declaration: {row['declaration_no']}\n" if row.get('declaration_no') else '')
            + f"\nCustoms broker: Afaq Tuwaiq Customs Clearance (licence {LICENSE}).\n\nBest regards,\nAfaq Tuwaiq\n{CONTACT} · info@afaqtawiqs.net")
    return subject, body


# ------------------------------------------------------------------ pending (manager confirms with «نفذ CODE»)
def _chat(c):
    from app import command_agent
    chat = command_agent.CHAT.get()
    if chat and chat != command_agent.OFFICE_CHAT:
        return chat
    from app import transport_desk
    return transport_desk.manager_chat(c)


def _prepare(row, step, text, label, email_subject=None, to_line=None):
    """One code that sends `text` to the customer (WhatsApp + email when known) or to the line (email)."""
    from app import transport_desk
    action = {'tool': 'shipment_step', 'bill': row['bill_no'], 'step': step, 'text': text, 'label': label}
    if to_line:
        action.update(email=to_line, subject=email_subject, whatsapp='')
    else:
        action.update(whatsapp=row.get('phone') or '', email=row.get('email') or '',
                      subject=email_subject or f"{label} — بوليصة {row['bill_no']} — آفاق طويق")
    if not action['whatsapp'] and not action['email']:
        return ''
    with db() as c:
        chat = _chat(c)
        if not chat:
            return ''
        code = transport_desk.pending(c, chat[0], chat[1], action, 24 * 60)
    _mark(row['id'], step, 'prepared', code=code)
    where = ' + '.join(x for x in (('واتساب +' + action['whatsapp']) if action['whatsapp'] else '',
                                    ('إيميل ' + action['email']) if action['email'] else '') if x)
    return f'↳ لإرسال «{label}» ({where}) اكتب: نفذ {code}'


def execute(action):
    """After «نفذ CODE»: send to the customer/line and tick the step."""
    import asyncio
    import threading
    from contextvars import copy_context
    from app.shipment_files import find
    rows = find(action.get('bill'))
    if not rows:
        return 'ملف الشحنة غير موجود؛ لم يُرسل شيء.'
    row = rows[0]
    sent, errors = [], []
    if action.get('whatsapp'):
        from app import zernio_whatsapp as z
        box = {}

        def run():
            try:
                box['ok'] = asyncio.run(z.send(action['whatsapp'], action['text']))
            except Exception as error:
                box['error'] = error
        worker = threading.Thread(target=copy_context().run, args=(run,))
        worker.start()
        worker.join(60)
        if 'ok' in box:
            sent.append('واتساب')
        else:
            errors.append('واتساب: ' + (str(box.get('error'))[:120] if box.get('error') else 'لم يتأكد الإرسال'))
    if action.get('email'):
        try:
            from app import spacemail
            with db() as c:
                user = c.execute('''SELECT s.user_id FROM spacemail_connections s JOIN users u ON u.id=s.user_id
                    WHERE s.enabled AND s.address=%s AND u.role='admin' ORDER BY s.user_id LIMIT 1''', (spacemail.ADDRESS,)).fetchone()
            if not user:
                raise RuntimeError('البريد الرسمي غير متصل')
            spacemail.send(user['user_id'], action['email'], action.get('subject') or action.get('label') or 'آفاق طويق', action['text'])
            sent.append('إيميل')
        except Exception as error:
            errors.append('إيميل: ' + str(error)[:120])
    if sent:
        _mark(row['id'], action['step'], 'sent', via='+'.join(sent))
        _save(row['id'], log=f"أُرسل {action.get('label')} ({'+'.join(sent)})")
    return (f"✅ أُرسل «{action.get('label')}» عبر {' و'.join(sent)}." if sent else '❌ لم يُرسل شيء.') + \
        ('\n⚠️ ' + '\n⚠️ '.join(errors) if errors else '')


# ------------------------------------------------------------------ the run
def _sibling(row, key):
    """The same customer's other open file where this step was already prepared/sent (one request per customer)."""
    with db() as c:
        rows = c.execute("SELECT * FROM shipment_files WHERE id<>%s AND stage NOT IN ('closed','returned')", (row['id'],)).fetchall()
    for r in rows:
        s = _steps(r).get(key) or {}
        if same_party(r['customer'], row['customer']) and (s.get('status') == 'sent' or (s.get('status') == 'prepared' and _fresh(s))):
            return r['bill_no']
    return ''


def run(query, actor=''):
    """«سيّر الشحنة»: walk the checklist in order, prepare what is due, report every step with its owner."""
    init()
    from app.shipment_files import STAGE_AR, find
    rows = find(query)
    if not rows:
        return f'ما لقيت ملف شحنة لـ«{query}». أرسل البوليصة أولًا ويُفتح الملف تلقائيًا.'
    row = rows[0]
    steps = _steps(row)
    now = dt.datetime.now(RIYADH)
    out = [f"🧭 سير شحنة {row['customer'] or '؟'} — بوليصة {row['bill_no']}",
           f"📞 العميل: {row.get('contact_name') or '—'} {('+' + row['phone']) if row.get('phone') else ''} {row.get('email') or ''}".rstrip()]
    if not row.get('phone') and not row.get('email'):
        out.append('⚠️ لا يوجد جوال ولا إيميل للعميل في الملف — أضفه حتى أجهّز الرسائل.')

    def due(key):
        s = steps.get(key) or {}
        return s.get('status') not in ('sent', 'done') and not (s.get('status') == 'prepared' and _fresh(s))

    # 0) declaration type: the final consignee decides, not the Saudi port or notify party (owner, 26 Nov 2026)
    from app.shipment_files import movement_line
    out.append(movement_line(row))
    movement = row.get('movement') or ''
    if movement == 'review':
        out.append('⛔ أوقفت سير الشحنة حتى يُحسم نوع البيان؛ لم أجهّز أي رسالة للعميل أو الوكيل.')
        _save(row['id'], log=(actor + ': ' if actor else '') + 'سير الشحنة موقوف: نوع البيان غير محسوم')
        return '\n'.join(x for x in out if x is not None)
    transit = _transit(row)

    # 1) authorization
    state, line = ('transit', '') if transit else authorization(row)
    if transit:
        out.append(f'\n1️⃣ تفويض فسح: الشحنة ترانزيت إلى {transit[0]} — لا أجهّز طلب تفويض استيراد للمرسل إليه. '
                   'فيصل: حدّد الجهة التي يُقدَّم باسمها بيان العبور والضمان قبل التقديم.')
    else:
        out.append('\n1️⃣ تفويض فسح: ' + line)
    if state == 'transit':
        pass
    elif state == 'unknown':
        try:
            from app import fasah_authorizations
            out.append('   ' + fasah_authorizations.answer(row['customer'], actor or 'فيصل').split('\n')[-1])
        except Exception as exc:
            out.append('   تعذر طلب قراءة التفاويض: ' + type(exc).__name__)
    elif state == 'active':
        steps = _mark(row['id'], 'authorization', 'done')
    elif due('authorization') and _sibling(row, 'authorization'):
        out.append('   (طلب التفويض مجهّز/مرسل مع البوليصة ' + _sibling(row, 'authorization') + ')')
    elif due('authorization'):
        code = _prepare(row, 'authorization', authorization_message(row, state), 'طلب تجديد/إصدار التفويض')
        out.append('   ' + (code or 'جهّزت النص لكن لا يوجد رقم/إيميل للعميل.'))
    else:
        out.append('   (طلب التفويض ' + ('أُرسل' if (steps.get('authorization') or {}).get('status') == 'sent' else 'مجهّز ينتظر «نفذ»') + ')')

    # 2) documents
    missing = missing_docs(row)
    have = [DOC_AR[k] for k in _docs(row) if k in DOC_AR]
    out.append('\n2️⃣ المستندات: لدينا ' + ('، '.join(have) or '—') + ('؛ ناقص: ' + '، '.join(DOC_AR[k] for k in missing) if missing else ' ✅ مكتملة'))
    if missing and due('documents'):
        code = _prepare(row, 'documents', documents_message(row, missing), 'طلب المستندات الناقصة')
        out.append('   ' + (code or 'لا يوجد رقم/إيميل للعميل.'))
    out.append('   (فيصل: ' + ('راجع ضوابط العبور للبند والمسار؛ لا تطبق اشتراطات الاستيراد على الترانزيت)' if transit else
                                'راجع اشتراطات البند — سابر/الغذاء والدواء — بأداة import_requirements)'))

    # 3) arrival report
    out.append(f'\n3️⃣ الوصول: {_eta(row)}' + (f" — {row.get('vessel')}" if row.get('vessel') else ''))
    if row.get('eta') and due('arrival'):
        code = _prepare(row, 'arrival', arrival_message(row), 'تقرير وصول الشحنة')
        out.append('   ' + (code or 'لا يوجد رقم/إيميل للعميل.'))
    elif not row.get('eta'):
        out.append('   سلطان: تتبّع البوليصة لتحديد موعد الوصول.')
    else:
        out.append('   (التقرير ' + ('أُرسل ✅' if (steps.get('arrival') or {}).get('status') == 'sent' else 'مجهّز ينتظر «نفذ»') + ')')

    # 4) declaration
    dec = steps.get('declaration') or {}
    if transit and not row.get('declaration_no'):
        out.append('\n4️⃣ بيان العبور: لم يُسجل رقمه بعد — فيصل: قدّم بيان عبور (ترانزيت) في فسح بالضمان ومنفذ الخروج'
                   + (f' ({transit[1]} متوقع)' if transit[1] else '') + '، ثم سجّل رقمه في الملف.')
    elif transit and (steps.get('declaration_send') or {}).get('status') != 'sent' and dec.get('status') != 'ready':
        out.append(f"\n4️⃣ بيان العبور {row['declaration_no']}: اطبعه من فسح يدويًا؛ الطباعة التلقائية مخصصة لبيانات الاستيراد.")
    elif not row.get('declaration_no'):
        out.append('\n4️⃣ البيان الجمركي: لم يُسجل رقمه بعد — فيصل: قدّم البيان في فسح ثم سجّل رقمه في الملف، ويُطبع من فسح ويُجهّز للعميل تلقائيًا.')
    elif dec.get('status') == 'ready' and due('declaration_send'):
        out.append(f"\n4️⃣ البيان {row['declaration_no']}: النسخة جاهزة {dec.get('link')}")
        out.append('   ' + (_prepare(row, 'declaration_send', declaration_message(row, dec.get('link')), 'نسخة البيان الجمركي') or ''))
    elif dec.get('status') in ('printing',) and _fresh(dec):
        out.append(f"\n4️⃣ البيان {row['declaration_no']}: جهاز العمل يطبعه من فسح (المهمة #{dec.get('task')}).")
    elif (steps.get('declaration_send') or {}).get('status') == 'sent':
        out.append(f"\n4️⃣ البيان {row['declaration_no']}: أُرسلت نسخته للعميل ✅")
    else:
        out.append(f"\n4️⃣ البيان {row['declaration_no']}: " + request_declaration_print(row, actor or 'فيصل').split('\n')[0])

    # 5) delivery order
    contact = line_contact(row)
    arriving = row.get('eta') and row['eta'] - now <= dt.timedelta(days=3)
    out.append('\n5️⃣ إذن التسليم (D/O) من الوكيل الملاحي' + (f" ({contact['name']} — {contact['email']})" if contact else '') + ':')
    if (steps.get('delivery_order') or {}).get('status') == 'sent':
        out.append('   طُلب ✅ — ننتظر رد الوكيل والفاتورة.')
    elif not contact:
        out.append('   ما عندي إيميل الوكيل لهذا الخط — أضفه من صفحة وكلاء الملاحة.')
    elif not arriving:
        out.append('   يُطلب قبل الوصول بـ3 أيام.')
    elif due('delivery_order'):
        subject, body = do_message(row)
        out.append('   ' + (_prepare(row, 'delivery_order', body, 'طلب إذن التسليم من الوكيل', subject, contact['email']) or ''))

    # 6) the rest, by stage
    label, nxt = STAGE_AR.get(row['stage'], (row['stage'], ''))
    if transit:
        out.append(f'\n6️⃣ بعدها (ترانزيت): الضمان وفسح العبور ← خالد يسند شاحنة مرخّصة للعبور ← الخروج من '
                   f"{transit[1] or 'منفذ الخروج'} إلى {transit[0]} خلال المدة وبالمسار المحدد ← تسوية الضمان بعد إثبات الخروج "
                   '← سلطان يتابع إرجاع الحاوية حسب ترتيب الخط ← نورة تصدر الفاتورة وتقفل الملف.')
    else:
        out.append('\n6️⃣ بعدها: سداد الرسوم ← الفسح (إشعار الفسح يُنزل تلقائيًا) ← خالد يسند الشاحنات ← التسليم لمستودع العميل '
                   '← سلطان يرجّع الحاويات فارغة قبل آخر يوم مجاني ← نورة تصدر الفاتورة وتقفل الملف.')
    out.append(f'📍 المرحلة الحالية: {label} — {nxt}')
    _save(row['id'], log=(actor + ': ' if actor else '') + 'تشغيل سير الشحنة')
    return '\n'.join(x for x in out if x is not None)


def kickoff(bill):
    """A new shipment file was opened from a document: run the flow once and tell the manager."""
    try:
        text = run(bill, 'تلقائي')
    except Exception as exc:
        print('SHIPMENT_WORKFLOW', type(exc).__name__, str(exc)[:200], flush=True)
        return
    from app.agent_runner import notify
    notify(text)
