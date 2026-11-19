"""The email desk of the virtual office (owner request, 19 Nov 2026: «لابد أن يكون في موظفة مسؤولة عن إدارة الإيميل»).

Reads the official mailbox the platform already syncs (spacemail_inbox, classified by mail_agent): what arrived, what is
urgent, what waits for a reply, the full text of one message and its suggested reply. Replying is an external send: it is
prepared here and goes out from the official mailbox only after «نفذ CODE».
"""
import datetime as dt
import re
from email.utils import parseaddr

RIYADH = dt.timezone(dt.timedelta(hours=3))
CATEGORY_AR = {'customer_inquiry': 'استفسار عميل', 'customer_followup': 'متابعة عميل', 'quote_request': 'طلب سعر',
               'shipping_line': 'خط ملاحي', 'shipping_agent': 'وكيل ملاحي', 'invoice': 'فاتورة', 'government': 'جهة حكومية',
               'complaint': 'شكوى', 'job': 'توظيف', 'notice': 'إشعار', 'newsletter': 'نشرة', 'spam': 'مزعج', 'other': 'أخرى'}
WAITING = ('draft', 'preview', 'send_failed')


def mailbox_user(c):
    """The admin user whose official mailbox is connected, or None."""
    from app import spacemail
    if not c.execute("SELECT to_regclass('spacemail_connections') t").fetchone()['t']:
        return None
    row = c.execute('''SELECT s.user_id FROM spacemail_connections s JOIN users u ON u.id=s.user_id
        WHERE s.enabled AND s.address=%s AND u.role='admin' ORDER BY s.user_id LIMIT 1''', (spacemail.ADDRESS,)).fetchone()
    return row['user_id'] if row else None


def _has_items(c):
    return bool(c.execute("SELECT to_regclass('mail_agent_items') t").fetchone()['t'])


def _line(r):
    name, addr = parseaddr(r['sender'] or '')
    tag = CATEGORY_AR.get(r.get('category') or '', '')
    flags = ('🔴 ' if r.get('urgency') == 'high' else '') + ('⏳ ' if r.get('action') in WAITING else '')
    summary = (r.get('summary') or '').strip()
    return (f"#{r['id']} {flags}{(r['subject'] or '(بدون عنوان)')[:90]}\n   من: {name or addr}" + (f' <{addr}>' if name and addr else '')
            + (f' · {tag}' if tag else '') + (f'\n   {summary[:160]}' if summary else ''))


def inbox(c, view='attention', query='', limit=10):
    uid = mailbox_user(c)
    if not uid:
        return 'البريد الرسمي غير متصل بالمنصة؛ اربطه من «إعداد البريد» ثم أقرأ الوارد.'
    items = _has_items(c)
    join = 'LEFT JOIN mail_agent_items a ON a.inbox_id=i.id' if items else ''
    cols = ', a.category, a.urgency, a.summary, a.action' if items else ", NULL category, NULL urgency, '' summary, NULL action"
    where, params = ['i.user_id=%s'], [uid]
    if query:
        where.append('(i.sender ILIKE %s OR i.subject ILIKE %s OR i.body ILIKE %s)')
        params += ['%' + query + '%'] * 3
        title = f'🔎 رسائل فيها «{query}»'
    elif view == 'today':
        start = dt.datetime.combine(dt.datetime.now(RIYADH).date(), dt.time(0), RIYADH)
        where.append('i.imported_at >= %s')
        params.append(start)
        title = '📥 بريد اليوم'
    elif view == 'all':
        title = '📥 آخر الرسائل'
    else:
        if items:
            where.append("(a.action IN ('draft','preview','send_failed') OR (a.urgency='high' AND a.action NOT IN ('approved_sent','auto_sent','dismissed')))")
        where.append("i.imported_at > NOW() - INTERVAL '14 days'")
        title = '📌 رسائل تحتاج انتباه (عاجلة أو تنتظر رد)'
    rows = c.execute(f'''SELECT i.id, i.sender, i.subject, i.imported_at{cols} FROM spacemail_inbox i {join}
        WHERE {' AND '.join(where)} ORDER BY i.id DESC LIMIT %s''', (*params, max(1, min(int(limit or 10), 20)))).fetchall()
    if not rows:
        return title + ': لا يوجد.' + (' اكتب «بريد اليوم» أو «آخر الرسائل» لعرض الكل.' if view == 'attention' and not query else '')
    return title + ':\n' + '\n'.join(_line(r) for r in rows) + '\nلفتح رسالة: «افتحي الرسالة #رقم»؛ للرد: «ردي على #رقم».'


