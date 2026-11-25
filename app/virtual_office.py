"""Virtual office (owner request, 19 Nov 2026): the agent split into departments, each with its own manager.

Seven departments — clearance, transport, containers & shipping lines, finance, sales & marketing, customer service,
administration. Each «manager» is the same command agent restricted to its department's tools, with its own role,
and its own conversation memory. The owner talks to them:
- on WhatsApp: «مدير المالية: كشف عمران لهذا الشهر», «قسم النقل، كم حمولة اليوم؟», «الحاويات: وش المتأخر؟»;
  «تقرير الأقسام» returns every department's numbers in one message;
- on the platform page /office: one card per department with its live numbers and a chat box with its manager.

Nothing new is sent to anyone: the managers use the existing tools, and anything that goes outside the company still
needs the same «نفذ CODE» on WhatsApp.
"""
import datetime as dt
import html
import json
import re
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from app.storage import db, utcnow

router = APIRouter()
RIYADH = dt.timezone(dt.timedelta(hours=3))
_READY = False

COMMON = ('search', 'list_recent', 'report', 'ask_document', 'ask_colleague', 'shipment_file', 'shipment_file_update', 'shipment_workflow')
DEPARTMENTS = {
    'clearance': {
        'person': 'فيصل', 'model': 'suit_male',
        'name': 'التخليص الجمركي', 'manager': 'مدير التخليص الجمركي', 'icon': '🛃',
        'aliases': ('التخليص', 'التخليص الجمركي', 'الجمارك'),
        'role': ('تتابع البيانات الجمركية في فسح ومراحلها والرسوم، والتعرفة والبنود والاشتراطات (سابر وغيرها)، وجهاز العمل الذي يقرأ فسح. '
                 'أنت مدير تخليص: أي سؤال «وش المطلوب لاستيراد مادة» (حتى لو مرفق MSDS أو مواصفات) تشغّل له import_requirements '
                 'وتعطي النتيجة كاملة: التناقضات أولًا (مثل أن المورد مصنع سعودي = شراء محلي لا استيراد)، البند والرسم، سابر، الجهات '
                 'والتصاريح، القيود، المستندات، ثم رسالة جاهزة للعميل. لا تقل «لم أستطع التحقق» قبل أن تشغّل الأداة، وما لم يتأكد '
                 'من مصدر رسمي تضعه تحت «غير متحقق».'),
        'tools': ('tariff', 'import_requirements', 'saber_exemptions', 'clearance_expert', 'zatca_rules', 'port_storage', 'customs_question', 'update_declaration', 'shipment_status', 'add_shipment', 'fasah_tracking',
                  'fasah_importer_phone', 'fasah_authorizations', 'open_fasah', 'fasah_containers', 'runner_task', 'runner_status', 'runner_stop',
                  'runner_deny', 'fasah_billing'),
        'actions': (('🖥️ افتح فسح على جهاز آفاق طويق', 'افتح فسح على جهاز آفاق طويق، وأنا أدخل معلومات الدخول'),
                    ('📋 سجّل كشوفات سلة الرحائب من فسح', 'سجل حسابات سلة الرحائب من فسح'),
                    ('🔎 حالة البيانات في فسح', 'وش حالة البيانات المفتوحة في فسح؟'),
                    ('🖥️ وش يسوي جهاز العمل الحين؟', 'وش حالة مهمة جهاز العمل؟'))},
    'transport': {
        'person': 'خالد', 'model': 'casual_male',
        'name': 'النقل والحمولات', 'manager': 'مدير النقل', 'icon': '🚚',
        'aliases': ('النقل', 'الحمولات', 'الشحن البري', 'السواقين', 'السائقين'),
        'role': ('تدير الحمولات من نقليات وملاك الحمولات، وعروض الحمولات للسائقين وأسعار السوق والإسناد. '
                 'مهامك الأساسية (قرار المالك 23 نوفمبر 2026): (1) طلب السائقين لكل حمولة، (2) إعلان كل حمولة في تطبيق «سوق آفاق طويق» '
                 'https://app.afaqtawiqs.net/market/ — يتم تلقائيًا مع نفس «نفذ» الإرسال للسائقين، (3) دعوة كل سائق يتواصل معنا للتسجيل في '
                 'التطبيق برقم جواله فقط. آفاق طويق هي الناقل في التطبيق، وسعر السائق يظهر صافيًا له. '
                 'إذا وصلتك حمولة (صورة بطاقة نقليات و/أو محادثة صاحبها) فلا تكتفِ بالتلخيص: اقرأ الملفات معًا، خذ رقم صاحب '
                 'الحمولة من رأس المحادثة إن وُجد، ثم جهّز فورًا بأداة load_offer: محادثة صاحب الحمولة + العرض على كل السائقين '
                 'برمز «نفذ» واحد. العمولة الثابتة 2.5% من سعر صاحب الحمولة (قرار المالك) — لا تسأل عنها؛ يغيّرها المالك لحمولة '
                 'بعينها فقط إذا طلب. اقرأ السعر كاملًا (٥،٣٠٠ = 5,300). '
                 'وأنت مسؤول جدول أسعار المسارات (rate_card): تجمع أسعار السائقين للمسارات الناقصة (rate_card_survey برمز «نفذ» واحد)، '
                 'وتعرض على المالك الوسيط والسعر المقترح، والمالك وحده يعتمد سعر العميل (approve_route_price). '
                 'وتبني شبكة الناقلين الشركاء: شركات النقل شركاء وليست عملاء؛ تدعوها لإرسال أنواع شاحناتها ومساراتها وأسعارها '
                 '(carrier_invite برمز «نفذ» واحد لكل دفعة) وتتابع ردودها (carrier_partners) وتقارن أسعارها بجدول الأسعار.'),
        'tools': ('add_driver', 'load_offer', 'broadcast_load', 'negotiate_owner', 'assign_driver', 'load_acceptances', 'approve_owner_load',
                  'owner_load_status', 'broadcast_status', 'stop_broadcast', 'driver_price_request', 'driver_prices', 'rate_card', 'rate_card_survey',
                  'approve_route_price', 'carrier_invite', 'carrier_partners', 'transport_drafts', 'send_whatsapp')},
    'containers': {
        'person': 'سلطان', 'model': 'classy_male',
        'name': 'الحاويات ووكلاء الملاحة', 'manager': 'مدير الحاويات والملاحة', 'icon': '🚢',
        'aliases': ('الحاويات', 'الملاحة', 'وكلاء الملاحة', 'الغرامات', 'الشحن البحري'),
        'role': 'تتابع الحاويات حتى إرجاعها فارغة، أيام السماح وطلبات التمديد والغرامات وأرضيات الميناء، وتتبع البواليص ومواعيد الوصول.',
        'tools': ('track_container', 'container_update', 'containers_status', 'container_line', 'line_tariff',
                  'free_time_extension', 'free_time_result', 'detention_claim', 'detention_exposure', 'port_storage',
                  'track_shipment', 'ask_eta_by_email', 'send_email')},
    'finance': {
        'person': 'نورة', 'model': 'suit_female',
        'name': 'المالية والحسابات', 'manager': 'المدير المالي', 'icon': '💰',
        'aliases': ('المالية', 'الحسابات', 'المحاسبة', 'المالي'),
        'role': 'تسجل البيانات في الحسابات بقواعد الفوترة المعتمدة، والكشوفات والأرصدة والسدادات، ومتابعة تحصيل الفواتير مع المسؤول عن السداد بالواتساب (collect_invoice ثم «نفذ»، وتذكير كل 3 أيام حتى السداد)، والمنصرفات (record_expense: كل مصروف يذكره المالك أو الفريق يُسجل فورًا كمسودة مع سداده إن دُفع). لا ترحيل مالي إلا بموافقة المالك.',
        'tools': ('fasah_count', 'billing_gap', 'declaration_info', 'record_declaration_billing', 'customer_balance', 'record_payment', 'record_expense', 'expenses_list', 'collect_invoice', 'collections_followup', 'party_statement', 'fasah_billing',
                  'statement_to_group', 'open_fasah', 'runner_status', 'runner_stop', 'runner_deny'),
        'actions': (('🖥️ افتح فسح على جهاز آفاق طويق', 'افتح فسح على جهاز آفاق طويق، وأنا أدخل معلومات الدخول'),
                    ('📋 سجّل كشوفات سلة الرحائب من فسح', 'سجل حسابات سلة الرحائب من فسح'),
                    ('📤 أرسل كشف الياسمين للقروب', 'أرسل كشف الياسمين لهذا الشهر إلى قروب الياسمين'),
                    ('📄 الكشوفات', 'ارسل الكشوفات لهذا الشهر'))},
    'sales': {
        'person': 'ريم', 'model': 'casual_female',
        'name': 'المبيعات والتسويق', 'manager': 'مدير المبيعات والتسويق', 'icon': '📈',
        'aliases': ('المبيعات', 'التسويق', 'العملاء المحتملين', 'المبيعات والتسويق'),
        'role': ('مديرة قسم تسويق ومبيعات كامل: تبحثين يوميًا عن عملاء جدد (find_leads: شركات الشحن ووكلاء الشحن، شركات النقل، '
                 'المستوردون، وكلاء الصين، الخليج) فيدخلون التواصل اليومي المعتمد تلقائيًا؛ تتابعين الردود والمهتمين وتجهزين لهم عروض '
                 'الأسعار؛ وتديرين المحتوى (البوستر اليومي بالعربي والإنجليزي ينشر تلقائيًا على فيسبوك وإنستغرام ويوتيوب وتيك توك)؛ '
                 'وترفعين للمالك تقرير القمع (marketing_report) كل صباح. لا رسالة خارجية جديدة إلا عبر القوالب المعتمدة أو «نفذ». '
                 'عندك مكتبة أدلة التسويق والمبيعات كاملة (sales_playbook: 50 دليل خبير + حملات آفاق B2B + محتوى الهوية): قبل أي حملة أو رسالة '
                 'تعريف أو بريد بارد أو إعلان أو منشور أو عرض أو تسعير أو خطة، افتحي الدليل المناسب واتبعي طريقته، واكتبي بالعربي الخليجي الطبيعي '
                 'أو بلغة العميل. '
                 'وأنتِ أيضًا منتجة الفيديو: قبل أي فيديو افتحي دليل «afaq-video-production» (sales_playbook) ثم اختاري: '
                 'cinematic_video للفيديو الاحترافي/السينمائي/الإعلاني (لقطات مولدة بالذكاء الاصطناعي وتعليق صوتي احترافي — مدفوع، '
                 'المدير يوافق على التكلفة بـ«نفذ»)، وstock_video للفيديو المجاني السريع من مقاطع حقيقية؛ وvideo_status لمتابعة الطلبات. '
                 'النشر برمز «نفذ» مستقل بعد المعاينة يرسل الفيديو لكل المنصات المربوطة (فيسبوك، إنستغرام، يوتيوب، تيك توك، '
                 'ولينكدإن وإكس وثريدز وغيرها متى ما رُبطت في Zernio) بنص مناسب لكل منصة، وسناب يدوي برابط المعاينة.'),
        'tools': ('sales_playbook', 'transport_drafts', 'find_leads', 'marketing_report', 'add_customer', 'prospect_replies', 'customer_care', 'cinematic_video', 'stock_video', 'video_status', 'whatsapp_templates', 'send_email',
                  'send_whatsapp')},
    'service': {
        'person': 'لمى', 'model': 'casual3_female',
        'name': 'خدمة العملاء', 'manager': 'مدير خدمة العملاء', 'icon': '🎧',
        'aliases': ('خدمة العملاء', 'العملاء', 'الدعم', 'الشكاوى'),
        'role': 'تتابع محادثات العملاء والقروبات (رسائل مهمة بلا رد تنبه عليها بعد 30 دقيقة): الوعود والانتظار والعملاء المنزعجين، وتعليم الوكيل الإجابات الصحيحة، وحالة شحنات العملاء.',
        'tools': ('customer_waiting', 'teach_answer', 'learned_answers', 'shipment_status', 'track_shipment', 'send_whatsapp')},
    'email': {
        'person': 'دانة', 'model': 'suit_female',
        'name': 'البريد والمراسلات', 'manager': 'مديرة البريد', 'icon': '📧',
        'aliases': ('البريد', 'الايميل', 'الإيميل', 'الايميلات', 'الإيميلات', 'المراسلات'),
        'role': 'تستلم إيميلات البريد الرسمي وتفرزها وتنبه للعاجل، وتجهز الردود والمراسلات مع الوكلاء الملاحيين والعملاء والجهات؛ لا يخرج إيميل إلا بعد «نفذ».',
        'tools': ('mail_inbox', 'mail_open', 'mail_reply', 'mail_sent', 'send_email', 'ask_eta_by_email', 'free_time_extension'),
        'actions': (('📌 تحتاج انتباه', 'وش الإيميلات اللي تحتاج انتباه أو رد؟'), ('📥 بريد اليوم', 'وش وصل على الإيميل اليوم؟'))},
    'admin': {
        'person': 'هند', 'model': 'classy_female',
        'name': 'الإدارة والموظفين', 'manager': 'مدير الإدارة', 'icon': '🗂️',
        'aliases': ('الإدارة', 'الادارة', 'الموظفين', 'الموارد البشرية'),
        'role': 'تدير سجل الموظفين وصلاحياتهم على واتساب، والتواصل الداخلي، وتقارير النشاط العامة.',
        'tools': ('list_employees', 'add_employee', 'set_employee_title', 'send_whatsapp', 'office_report')},
}


