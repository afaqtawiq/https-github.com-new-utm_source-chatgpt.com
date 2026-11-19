"""Send a party's monthly statement (PDF) to that party's WhatsApp group (owner request, 19 Nov 2026).

«مدير المالية … يرسل كشف الياسمين إلى قروب الياسمين على الواتساب». The group is found among the agent number's own
WhatsApp conversations (a group conversation whose name contains the party's name). The statement is prepared,
shown with a confirmation code, and sent only after «نفذ CODE» — it goes to a customer group, so it is an external send.

WhatsApp rule (Meta/Zernio): the business number can only post in a group it belongs to, and a group appears in its
inbox only after a member wrote there once. When no such group is found the reply says exactly that.
"""
import hashlib
import re
import secrets
from urllib.parse import quote

KEYS = {'الياسمين': ('ياسمين',), 'عمران': ('عمران', 'اقبال'), 'سلة الرحائب': ('سله', 'رحائب', 'رحايب')}
NAME_FIELDS = ('name', 'participantName', 'title', 'groupName', 'subject', 'displayName')


def _fold(text):
    from app.billing_rules import fold
    return fold(text)


def group_name(row):
    for key in NAME_FIELDS:
        if isinstance(row.get(key), str) and row[key].strip():
            return row[key].strip()
    return ''


async def groups():
    """[(conversation_id, name)] of the WhatsApp group conversations on the agent number."""
    from app import zernio_whatsapp as z
    out, cursor, visited = [], None, set()
    async with z.client() as c:
        await z.validate_account(c)
        for _ in range(20):
            params = {'accountId': z.account_id(), 'platform': 'whatsapp', 'limit': 100}
            if cursor:
                params['cursor'] = cursor
            data = await z.read(c, '/inbox/conversations', params)
            for row in data.get('data') or []:
                if (isinstance(row, dict) and row.get('isGroup') and row.get('accountId') == z.account_id()
                        and row.get('platform', 'whatsapp') == 'whatsapp' and isinstance(row.get('id'), str)):
                    out.append((row['id'], group_name(row)))
            pagination = data.get('pagination') or {}
            cursor = pagination.get('nextCursor')
            if not pagination.get('hasMore') or not cursor or cursor in visited:
                break
            visited.add(cursor)
    return out


def match(found, party, hint=''):
    """The single group whose name contains the hint, else the party's name. None when none or ambiguous."""
    keys = [_fold(hint)] if hint and _fold(hint) else [_fold(k) for k in KEYS.get(party, (party,))]
    hits = [(cid, name) for cid, name in found if any(k and k in _fold(name) for k in keys)]
    return hits[0] if len(hits) == 1 else None


async def send_pdf(conversation_id, content, filename, caption):
    """One multipart POST of the PDF to the group conversation. Returns the provider message id."""
    from app import zernio_whatsapp as z
    key = 'wa-document-' + hashlib.sha256(content + conversation_id.encode() + secrets.token_bytes(8)).hexdigest()
    async with z.transport_batch() as batch:
        c = await batch.get_client()
        await z.validate_account(c)
        response = await c.post(z.BASE + '/inbox/conversations/' + quote(conversation_id, safe='') + '/messages',
                                data={'accountId': batch.account, 'message': caption},
                                files={'attachment': (filename, content, 'application/pdf')},
                                headers={'Idempotency-Key': key}, follow_redirects=False)
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400 or not isinstance(data, dict) or data.get('success') is not True:
        detail = ''
        if isinstance(data, dict):
            err = data.get('error') or data.get('message') or ''
            detail = (err.get('message') if isinstance(err, dict) else str(err))[:160]
        raise z.WhatsAppBlocked(f'رفض واتساب إرسال الملف للقروب (HTTP {response.status_code})' + (f': {detail}' if detail else ''))
    receipt = data.get('data') if isinstance(data.get('data'), dict) else {}
    return receipt.get('messageId') or ''


def _month(text):
    import datetime as dt
    m = re.search(r'(\d{4})-(\d{1,2})', str(text or ''))
    return f'{m.group(1)}-{int(m.group(2)):02d}' if m else dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).strftime('%Y-%m')


def prepare(party_text, month_text, hint, make_code):
    """Build the statement, find the group, return the confirmation text (nothing is sent here)."""
    from app import statement_import
    from app.transport_desk import run_async
    party = statement_import.party_from(party_text) or statement_import.party_from(hint)
    if not party:
        return 'اذكر الجهة: الياسمين أو عمران أو سلة الرحائب.'
    month = _month(month_text)
    s = statement_import.statement(party, month)
    if not s.get('lines'):
        return f'لا توجد بيانات مسجلة لـ{party} في {month}، فلا يوجد كشف لإرساله. سجّل البيانات أولًا (مثل «سجل حسابات سلة من فسح»).'
    try:
        found = run_async(groups, timeout=60)
    except Exception as exc:
        return f'تعذر الاطلاع على محادثات واتساب الآن ({type(exc).__name__})؛ لم يُرسل شيء. أعد المحاولة بعد قليل.'
    target = match(found, party, hint)
    if not target:
        names = '، '.join(f'«{n}»' for _, n in found[:8] if n)
        return (f'لم أجد قروب واتساب واحدًا باسم «{hint or party}» في محادثات رقم الوكيل، فلم أجهز الإرسال.\n'
                + (f'القروبات الموجودة: {names}. اكتب اسم القروب كما هو، مثل: «أرسل كشف {party} لقروب <الاسم>».\n' if names else
                   'رقم الوكيل ليس عضوًا في أي قروب ظاهر له الآن.\n')
                + 'شرط واتساب: يكون رقم الوكيل عضوًا في القروب، ويكتب أحد الأعضاء فيه رسالة واحدة على الأقل بعد إضافته حتى يظهر القروب للوكيل.')
    code = make_code({'tool': 'statement_group_send', 'party': party, 'month': month, 'conversation': target[0],
                      'group': target[1][:120]})
    return (f"📄 كشف {party} لشهر {month}: {len(s['lines'])} بيان — الإجمالي {s['total']:,.2f} ريال.\n"
            f"جاهز للإرسال ملف PDF إلى قروب «{target[1]}».\nللإرسال اكتب: نفذ {code}")


def execute(action):
    """After «نفذ»: rebuild the statement now (latest figures) and post the PDF to the group."""
    from app import statement_import, statement_pdf
    from app.transport_desk import run_async
    s = statement_import.statement(action['party'], action['month'])
    if not s.get('lines'):
        return f"لا توجد بيانات لـ{action['party']} في {action['month']} الآن؛ لم يُرسل شيء."
    content = statement_pdf.build(s)
    caption = f"كشف حساب {s['party']} — {s['month']} — {len(s['lines'])} بيان — الإجمالي {s['total']:,.2f} ريال"
    try:
        run_async(lambda: send_pdf(action['conversation'], content, statement_pdf.filename(s), caption), timeout=90)
    except Exception as exc:
        print('STATEMENT_GROUP_SEND', type(exc).__name__, str(exc)[:200], flush=True)
        return f"⚠️ لم يُرسل الكشف إلى قروب «{action['group']}»: {str(exc)[:200] or type(exc).__name__}"
    return f"✅ أُرسل كشف {s['party']} لشهر {s['month']} (PDF) إلى قروب «{action['group']}»."
