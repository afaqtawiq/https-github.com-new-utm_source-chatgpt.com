"""Natural WhatsApp answers for Afaq Tuwaiq customers, grounded in the full approved knowledge base.

Used by the WhatsApp assistant for ordinary text questions (no documents). It answers like a
helpful Saudi customer-service employee, from customs_knowledge.KNOWLEDGE only. It never claims an
action was done, never confirms a live shipment status, never asks for passwords or bank data,
and only shares the official contact numbers/links that appear in the knowledge or below.
Any doubt in the output returns None so the caller falls back to the guarded path.
"""
import os
import re

import httpx

SUPPORT = '0507665873'
EXTRA_NUMBERS = {'0507665873', '966507665873', '0530130435', '966530130435'}
MAX_CHARS = 1400
ACTION_CLAIM = re.compile(r'(سأحجز|سنحجز|حجزت|حجزنا|تم\s*الحجز|أرسلت\s*لك|ارسلت\s*لك|تم\s*الإرسال|تم\s*الارسال|سأرسل|سنرسل\s*السائق|نفذت|تم\s*التنفيذ|تم\s*التأكيد|أكدت\s*الحجز|وصلت\s*شحنتك|شحنتك\s*وصلت|تم\s*الفسح)')

SYSTEM = """أنت موظف خدمة العملاء على واتساب لمؤسسة «آفاق طويق للتخليص الجمركي والنقل» في السعودية.
اكتب بالعربية السعودية المهذبة والطبيعية، كأنك موظف حقيقي: مختصر وواضح ودود، بدون مقدمات طويلة ولا تكرار.
أجب عن سؤال العميل نفسه مباشرة. إذا كان سؤاله عامًا (مثل: عندكم تخليص؟ عندكم نقل؟) فأكّد الخدمة واذكر أهم ما يلزم في سطرين،
ثم اسأله سؤالًا واحدًا مفيدًا لإكمال الطلب (المنفذ أو المسار، نوع البضاعة، عدد الحاويات).
اعتمد فقط على «معلومات آفاق» أدناه. الأسعار تُذكر فقط من قسم الأسعار المعتمدة كما هي، مع التنبيه أنها أجور الخدمة فقط وأن الرسوم الحكومية على المستورد.
لا تخترع أسعارًا أو مددًا أو وعودًا. ما ليس في المعلومات قل إن الفريق يرسل له عرضًا خاصًا أو يتابع معه، ورقم الدعم واتساب/اتصال 0507665873 (أو 0530130435).
لا تقل إنك نفّذت أي إجراء أو حجزت أو أرسلت شيئًا. لا تؤكد حالة شحنة أو وصولها؛ اطلب رقم البوليصة أو الحاوية وقل إن فريق العمليات سيتابع.
لا تطلب كلمات مرور أو رموز تحقق أو بيانات بنكية. اسمك «نيرمين، المساعدة الرقمية لآفاق طويق».
العمل 24 ساعة طوال أيام الأسبوع. ترخيص التخليص الجمركي 2513، ترخيص النقل 11/00098402.
اكتب نصًا عاديًا مناسبًا لواتساب (بدون عناوين Markdown)، ويمكن استخدام نقاط قصيرة عند الحاجة، وبحد أقصى نحو 8 أسطر.

معلومات آفاق:
"""


def model():
    return (os.getenv('WHATSAPP_NATURAL_MODEL') or os.getenv('COMMAND_AGENT_MODEL')
            or os.getenv('COMMAND_AI_MODEL', 'claude-sonnet-5')).strip()


def enabled():
    return os.getenv('WHATSAPP_NATURAL_REPLIES', '1') == '1'


def allowed_numbers(knowledge):
    found = {re.sub(r'\D', '', n) for n in re.findall(r'\+?\d[\d\s-]{7,}\d', knowledge)}
    return found | EXTRA_NUMBERS


def safe(text, knowledge):
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text or len(text) > MAX_CHARS:
        return None
    numbers = {re.sub(r'\D', '', n) for n in re.findall(r'\+?\d[\d\s-]{8,}\d', text)}
    if numbers - allowed_numbers(knowledge):
        return None
    for url in re.findall(r'https?://\S+', text):
        if url.rstrip('.,)،') not in knowledge and 'afaqtawiqs.net' not in url:
            return None
    if re.search(r'(كلمة\s*(المرور|السر)|رمز\s*التحقق|رقم\s*البطاقة|الآيبان|IBAN)', text) and 'لا ' not in text:
        return None
    # Never claim or promise an executed action (booking, sending, dispatching, confirming).
    if ACTION_CLAIM.search(text):
        return None
    return text


def messages(question, history):
    out = []
    for entry in list(history or ())[-6:]:
        q = str((entry or {}).get('question') or '').strip()
        a = str((entry or {}).get('reply') or (entry or {}).get('reply_text') or '').strip()
        if q and a:
            out += [{'role': 'user', 'content': q[:1500]}, {'role': 'assistant', 'content': a[:1500]}]
    out.append({'role': 'user', 'content': str(question)[:2000]})
    return out


async def reply(question, history=()):
    """Return a natural grounded answer, or None (caller then uses the guarded path)."""
    if not enabled():
        return None
    from app import whatsapp_agent_privacy as privacy
    if privacy.identity_requested(str(question)):
        return None
    key = os.getenv('ANTHROPIC_API_KEY', '').strip()
    name = model()
    if not key or not re.fullmatch(r'claude-[a-zA-Z0-9._-]{1,100}', name):
        return None
    from app.customs_knowledge import KNOWLEDGE
    body = {'model': name, 'max_tokens': 700, 'system': SYSTEM + KNOWLEDGE,
            'messages': messages(question, history)}
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            r = await client.post('https://api.anthropic.com/v1/messages', json=body,
                                  headers={'x-api-key': key, 'anthropic-version': '2023-06-01'})
        if r.status_code != 200:
            print('WHATSAPP_NATURAL_HTTP', r.status_code, flush=True)
            return None
        data = r.json()
        text = '\n'.join(p.get('text', '') for p in data.get('content', []) if isinstance(p, dict) and p.get('type') == 'text')
    except (httpx.HTTPError, ValueError) as exc:
        print('WHATSAPP_NATURAL_ERROR', type(exc).__name__, flush=True)
        return None
    result = safe(text, KNOWLEDGE)
    if result is None:
        print('WHATSAPP_NATURAL_REJECTED', flush=True)
    return result