def init():
    global _READY
    if _READY:
        return
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS office_messages(id BIGSERIAL PRIMARY KEY, department TEXT NOT NULL,
            channel TEXT NOT NULL, author TEXT NOT NULL, command TEXT NOT NULL, reply TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS office_messages_dept ON office_messages(department, id DESC)')
    _READY = True


def _fold(text):
    text = re.sub(r'[ً-ٰـ]', '', str(text or ''))
    return text.translate(str.maketrans('أإآة', 'اااه')).strip()


def route(raw):
    """«مدير المالية: …», «قسم النقل، …», «الحاويات: …» → (department key, the rest). None otherwise.
    A bare department word without «مدير/قسم» or a colon is NOT routed, so ordinary sentences are unaffected."""
    text = str(raw or '').strip()
    folded = _fold(text)
    for key, d in DEPARTMENTS.items():
        for alias in sorted(set(d['aliases']) | {d['name'], d['manager']}, key=len, reverse=True):
            a = re.escape(_fold(alias))
            m = re.match(r'^(?:يا\s+)?(?:(?:مدير|مديرة|قسم|إدارة|اداره|ادارة)\s+)' + a + r'(?:\s*[:،,\-]\s*|\s+|$)', folded) \
                or re.match(r'^(?:يا\s+)?(?:مدير\s+|قسم\s+)?' + a + r'\s*[:：]\s*', folded)
            if not m:
                m = re.match(r'^' + re.escape(_fold(d['manager'])) + r'(?:\s*[:،,\-]\s*|\s+|$)', folded)
            if not m and d.get('person'):
                n = re.escape(_fold(d['person']))
                m = re.match(r'^(?:يا\s+)?' + n + r'\s*[:：،,]\s*', folded) or re.match(r'^يا\s+' + n + r'(?:\s+|$)', folded)
            if m:
                return key, text[m.end():].strip() or 'وش وضع القسم اليوم؟'
    return None


def clearance_notes():
    from app.clearance_expert import NOTES
    from app.zatca_ports_knowledge import NOTES as RULES
    return NOTES + '\n\n' + RULES


def scope(key):
    from app.command_agent import TOOLS
    d = DEPARTMENTS[key]
    names = set(d['tools']) | set(COMMON) | {'office_report'}
    names &= {t['name'] for t in TOOLS}
    others = '، '.join(f"{x['name']} ({x.get('person', '')})" for k, x in DEPARTMENTS.items() if k != key)
    system = (f"\n\nأنت الآن {d.get('person', '')}، «{d['manager']}» في المكتب الافتراضي لآفاق طويق — قسم {d['name']}. مهمتك: {d['role']} "
              'تكلم كمدير قسم يرفع تقريره للمالك: النتيجة أولًا، أرقام دقيقة من الأدوات فقط، ثم ما يحتاج قراره. '
              f'إذا احتاج الطلب قسمًا آخر ({others}) فاطلبه من الزميل مباشرة بأداة ask_colleague وارجع للمالك بالنتيجة، '
              'ولا تحيل المالك لزميل. كل بريد يخرج من البريد الرسمي تراه دانة، وردود الوكلاء ترجع لمن أرسل. '
              'ربط الحسابات والإعدادات التقنية (مثل رموز الخدمات في Railway) يتولاها المالك نفسه؛ لا تحيلها لمدير آخر. '
              'مدراء المكتب (فيصل، خالد، سلطان، نورة، ريم، لمى، دانة، هند) موظفون افتراضيون داخل الوكيل وليس لهم جوالات؛ '
              'الفريق البشري هو المسجل في list_employees، فلا تطلب تسجيل مدير افتراضي كموظف. '
              'لكل شحنة ملف مشترك (shipment_file): صاحبها وجواله وإيميله والحاويات والبيان والمرحلة والخطوة التالية — '
              'ارجع له أولًا لأي سؤال عن عميل أو شحنة، وحدّثه (shipment_file_update) عند أي تقدم. '
              'تستطيع قراءة أي ملف أرسله المالك أو رفعه هنا (PDF، صورة، إكسل، وورد) بأداة ask_document؛ إن لم يصلك الملف '
              'فاطلب منه رفعه هنا أو تحويله لرقم الوكيل بدل أن تقول إنك لا تملك أداة. '
              'إذا نقصت معلومة من العميل (مثل وصف المنتج لسابر أو التعرفة) فجهّز له رسالة طلب البيانات الناقصة بالتحديد '
              '(الاسم التجاري، المادة، الاستخدام، بلد المنشأ، البند من المورد، صورة أو كتالوج) مع رمز «نفذ» بدل أن تتوقف. '
              'إذا أعادت أداة نتيجة بديلة (مثل فتح الصفحة على جهاز آفاق طويق) فاعرضها كما هي ولا تقل إن الأمر غير متاح. '
              + ('\nمرجعك المهني: لأي سؤال تخليص عملي شغّل clearance_expert، ولأي سؤال نظامي أو عن المواد والمدد والموانئ شغّل zatca_rules، '
                 'ولأرضيات الميناء port_storage، وللتفاويض fasah_authorizations — وأجب منها لا من الذاكرة.' if key == 'clearance' else '')
              + '\nأرقام القسم الآن:\n' + snapshot_text(key))
    return {'key': key, 'tools': names, 'system': system}


def sign(key, reply):
    if not reply:
        return reply
    d = DEPARTMENTS[key]
    return f"{d['icon']} {d.get('person', '')} — {d['manager']}:\n{reply}"


def log(key, channel, author, command, reply):
    init()
    with db() as c:
        c.execute('''INSERT INTO office_messages(department,channel,author,command,reply,created_at) VALUES(%s,%s,%s,%s,%s,%s)''',
                  (key, channel, author or '', str(command)[:4000], str(reply or '')[:8000], utcnow()))


def history(key, limit=20):
    init()
    with db() as c:
        return list(reversed(c.execute('SELECT * FROM office_messages WHERE department=%s ORDER BY id DESC LIMIT %s',
                                       (key, limit)).fetchall()))


# ---------- live numbers per department ----------

def _n(sql, params=()):
    """One count; None when the table does not exist yet or the query fails (never breaks the page)."""
    try:
        with db() as c:
            row = c.execute(sql, params).fetchone()
            return list(row.values())[0] if row else None
    except Exception:
        return None


def snapshot(key):
    today = dt.datetime.now(RIYADH).date()
    month = today.replace(day=1)
    day_start = dt.datetime.combine(today, dt.time(0), RIYADH)
    week = utcnow() - dt.timedelta(days=7)
    q = {
        'clearance': [
            ('بيانات تحت المتابعة في فسح', "SELECT COUNT(*) FROM fasah_status WHERE seen_at > NOW() - INTERVAL '3 days'"),
            ('بانتظار سداد الرسوم', "SELECT COUNT(*) FROM fasah_status WHERE duties_since IS NOT NULL AND seen_at > NOW() - INTERVAL '3 days'"),
            ('تغيرت حالتها اليوم', 'SELECT COUNT(*) FROM fasah_status WHERE changed_at >= %s', (day_start,)),
            ('ملفات تخليص هذا الشهر', 'SELECT COUNT(*) FROM customs_declarations WHERE created_at >= %s', (month,)),
        ],
        'transport': [
            ('حمولات جديدة (7 أيام)', 'SELECT COUNT(*) FROM naqliat_loads WHERE created_at >= %s', (week,)),
            ('عروض أُرسلت للسائقين (7 أيام)', 'SELECT COUNT(*) FROM load_broadcasts WHERE created_at >= %s', (week,)),
            ('سائقون مسجلون', 'SELECT COUNT(*) FROM drivers'),
            ('طلبات أسعار سوق (7 أيام)', 'SELECT COUNT(*) FROM driver_price_requests WHERE created_at >= %s', (week,)),
        ],
        'containers': [
            ('حاويات لم تُرجع', "SELECT COUNT(*) FROM container_returns WHERE status IN ('open','delivered','driver_reported')"),
            ('متأخرة عن آخر يوم مجاني', "SELECT COUNT(*) FROM container_returns WHERE status IN ('open','delivered','driver_reported') AND free_until < %s", (today,)),
            ('تنتهي خلال 3 أيام', "SELECT COUNT(*) FROM container_returns WHERE status IN ('open','delivered','driver_reported') AND free_until BETWEEN %s AND %s",
             (today, today + dt.timedelta(days=3))),
            ('بواليص قيد التتبع', 'SELECT COUNT(*) FROM shipment_tracks WHERE NOT arrived'),
        ],
        'finance': [
            ('بيانات مسجلة هذا الشهر', 'SELECT COUNT(*) FROM billing_declarations WHERE created_at >= %s', (month,)),
            ('سدادات مسجلة هذا الشهر', 'SELECT COUNT(*) FROM billing_payments WHERE created_at >= %s', (month,)),
            ('مستندات مالية هذا الشهر', 'SELECT COUNT(*) FROM finance_documents WHERE created_at >= %s', (month,)),
        ],
        'sales': [
            ('عملاء محتملون اليوم', 'SELECT COUNT(*) FROM daily_prospects WHERE batch_date = %s', (today,)),
            ('تم التواصل (7 أيام)', "SELECT COUNT(*) FROM daily_prospects WHERE status='contacted' AND updated_at >= %s", (week,)),
            ('ردود مهتمة (7 أيام)', "SELECT COUNT(*) FROM prospect_replies WHERE intent='interested' AND created_at >= %s", (week,)),
            ('عروض أسعار هذا الشهر', 'SELECT COUNT(*) FROM sales_quotes WHERE created_at >= %s', (month,)),
        ],
        'service': [
            ('رسائل عملاء اليوم', 'SELECT COUNT(*) FROM whatsapp_agent_jobs WHERE created_at >= %s', (day_start,)),
            ('وعود مفتوحة', "SELECT COUNT(*) FROM customer_promises WHERE status='open'"),
            ('تنبيهات انتظار (24 ساعة)', "SELECT COUNT(*) FROM customer_wait_alerts WHERE outcome='alerted' AND created_at > NOW() - INTERVAL '24 hours'"),
            ('عملاء منزعجون (يومين)', "SELECT COUNT(*) FROM customer_upset_events WHERE created_at > NOW() - INTERVAL '2 days'"),
        ],
        'email': [
            ('رسائل وصلت اليوم', 'SELECT COUNT(*) FROM spacemail_inbox WHERE imported_at >= %s', (day_start,)),
            ('تنتظر رد', "SELECT COUNT(*) FROM mail_agent_items WHERE action IN ('draft','preview','send_failed')"),
            ('عاجلة (3 أيام)', "SELECT COUNT(*) FROM mail_agent_items WHERE urgency='high' AND created_at > NOW() - INTERVAL '3 days'"),
            ('ردود أُرسلت (7 أيام)', "SELECT COUNT(*) FROM mail_agent_items WHERE action IN ('approved_sent','auto_sent') AND updated_at >= %s", (week,)),
        ],
        'admin': [
            ('موظفون مسجلون', 'SELECT COUNT(*) FROM team_employees'),
            ('أوامر للمكتب اليوم', 'SELECT COUNT(*) FROM office_messages WHERE created_at >= %s', (day_start,)),
        ],
    }[key]
    out = []
    for item in q:
        label, sql, params = item[0], item[1], (item[2] if len(item) > 2 else ())
        out.append((label, _n(sql, params)))
    return out


def snapshot_text(key):
    return '\n'.join(f'• {label}: {"—" if value is None else value}' for label, value in snapshot(key))


def report_text(key=None):
    keys = [key] if key in DEPARTMENTS else list(DEPARTMENTS)
    parts = ['🏢 تقرير الأقسام — ' + dt.datetime.now(RIYADH).strftime('%d/%m/%Y %H:%M')] if len(keys) > 1 else []
    for k in keys:
        d = DEPARTMENTS[k]
        parts.append(f"\n{d['icon']} {d['name']} — {d.get('person', '')} ({d['manager']})\n" + snapshot_text(k))
    if len(keys) > 1:
        parts.append('\nللتحدث مع أي مدير اكتب اسمه أو قسمه، مثلًا: «نورة: كشف عمران لهذا الشهر» أو «مدير المالية: …».')
    return '\n'.join(parts).strip()


def department_for(text):
    t = _fold(text)
    for key, d in DEPARTMENTS.items():
        if any(_fold(a) in t for a in d['aliases'] + (d['name'],)):
            return key
    return None


# ---------- web office ----------

def _admin(request):
    from app.storage import get_session
    session = get_session(request.cookies.get('gla_session'))
    if not session:
        raise HTTPException(401, 'سجل الدخول أولًا.')
    if session.get('role') != 'admin':
        raise HTTPException(403, 'المكتب الافتراضي للمدير فقط.')
    return session


STYLE = '''<style>body{font-family:Tahoma,Arial;background:#06121d;color:#eef6fb;margin:0}.w{max-width:1300px;margin:auto;padding:20px}
a{color:#7cc4ff}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:16px}.card h2{margin:0 0 6px;font-size:19px}
.muted{color:#9fb4c4;font-size:13px}.kpi{display:flex;justify-content:space-between;border-bottom:1px solid #1d3a4f;padding:6px 0}
.kpi b{font-size:18px}.btn{display:inline-block;margin-top:10px;padding:8px 12px;border-radius:10px;background:#22c55e;color:#04130a;
font-weight:bold;text-decoration:none;border:0;cursor:pointer}.msg{background:#0b1c29;border-radius:12px;padding:10px;margin:8px 0;white-space:pre-wrap}
.me{border-right:4px solid #7cc4ff}.him{border-right:4px solid #22c55e}textarea{width:100%;min-height:80px;background:#0b1c29;color:#eef6fb;
border:1px solid #28475d;border-radius:10px;padding:10px;font-size:15px;box-sizing:border-box}</style>'''


def _page(title, body):
    return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" '
                        'content="width=device-width,initial-scale=1"><title>' + html.escape(title) + '</title>' + STYLE +
                        '</head><body><div class="w">' + body + '</div></body></html>')


