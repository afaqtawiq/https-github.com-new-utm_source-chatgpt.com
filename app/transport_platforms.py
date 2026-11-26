"""خالد — التسجيل في منصات النقل (طلب المالك، 26 نوفمبر 2026): «عايز خالد يسجل في المنصات المثل دي كلها».

1) أي رسالة واتساب فيها رابط ودعوة للتسجيل في منصة نقل تُسجّل هنا، ويصل المدير تنبيه واحد لكل منصة.
2) التسجيل لا يبدأ إلا بأمر المدير «سجّل في منصة …»: جهاز العمل يفتح صفحة التسجيل، ويعبئ بيانات المؤسسة،
   ويرفع مستنداتها من أرشيف المؤسسة. لا يكتب كلمة المرور، ولا يضع علامة الإقرار، ولا يضغط أي زر:
   المدير يكمل كلمة المرور والإقرار ويضغط «إرسال» بنفسه.
3) بيانات المؤسسة (الاسم النظامي، السجل التجاري، الرقم الضريبي…) تُحفظ مرة واحدة وتُستخدم لكل المنصات.
"""
import json
import re
import time
from urllib.parse import urlparse

from app.storage import db, utcnow

URL = re.compile(r'https?://[^\s<>"\'،)]+', re.I)
INVITE = re.compile(r'تسجيل|سجل|التسجيل|انضمام|الانضمام|انضم|منص[ةه]|register|registration|sign\s*up|join|platform|onboard', re.I)
TRANSPORT = re.compile(r'نقل|شاحن|شحن|حمول|ناقل|لوجست|transport|truck|freight|cargo|shipment|logistic|load', re.I)
IGNORED = ('afaqtawiqs.net', 'afaqtwiq.com', 'afaqtawiq', 'railway.app', 'wa.me', 'whatsapp.com', 'google.', 'goo.gl',
           'youtube.', 'youtu.be', 'instagram.', 'tiktok.', 'facebook.', 'fb.', 'twitter.', 'x.com', 'linkedin.', 'snapchat.',
           'apple.com', 'zatca.gov.sa')
STATUS_AR = {'new': 'دعوة جديدة — لم يُطلب التسجيل', 'approved': 'وافق المدير — جهاز العمل يجهّز التسجيل',
             'filled': 'عُبئت البيانات — ينتظر كلمة المرور والإرسال من المدير', 'submitted': 'أُرسل طلب التسجيل — ينتظر التفعيل',
             'active': 'الحساب مفعّل', 'skipped': 'تم تجاهلها'}
# بيانات المؤسسة لنماذج التسجيل: المفتاح ← (الوصف، مرادفات عنوان الخانة في المنصات)
PROFILE = {
    'legal_name': ('الاسم النظامي للمؤسسة', ['الاسم الكامل', 'الاسم القانوني', 'اسم المنشأة', 'اسم الشركة', 'اسم المؤسسة', 'company name', 'legal name', 'full name']),
    'short_name': ('الاسم المختصر', ['الاسم المختصر', 'الاسم المختصر للحساب', 'display name', 'short name']),
    'email': ('البريد الإلكتروني', ['البريد الإلكتروني', 'البريد الالكتروني', 'الإيميل', 'email', 'e-mail']),
    'phone': ('رقم الجوال', ['رقم الهاتف', 'رقم الجوال', 'الجوال', 'الهاتف', 'phone', 'mobile']),
    'address': ('العنوان', ['العنوان', 'عنوان المنشأة', 'address']),
    'city': ('المدينة', ['المدينة', 'city']),
    'cr_number': ('رقم السجل التجاري', ['رقم السجل التجاري', 'السجل التجاري', 'commercial registration', 'cr number']),
    'vat_number': ('الرقم الضريبي', ['رقم ضريبة القيمة المضافة', 'الرقم الضريبي', 'vat number', 'tax number']),
    'username': ('اسم المستخدم المقترح', ['اسم المستخدم', 'اسم المستخدم لتسجيل الدخول', 'username', 'user name']),
}
REQUIRED = ('legal_name', 'email', 'phone', 'cr_number', 'vat_number')
DEFAULTS = {  # من سجلات النظام؛ يغيّرها المدير بأداة بيانات المؤسسة
    'legal_name': 'مؤسسة آفاق طويق للتخليص الجمركي', 'short_name': 'afaq-tuwaiq', 'email': 'info@afaqtawiqs.net',
    'phone': '0530130435', 'address': 'جدة، تقاطع طريق صاري مع شارع الستين، عمارة المليباري', 'city': 'جدة',
    'username': 'afaqtuwaiq',
}
DOCUMENTS = {  # نوع المستند في أرشيف المؤسسة ← مرادفات عنوان خانة الرفع
    'commercial_registration': ['سجل تجاري', 'السجل التجاري', 'commercial registration', 'cr document'],
    'tax_certificate': ['شهادة ضريبة القيمة المضافة', 'الشهادة الضريبية', 'شهادة الضريبة', 'vat certificate', 'tax certificate'],
    'national_address': ['العنوان الوطني', 'وثيقة العنوان الوطني', 'national address'],
    'transport_license': ['رخصة النقل', 'ترخيص النقل', 'transport license'],
}
_READY = False
_CACHE = {'at': 0.0, 'domains': []}