def open_message(c, mid):
    uid = mailbox_user(c)
    if not uid:
        return 'البريد الرسمي غير متصل بالمنصة.'
    items = _has_items(c)
    row = c.execute(('SELECT i.*, a.category, a.urgency, a.summary, a.reply_body, a.action FROM spacemail_inbox i '
                     'LEFT JOIN mail_agent_items a ON a.inbox_id=i.id' if items else 'SELECT i.* FROM spacemail_inbox i')
                    + ' WHERE i.id=%s AND i.user_id=%s', (mid, uid)).fetchone()
    if not row:
        return f'لا توجد رسالة رقم {mid} في البريد الرسمي.'
    body = re.sub(r'\n{3,}', '\n\n', (row['body'] or '').strip())
    out = [f"✉️ رسالة #{row['id']}", f"من: {row['sender']}", f"العنوان: {row['subject'] or '(بدون عنوان)'}",
           f"وصلت: {row['received'] or row['imported_at']}", '', body[:3500] + ('…' if len(body) > 3500 else '')]
    if row.get('reply_body') and row.get('action') in WAITING:
        out += ['', '— رد مقترح جاهز —', row['reply_body'][:1500], f"للإرسال كما هو: «ردي على #{row['id']}»."]
    return '\n'.join(out)


def prepare_reply(c, mid, body, make_code):
    uid = mailbox_user(c)
    if not uid:
        return 'البريد الرسمي غير متصل بالمنصة؛ لم أجهز الرد.'
    items = _has_items(c)
    row = c.execute(('SELECT i.*, a.reply_body, a.reply_to FROM spacemail_inbox i LEFT JOIN mail_agent_items a ON a.inbox_id=i.id'
                     if items else "SELECT i.*, NULL reply_body, NULL reply_to FROM spacemail_inbox i")
                    + ' WHERE i.id=%s AND i.user_id=%s', (mid, uid)).fetchone()
    if not row:
        return f'لا توجد رسالة رقم {mid} في البريد الرسمي.'
    to = row.get('reply_to') or parseaddr(row['sender'] or '')[1]
    text = (body or row.get('reply_body') or '').strip()
    if not to or '@' not in to:
        return 'لا أعرف عنوان المرسل لهذه الرسالة.'
    if len(text) < 20:
        return f"اكتبي نص الرد (أو اطلب: «اكتبي ردًا مناسبًا على #{mid}» وأقترح نصًا)."
    from app.mail_agent import subject_for
    subject = subject_for(row['subject'])
    code = make_code({'tool': 'mail_reply', 'id': int(mid), 'to': to, 'subject': subject, 'body': text[:6000]})
    return (f'↩️ رد جاهز على #{mid} إلى {to}\nالعنوان: {subject}\n\n{text[:1200]}\n\n'
            f'للإرسال من البريد الرسمي اكتب: نفذ {code}')


def send_reply(c, action):
    """After «نفذ»: send in the same thread (In-Reply-To) and mark the item as answered."""
    from app import spacemail
    uid = mailbox_user(c)
    if not uid:
        return 'البريد الرسمي غير متصل؛ لم يُرسل شيء.'
    row = c.execute('SELECT message_id, message_references FROM spacemail_inbox WHERE id=%s AND user_id=%s',
                    (action['id'], uid)).fetchone()
    if not row:
        return 'الرسالة لم تعد موجودة؛ لم يُرسل شيء.'
    refs = ' '.join(x for x in (row.get('message_references') or '', row.get('message_id') or '') if x).strip() or None
    try:
        sent = spacemail.send(uid, action['to'], action['subject'], action['body'],
                              in_reply_to=row.get('message_id') or None, references=refs)
    except Exception as exc:
        return 'تعذر إرسال الرد (' + type(exc).__name__ + '). لم أعد المحاولة.'
    if _has_items(c):
        c.execute("""UPDATE mail_agent_items SET action='approved_sent', reply_body=%s, reply_message_id=%s, updated_at=NOW()
            WHERE inbox_id=%s""", (action['body'], sent, action['id']))
    return f"✅ أُرسل الرد على #{action['id']} إلى {action['to']} من {spacemail.ADDRESS}."