ASSETS = Path(__file__).resolve().parent / 'office_assets'
TEMPLATE = Path(__file__).resolve().parent / 'office_3d.html'
TYPES = {'.js': 'application/javascript', '.glb': 'model/gltf-binary'}


def _state(session=None):
    out = []
    for key, d in DEPARTMENTS.items():
        kpis = snapshot(key)
        alert = any(v and any(w in label for w in ('متأخرة', 'منزعج', 'انتظار')) for label, v in kpis)
        last = history(key, 1)
        out.append({'key': key, 'name': d['name'], 'manager': d['manager'], 'icon': d['icon'], 'role': d['role'],
                    'person': d.get('person', ''), 'model': d.get('model', ''), 'photo': photo_version(key),
                    'actions': [list(x) for x in d.get('actions', ())],
                    'kpis': [[label, v] for label, v in kpis], 'alert': bool(alert),
                    'last': ({'command': last[-1]['command'][:200], 'reply': last[-1]['reply'][:300]} if last else None)})
    data = {'departments': out}
    if session is not None:
        data['csrf'] = session.get('csrf') or ''
    return data


@router.get('/office', response_class=HTMLResponse)
def office_3d(request: Request):
    """The 3D office: each department manager at a desk; tap one to talk to him."""
    import json
    session = _admin(request)
    config = json.dumps(_state(session), ensure_ascii=False, default=str).replace('<', '\\u003c')
    return HTMLResponse(TEMPLATE.read_text(encoding='utf-8').replace('__CONFIG__', config),
                        headers={'Cache-Control': 'no-store'})