def init():
    global _READY
    if _READY:
        return
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS transport_platforms(id BIGSERIAL PRIMARY KEY, domain TEXT NOT NULL UNIQUE,
            url TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', invited_by TEXT NOT NULL DEFAULT '', invite_text TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'new', task_id BIGINT, history TEXT NOT NULL DEFAULT '[]',
            created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS company_profile(key TEXT PRIMARY KEY, value TEXT NOT NULL,
            updated_by TEXT NOT NULL DEFAULT '', updated_at TIMESTAMPTZ NOT NULL)''')
    _READY = True


# ------------------------------------------------------------------ الدعوات
def _domain(url):
    host = (urlparse(url).hostname or '').lower()
    return host[4:] if host.startswith('www.') else host


def detect(text):
    """دعوة تسجيل في منصة نقل داخل نص الرسالة → {'url','domain','name'} أو None. بدون قاعدة بيانات."""
    text = str(text or '')
    if not INVITE.search(text) or not TRANSPORT.search(text):
        return None
    for raw in URL.findall(text):
        url = raw.rstrip('.,;!؟?')
        domain = _domain(url)
        if not domain or '.' not in domain or any(bad in domain for bad in IGNORED):
            continue
        name = ''
        match = re.search(r'(?:مرحب[اًا]* بكم في|أهلا بكم في|اهلا بكم في)\s+([^\n.،]{3,50})', text)
        if match:
            name = match.group(1).strip()
        else:
            match = re.search(r'welcome to\s+([^\n.,]{3,50})', text, re.I)
            name = match.group(1).strip() if match else ''
        return {'url': url[:300], 'domain': domain[:120], 'name': name[:80]}
    return None


def _log(row, text):
    history = json.loads((row or {}).get('history') or '[]')
    history.append({'at': utcnow().isoformat(timespec='minutes'), 'text': text[:300]})
    return json.dumps(history[-40:], ensure_ascii=False)


def record(invite, sender='', text=''):
    """يحفظ الدعوة مرة واحدة لكل منصة. يرجع نص التنبيه للمدير إذا كانت المنصة جديدة، وإلا None."""
    if not invite:
        return None
    init()
    with db() as c:
        row = c.execute('SELECT * FROM transport_platforms WHERE domain=%s', (invite['domain'],)).fetchone()
        if row:
            return None
        c.execute('''INSERT INTO transport_platforms(domain,url,name,invited_by,invite_text,history,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(domain) DO NOTHING''',
                  (invite['domain'], invite['url'], invite.get('name') or '', str(sender or '')[:30], str(text or '')[:600],
                   _log(None, 'وصلت دعوة التسجيل' + (f' من +{sender}' if sender else '')), utcnow(), utcnow()))
    label = invite.get('name') or invite['domain']
    return (f'🚚 خالد: وصلتنا دعوة للتسجيل في منصة نقل «{label}» ({invite["domain"]})'
            + (f' من +{sender}' if sender else '') + '.\n'
            f'للتسجيل اكتب: «سجّل في منصة {invite["domain"]}» — يعبئ جهاز العمل بيانات المؤسسة ويرفع مستنداتها، '
            'وأنت تكتب كلمة المرور وتضغط إرسال بنفسك.')


def add(url, actor=''):
    """المدير يضيف منصة بنفسه (رابط من أي مكان)."""
    url = str(url or '').strip()
    if not re.match(r'https://', url):
        url = 'https://' + url.lstrip('/')
    domain = _domain(url)
    if not domain or '.' not in domain:
        return None
    init()
    with db() as c:
        c.execute('''INSERT INTO transport_platforms(domain,url,name,invited_by,history,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(domain) DO NOTHING''',
                  (domain, url[:300], '', actor[:30], _log(None, f'أضافها {actor or "المدير"}'), utcnow(), utcnow()))
        return c.execute('SELECT * FROM transport_platforms WHERE domain=%s', (domain,)).fetchone()


def find(query):
    init()
    q = str(query or '').strip().lower()
    q = _domain(q) if q.startswith('http') else q.replace('www.', '')
    with db() as c:
        return c.execute('''SELECT * FROM transport_platforms WHERE domain=%s OR domain ILIKE %s OR name ILIKE %s
            ORDER BY (domain=%s) DESC, updated_at DESC LIMIT 1''', (q, '%' + q + '%', '%' + q + '%', q)).fetchone() if q else None


def approved_domains():
    """نطاقات المنصات التي وافق المدير على التسجيل فيها — يُسمح لجهاز العمل بفتحها فقط. مخزّنة دقيقة واحدة."""
    if time.time() - _CACHE['at'] < 60:
        return _CACHE['domains']
    try:
        init()
        with db() as c:
            found = [r['domain'] for r in c.execute(
                "SELECT domain FROM transport_platforms WHERE status IN ('approved','filled','submitted','active')").fetchall()]
    except Exception:
        found = []
    _CACHE.update(at=time.time(), domains=found)
    return found


# ------------------------------------------------------------------ بيانات المؤسسة
def profile():
    init()
    with db() as c:
        saved = {r['key']: r['value'] for r in c.execute('SELECT key, value FROM company_profile').fetchall()}
    return dict(DEFAULTS, **{k: v for k, v in saved.items() if v})


def set_profile(values, actor=''):
    init()
    changed = []
    with db() as c:
        for key, value in (values or {}).items():
            value = re.sub(r'[\x00-\x1f\x7f]', ' ', str(value or '')).strip()[:200]
            if key not in PROFILE or not value:
                continue
            if key in ('cr_number', 'vat_number'):
                digits = re.sub(r'\D', '', value.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')))
                if key == 'cr_number' and not re.fullmatch(r'\d{10}', digits):
                    return 'رقم السجل التجاري 10 أرقام.'
                if key == 'vat_number' and not re.fullmatch(r'3\d{13}3', digits):
                    return 'الرقم الضريبي 15 رقمًا يبدأ وينتهي بـ3.'
                value = digits
            c.execute('''INSERT INTO company_profile(key,value,updated_by,updated_at) VALUES(%s,%s,%s,%s)
                ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_by=EXCLUDED.updated_by, updated_at=EXCLUDED.updated_at''',
                      (key, value, actor[:40], utcnow()))
            changed.append(PROFILE[key][0])
    return ('✅ حُفظت: ' + '، '.join(changed) + '\n\n' + profile_text()) if changed else profile_text()


def missing_profile(values=None):
    values = values or profile()
    return [PROFILE[k][0] for k in REQUIRED if not values.get(k)]


def profile_text():
    values = profile()
    lines = ['🏢 بيانات المؤسسة المستخدمة في التسجيل بالمنصات:']
    lines += [f'• {label}: {values.get(key) or "— غير مسجل"}' for key, (label, _) in PROFILE.items()]
    missing = missing_profile(values)
    if missing:
        lines.append('\n⚠️ ناقص: ' + '، '.join(missing) + ' — أرسلها مثل: «بيانات المؤسسة: السجل التجاري 4030123456، الرقم الضريبي 300012345600003».')
    return '\n'.join(lines)


def archived_documents():
    """آخر نسخة من كل نوع مستند في أرشيف المؤسسة: {kind: {'id','name','media_type','byte_count'}}."""
    try:
        with db() as c:
            rows = c.execute('''SELECT DISTINCT ON (kind) id, kind, name, media_type, byte_count FROM company_documents
                WHERE kind = ANY(%s) ORDER BY kind, created_at DESC''', (list(DOCUMENTS),)).fetchall()
        return {r['kind']: {'id': str(r['id']), 'name': r['name'], 'media_type': r['media_type'], 'byte_count': r['byte_count']} for r in rows}
    except Exception:
        return {}


def document_bytes(doc_id):
    with db() as c:
        row = c.execute('SELECT name, media_type, content FROM company_documents WHERE id=%s', (str(doc_id),)).fetchone()
    return row


# ------------------------------------------------------------------ التسجيل
def signup(query, actor=''):
    """أمر المدير «سجّل في منصة X»: يوافق على النطاق وينشئ مهمة جهاز العمل (تعبئة ورفع بدون إرسال)."""
    row = find(query)
    if not row and re.search(r'[a-z0-9-]+\.[a-z]{2,}', str(query or ''), re.I):
        row = add(re.search(r'\S+\.[a-z]{2,}\S*', str(query), re.I).group(0), actor)
    if not row:
        return f'ما لقيت منصة «{query}». أرسل رابطها أو اكتب «أضف منصة <الرابط>».'
    values = profile()
    missing = missing_profile(values)
    if missing:
        return ('قبل التسجيل في ' + row['domain'] + ' ينقص من بيانات المؤسسة: ' + '، '.join(missing)
                + '.\nأرسلها مثل: «بيانات المؤسسة: السجل التجاري 4030123456، الرقم الضريبي 300012345600003» ثم أعد الطلب.')
    docs = archived_documents()
    with db() as c:
        c.execute("UPDATE transport_platforms SET status='approved', history=%s, updated_at=%s WHERE id=%s",
                  (_log(row, f'وافق {actor or "المدير"} على التسجيل'), utcnow(), row['id']))
    _CACHE['at'] = 0.0
    # إن كان الرابط صفحة دخول، ينتقل الجهاز إلى رابط «التسجيل» الظاهر فيها (على نفس النطاق) بدل الضغط عليه.
    params = {'url': row['url'], 'platform': row['domain'],
              'fields': [{'key': k, 'label': PROFILE[k][0], 'value': values[k], 'synonyms': PROFILE[k][1]}
                         for k in PROFILE if values.get(k)],
              'documents': [{'kind': k, 'label': d['name'], 'doc_id': d['id'], 'synonyms': DOCUMENTS[k],
                             'media_type': d['media_type'], 'byte_count': d['byte_count']} for k, d in docs.items()]}
    from app import agent_runner
    tid, message = agent_runner.create_task('platform_signup', params, actor or 'خالد')
    if tid:
        with db() as c:
            c.execute('UPDATE transport_platforms SET task_id=%s, updated_at=%s WHERE id=%s', (tid, utcnow(), row['id']))
    absent = [label for kind, label in (('commercial_registration', 'السجل التجاري'), ('tax_certificate', 'شهادة الضريبة'),
                                         ('national_address', 'العنوان الوطني')) if kind not in docs]
    return (f'🚚 خالد: التسجيل في {row["domain"]}\n' + message
            + '\nجهاز العمل يفتح صفحة التسجيل، ويعبئ بيانات المؤسسة' + ('، ويرفع المستندات من أرشيف المؤسسة' if docs else '')
            + '. لا يكتب كلمة المرور ولا يضغط أي زر.'
            + (f'\n⚠️ غير موجود في أرشيف المؤسسة: {"، ".join(absent)} — ارفعه في صفحة مستندات المؤسسة أو أرفقه بنفسك في المنصة.' if absent else '')
            + '\nبعد انتهائه: افتح نافذة جهاز العمل، اكتب كلمة المرور وتأكيدها، وضع علامة الإقرار، واضغط «إرسال طلب التسجيل» بنفسك، '
              f'ثم اكتب «تم التسجيل في {row["domain"]}».') if tid else message


def mark(query, status, actor=''):
    row = find(query)
    if not row:
        return f'ما لقيت منصة «{query}».'
    if status not in STATUS_AR:
        return 'الحالة غير معروفة.'
    with db() as c:
        c.execute('UPDATE transport_platforms SET status=%s, history=%s, updated_at=%s WHERE id=%s',
                  (status, _log(row, f'{actor or "المدير"}: {STATUS_AR[status]}'), utcnow(), row['id']))
    _CACHE['at'] = 0.0
    return f'✅ {row["domain"]}: {STATUS_AR[status]}'


def after_task(task_id, ok):
    """جهاز العمل انتهى من التعبئة."""
    init()
    with db() as c:
        row = c.execute('SELECT * FROM transport_platforms WHERE task_id=%s', (task_id,)).fetchone()
        if row and ok and row['status'] == 'approved':
            c.execute("UPDATE transport_platforms SET status='filled', history=%s, updated_at=%s WHERE id=%s",
                      (_log(row, 'عبأ جهاز العمل البيانات ورفع المستندات — بانتظار المدير'), utcnow(), row['id']))


def status_text():
    init()
    with db() as c:
        rows = c.execute('SELECT * FROM transport_platforms ORDER BY updated_at DESC LIMIT 30').fetchall()
    if not rows:
        return 'لا توجد منصات نقل مسجلة بعد. أي دعوة تسجيل تصل على واتساب تُضاف هنا تلقائيًا، أو اكتب «أضف منصة <الرابط>».'
    return '🚚 منصات النقل:\n' + '\n'.join(
        f"• {r['name'] or r['domain']} ({r['domain']}) — {STATUS_AR.get(r['status'], r['status'])}" for r in rows)