@router.get('/office/assets/{path:path}')
def office_asset(path: str):
    target = (ASSETS / path).resolve()
    if ASSETS not in target.parents or not target.is_file() or target.suffix not in TYPES:
        raise HTTPException(404, 'غير موجود')
    return FileResponse(target, media_type=TYPES[target.suffix], headers={'Cache-Control': 'public, max-age=604800'})


@router.get('/office/api/state')
def office_state(request: Request):
    _admin(request)
    return JSONResponse(json.loads(json.dumps(_state(), ensure_ascii=False, default=str)))


@router.get('/office/api/report')
def office_report(request: Request):
    _admin(request)
    return {'text': report_text()}


@router.get('/office/api/{key}/history')
def office_history(key: str, request: Request):
    _admin(request)
    if key not in DEPARTMENTS:
        raise HTTPException(404, 'قسم غير موجود')
    return {'messages': [{'author': m['author'], 'channel': m['channel'], 'command': m['command'], 'reply': m['reply'],
                          'at': m['created_at'].astimezone(RIYADH).strftime('%d/%m %H:%M')} for m in history(key)]}


@router.post('/office/api/{key}/ask')
async def office_ask(key: str, request: Request):
    import secrets as _secrets
    from starlette.concurrency import run_in_threadpool
    session = _admin(request)
    if key not in DEPARTMENTS:
        raise HTTPException(404, 'قسم غير موجود')
    expected = session.get('csrf') or ''
    if not expected or not _secrets.compare_digest(request.headers.get('x-csrf-token', ''), expected):
        raise HTTPException(403, 'أعد فتح الصفحة ثم حاول مجددًا.')
    try:
        body = await request.json()
    except ValueError:
        body = {}
    text = str((body or {}).get('text') or '').strip()[:2000]
    if not text:
        raise HTTPException(400, 'اكتب طلبك.')
    reply = await run_in_threadpool(ask, key, text, session.get('name') or session.get('email') or 'المدير',
                                    owner=office_owner(session), meeting=bool((body or {}).get('meeting')))
    return {'reply': reply}


MAX_UPLOAD = 15 * 1024 * 1024


# ---------- real staff photos (owner, 22 Nov 2026): kept in the DB (the repo is public), shown only inside the office ----------
_PHOTO_CACHE = {}


def _photo_table(c):
    c.execute('''CREATE TABLE IF NOT EXISTS staff_photos(key TEXT PRIMARY KEY, mime TEXT NOT NULL, data BYTEA NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''')


def photo(key):
    """(mime, bytes, version) of a manager's photo: an uploaded one, else STAFF_PHOTO_<KEY> (base64 JPEG) from the server
    settings; None when there is none."""
    import base64
    import os
    try:
        from app.storage import db
        with db() as c:
            _photo_table(c)
            row = c.execute('SELECT mime, data, updated_at FROM staff_photos WHERE key=%s', (key,)).fetchone()
        if row:
            return row['mime'], bytes(row['data']), str(int(row['updated_at'].timestamp()))
    except Exception as exc:
        print('STAFF_PHOTO', type(exc).__name__, str(exc)[:120], flush=True)
    raw = os.getenv('STAFF_PHOTO_' + key.upper(), '').strip()
    if raw:
        try:
            data = base64.b64decode(raw)
            return ('image/png' if data[:4] == b'\x89PNG' else 'image/jpeg'), data, 'env' + str(len(raw))
        except ValueError:
            return None
    return None


def photo_version(key):
    try:
        got = photo(key)
    except Exception:
        return ''
    return got[2] if got else ''


def square_jpeg(data, size=320):
    """Centre-crop to a square (faces sit in the upper middle of a portrait) and shrink to a small JPEG."""
    import io
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert('RGB')
    w, h = im.size
    side = min(w, h)
    left, top = (w - side) // 2, max(0, min(h - side, int(h * 0.12))) if h > w else 0
    im = im.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, 'JPEG', quality=84, optimize=True)
    return out.getvalue()


@router.get('/office/api/photo/{key}')
def office_photo(key: str, request: Request):
    _admin(request)
    got = photo(key) if key in DEPARTMENTS else None
    if not got:
        raise HTTPException(404)
    return Response(got[1], media_type=got[0], headers={'Cache-Control': 'private, max-age=600'})


@router.post('/office/api/{key}/photo')
async def office_photo_upload(key: str, request: Request):
    """Set a manager's real photo (image file). Replaces the previous one."""
    import secrets as _secrets
    from starlette.datastructures import UploadFile
    session = _admin(request)
    if key not in DEPARTMENTS:
        raise HTTPException(404, 'قسم غير موجود')
    if not _secrets.compare_digest(request.headers.get('x-csrf-token', ''), session.get('csrf') or '-'):
        raise HTTPException(403, 'أعد فتح الصفحة ثم حاول مجددًا.')
    form = await request.form()
    up = form.get('file')
    if not isinstance(up, UploadFile):
        raise HTTPException(400, 'أرفق صورة.')
    data = await up.read(12_000_001)
    if not data or len(data) > 12_000_000:
        raise HTTPException(400, 'الصورة فارغة أو أكبر من 12 ميجابايت.')
    try:
        small = square_jpeg(data)
    except Exception:
        raise HTTPException(400, 'الملف ليس صورة صالحة.')
    from app.storage import db
    with db() as c:
        _photo_table(c)
        c.execute('''INSERT INTO staff_photos(key,mime,data,updated_at) VALUES(%s,'image/jpeg',%s,NOW())
            ON CONFLICT(key) DO UPDATE SET mime=EXCLUDED.mime,data=EXCLUDED.data,updated_at=NOW()''', (key, small))
    return {'ok': True, 'photo': photo_version(key)}


@router.post('/office/api/{key}/upload')
async def office_upload(key: str, request: Request):
    """A file (PDF, Excel, CSV, Word, image) for one manager, with an optional message. Kept 3 days for questions."""
    import secrets as _secrets
    from starlette.concurrency import run_in_threadpool
    from starlette.datastructures import UploadFile
    from app import staff_documents
    session = _admin(request)
    if key not in DEPARTMENTS:
        raise HTTPException(404, 'قسم غير موجود')
    expected = session.get('csrf') or ''
    if not expected or not _secrets.compare_digest(request.headers.get('x-csrf-token', ''), expected):
        raise HTTPException(403, 'أعد فتح الصفحة ثم حاول مجددًا.')
    if int(request.headers.get('content-length') or 0) > MAX_UPLOAD + 200_000:
        raise HTTPException(413, 'الملف أكبر من 15 ميجابايت.')
    form = await request.form()
    item = form.get('file')
    if not isinstance(item, UploadFile):
        raise HTTPException(400, 'اختر ملفًا.')
    data = await item.read(MAX_UPLOAD + 1)
    if not data:
        raise HTTPException(400, 'الملف فارغ.')
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, 'الملف أكبر من 15 ميجابايت.')
    name = re.sub(r'[\x00-\x1f]', '', str(item.filename or 'ملف'))[:160]
    kind, mime = staff_documents.kind_of(name, data)
    if not kind:
        raise HTTPException(415, mime)
    owner = office_owner(session)
    doc_id = await run_in_threadpool(staff_documents.save, owner, name, mime, data)
    text = str(form.get('text') or '').strip()[:2000]
    if data[:4] == b'%PDF':
        # Every shipping document uploaded in the office opens/updates its shipment file (customer, contact, containers).
        try:
            from app import load_vision, shipping_docs
            fields = await load_vision.extract_pdf(data)
            await run_in_threadpool(staff_documents.set_fields, doc_id, fields)
            from app import shipment_files, shipment_workflow
            await run_in_threadpool(shipment_workflow.note_document, fields)
            kept = await run_in_threadpool(shipment_files.keep_document, fields, name, data, mime)
            if kept:
                text = (text + '\n\n' if text else '') + f'[حُفظ المستند في ملف الشحنة {kept}]'
            if fields.get('document_kind') == 'shipping_document' and fields.get('bill_no'):
                registered = await run_in_threadpool(shipping_docs.register, fields, text)
                text = (text + '\n\n' if text else '') + ('[سُجل المستند في ملف الشحنة ' + str(fields.get('bill_no')) +
                        (' وفي متابعة الحاويات: ' + registered if registered else '') + ' — اعرض الملف بأداة shipment_file.]')
        except Exception as exc:
            print('OFFICE_DOC_EXTRACT', type(exc).__name__, str(exc)[:160], flush=True)
    reply = await run_in_threadpool(ask, key, text, session.get('name') or session.get('email') or 'المدير',
                                    owner=owner, attached=(name, kind))
    return {'reply': reply, 'file': name, 'kind': KIND_AR.get(kind, kind)}


@router.get('/office/cards', response_class=HTMLResponse)
def office(request: Request):
    _admin(request)
    e = html.escape
    cards = ''
    for key, d in DEPARTMENTS.items():
        kpis = ''.join(f'<div class="kpi"><span>{e(label)}</span><b>{"—" if v is None else e(str(v))}</b></div>' for label, v in snapshot(key))
        cards += (f'<div class="card"><h2>{d["icon"]} {e(d["name"])}</h2><div class="muted">{e(d["manager"])} — {e(d["role"])}</div>'
                  f'{kpis}<a class="btn" href="/office/{key}">تحدث مع {e(d["manager"])}</a></div>')
    body = ('<p><a href="/office">← المكتب ثلاثي الأبعاد</a> · <a href="/dashboard">النظام</a></p><h1>🏢 المكتب الافتراضي — آفاق طويق</h1>'
            '<p class="muted">كل قسم له مدير يعمل بأدوات قسمه فقط. تقدر تكلمه هنا أو على واتساب: «مدير المالية: …»، '
            'و«تقرير الأقسام» يرسل لك أرقام كل الأقسام. أي إرسال خارج الشركة يبقى بتأكيد «نفذ» على واتساب.</p>'
            f'<div class="grid">{cards}</div>')
    return _page('المكتب الافتراضي', body)


@router.get('/office/{key}', response_class=HTMLResponse)
def department_page(key: str, request: Request):
    session = _admin(request)
    if key not in DEPARTMENTS:
        raise HTTPException(404, 'قسم غير موجود')
    e = html.escape
    d = DEPARTMENTS[key]
    msgs = ''
    for m in history(key):
        msgs += (f'<div class="msg me"><span class="muted">{e(m["author"])} · {e(m["channel"])} · '
                 f'{e(m["created_at"].astimezone(RIYADH).strftime("%d/%m %H:%M"))}</span>\n{e(m["command"])}</div>'
                 f'<div class="msg him">{e(m["reply"])}</div>')
    kpis = ''.join(f'<div class="kpi"><span>{e(label)}</span><b>{"—" if v is None else e(str(v))}</b></div>' for label, v in snapshot(key))
    body = (f'<p><a href="/office">← المكتب الافتراضي</a></p><h1>{d["icon"]} {e(d["manager"])}</h1>'
            f'<p class="muted">{e(d["role"])}</p><div class="grid"><div class="card"><h2>أرقام القسم الآن</h2>{kpis}</div>'
            f'<div class="card"><h2>اكتب لمدير القسم</h2><form method="post" action="/office/{key}">'
            f'<input type="hidden" name="csrf" value="{e(session.get("csrf") or "")}">'
            '<textarea name="text" required placeholder="مثال: وش المتأخر عندك اليوم؟"></textarea>'
            '<button class="btn">إرسال</button></form><p class="muted">الرد قد يأخذ حتى دقيقة. الإجراءات التي ترسل خارج الشركة '
            'تُجهز برمز وتُؤكد بـ«نفذ» من واتساب.</p></div></div>'
            f'<h2>المحادثة</h2>{msgs or "<p class=muted>لا توجد رسائل بعد.</p>"}')
    return _page(d['manager'], body)


KIND_AR = {'pdf': 'PDF', 'excel': 'إكسل', 'csv': 'جدول CSV', 'word': 'وورد', 'image': 'صورة'}


CONFIRM = re.compile(r'^\s*(?:نفذ|نفّذ)\s*[:،-]?\s*([0-9A-Fa-f]{6})\s*$')


def owner_chat():
    """The owner's WhatsApp chat with the agent (sender, conversation), so codes prepared from the office are the same
    codes he can confirm on WhatsApp, and statement PDFs reach him there. None when unknown."""
    import os
    owner = re.sub(r'\D', '', os.getenv('WHATSAPP_COMMAND_OWNER', ''))
    if not owner:
        return None
    try:
        with db() as c:
            if not c.execute("SELECT to_regclass('whatsapp_admin_audit') t").fetchone()['t']:
                return None
            row = c.execute('''SELECT sender, conversation_id FROM whatsapp_admin_audit
                WHERE regexp_replace(sender, '\\D', '', 'g') = %s AND conversation_id IS NOT NULL ORDER BY id DESC LIMIT 1''',
                            (owner,)).fetchone()
    except Exception:
        return None
    return (row['sender'], row['conversation_id']) if row else None


def confirm(c, code, chat):
    """«نفذ CODE» typed in the office: run the same prepared action as on WhatsApp (one use, not expired)."""
    from app import command_agent
    if not chat:
        return 'لا أستطيع تنفيذ الرمز من هنا؛ اكتب «نفذ ' + code + '» على واتساب.'
    row = c.execute('''UPDATE whatsapp_voice_pending SET consumed=TRUE WHERE token=%s AND sender=%s AND NOT consumed
        AND expires_at>NOW() RETURNING command''', (code.upper(), chat[0])).fetchone()
    if not row:
        return 'الرمز غير صحيح أو انتهت صلاحيته أو نُفذ من قبل.'
    command = row['command']
    if not command.startswith(command_agent.CONFIRM_PREFIX):
        return 'هذا الرمز لأمر يُنفذ من واتساب فقط؛ اكتب «نفذ ' + code + '» هناك.'
    return command_agent.execute_confirmed(c, command[len(command_agent.CONFIRM_PREFIX):])


MEETING_NOTE = ('[اجتماع الفريق: المالك يخاطب كل المدراء معًا. رد من زاوية قسمك فقط في 3 أسطر كحد أقصى، بالأرقام إن وجدت. '
                'إن لم يخص الطلب قسمك فاكتب سطرًا واحدًا: «لا شيء يخص قسمي». لا تجهّز إرسالًا أو تسجيلًا إلا إذا ذُكر قسمك أو اسمك صراحة.]\n')


def ask(key, text, author, manager=True, channel='المنصة', owner=None, attached=None, meeting=False, chat=None):
    """Run one request through the department manager (used by the web page). Returns the reply.
    owner = whose uploaded files ask_document reads; attached = (filename, kind) of a file sent with this message."""
    from app import command_agent, staff_documents
    from app.team import CONTEXT, ROLE
    past = [{'command': m['command'], 'reply': m['reply']} for m in history(key, 4)]
    prompt = (MEETING_NOTE + text) if meeting else text
    if attached:
        prompt = (text or 'اقرأ الملف ولخص لي أهم ما فيه.') + (
            f"\n\n[أرفق المالك الآن ملف «{attached[0]}» ({KIND_AR.get(attached[1], attached[1])}). اقرأه بأداة ask_document قبل الرد. "
            'لا تسجل أو ترسل شيئًا بناءً عليه إلا إذا طلب ذلك صراحة.]')
    role = ROLE.set({'name': author, 'manager': manager})
    ctx = CONTEXT.set({'history': past})
    scope_token = command_agent.OFFICE.set(scope(key))
    doc_token = staff_documents.SENDER.set(owner) if owner else None
    chat = chat or (owner_chat() if channel == 'المنصة' else None)
    chat_token = command_agent.CHAT.set(chat) if chat else None
    try:
        with db() as c:
            code = CONFIRM.match(text or '') if not attached else None
            reply = (confirm(c, code.group(1), chat or command_agent.OFFICE_CHAT) if code and manager
                     else command_agent.run_agent(c, prompt))
    finally:
        if chat_token is not None:
            command_agent.CHAT.reset(chat_token)
        if doc_token is not None:
            staff_documents.SENDER.reset(doc_token)
        command_agent.OFFICE.reset(scope_token)
        CONTEXT.reset(ctx)
        ROLE.reset(role)
    reply = reply or 'تعذر الحصول على رد الآن؛ أعد المحاولة بعد قليل.'
    log(key, 'اجتماع' if meeting else channel, author, (f'📎 {attached[0]}\n' if attached else '') + (text or ''), reply)
    return reply


def office_owner(session):
    return 'office:' + str(session.get('user_id') or session.get('email') or 'admin')


@router.post('/office/{key}')
async def department_post(key: str, request: Request):
    from starlette.concurrency import run_in_threadpool
    from app.social_publishing import csrf
    session = _admin(request)
    if key not in DEPARTMENTS:
        raise HTTPException(404, 'قسم غير موجود')
    data = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
    csrf(session, data)
    text = str(data.get('text') or '').strip()[:2000]
    if text:
        await run_in_threadpool(ask, key, text, session.get('name') or session.get('email') or 'المدير')
    return RedirectResponse(f'/office/{key}', 303)
