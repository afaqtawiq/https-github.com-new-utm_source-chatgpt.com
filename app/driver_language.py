"""Owner-requested (Nov 2026): drivers who do not read Arabic (e.g. Pakistani drivers) get loads in Urdu.

- lang_hint(text): 'ur' (Urdu letters), 'en' (Latin only), 'unclear' (only ?/!/emoji), 'ar' or ''.
- A driver who answers a recent load offer in Urdu/English, or with only «????», gets the same offer
  back in Urdu (+ English when unclear) inside the open 24h window; his language is remembered.
- Broadcasts send Urdu text to drivers marked 'ur'/'en' when their window is open, else the approved
  Arabic template (so delivery never fails because of language).
"""
import re

from app.storage import db, utcnow

URDU_ONLY = re.compile(r'[ٹڈڑںےۓھہۂۃکی]')
ARABIC = re.compile(r'[؀-ۿ]')
LATIN = re.compile(r'[A-Za-z]')
URDU_WORDS = re.compile(r'\b(ki|kya|kia|hai|nahi|nahin|bhai|kitna|kahan|theek|thik|haan|han|jani|yar|yaar)\b', re.I)
SUPPORT = '0507665873'
PAYMENT_UR = {'حسب الاتفاق': 'طے شدہ طریقے کے مطابق'}
PAYMENT_EN = {'حسب الاتفاق': 'as agreed'}


def lang_hint(text):
    t = str(text or '').strip()
    if not t:
        return ''
    if URDU_ONLY.search(t):
        return 'ur'
    if ARABIC.search(t):
        return 'ar'
    if LATIN.search(t):
        return 'ur' if URDU_WORDS.search(t) else 'en'
    if not re.search(r'\w', t, re.U):
        return 'unclear'
    return ''


def init():
    with db() as c:
        c.execute('ALTER TABLE drivers ADD COLUMN IF NOT EXISTS language TEXT')


def digits(phone):
    return re.sub(r'\D', '', str(phone or ''))


def driver_language(c, phone):
    d = digits(phone)
    if len(d) < 9:
        return ''
    row = c.execute("SELECT language FROM drivers WHERE right(regexp_replace(whatsapp_phone,'\\D','','g'),9)=%s "
                    'AND language IS NOT NULL LIMIT 1', (d[-9:],)).fetchone()
    return (row or {}).get('language') or ''


def set_language(c, phone, lang):
    d = digits(phone)
    if lang in ('ar', 'ur', 'en') and len(d) >= 9:
        c.execute("UPDATE drivers SET language=%s,updated_at=%s WHERE right(regexp_replace(whatsapp_phone,'\\D','','g'),9)=%s",
                  (lang, utcnow(), d[-9:]))


def offer_ur(ref, b):
    return (f'آفاق طویق کی طرف سے لوڈ کی پیشکش — {ref}\n'
            f"روٹ: {b['origin']} ← {b['destination']}\n"
            f"وزن: {b['weight']} ٹن\n"
            f"ڈرائیور کا کرایہ: {b['driver_price']} ریال\n"
            f"ان لوڈنگ: {b['unloading']}\n"
            f"ادائیگی: {PAYMENT_UR.get(b['payment'], b['payment'])}\n"
            f'اگر آپ یہ لوڈ لینا چاہتے ہیں تو لکھیں: OK {ref}\nشکریہ۔')


def offer_en(ref, b):
    return (f'Load offer from Afaq Tuwaiq — {ref}\n'
            f"Route: {b['origin']} → {b['destination']}\n"
            f"Weight: {b['weight']} ton\n"
            f"Driver rate: {b['driver_price']} SAR\n"
            f"Unloading: {b['unloading']}\n"
            f"Payment: {PAYMENT_EN.get(b['payment'], b['payment'])}\n"
            f'To take this load reply: OK {ref}\nThank you.')


def offer_for(lang, ref, b):
    if lang == 'ur':
        return offer_ur(ref, b)
    if lang == 'en':
        return offer_en(ref, b)
    return None


def accept_reply(lang, ref, state='recorded'):
    texts = {
        'ur': {'recorded': f'لوڈ {ref} کے لیے آپ کی منظوری درج ہو گئی 👍 ہم لوڈ والے سے بات کر کے جلد تصدیق کریں گے۔ رابطہ: {SUPPORT}',
               'yours': f'لوڈ {ref} آپ کو دے دیا گیا ہے ✅ تفصیلات آپ کو بھیج دی گئی ہیں۔ رابطہ: {SUPPORT}',
               'taken': f'شکریہ 🙏 لوڈ {ref} کسی اور ڈرائیور کو دے دیا گیا ہے۔ اگلے لوڈ ہم آپ کو بھیجتے رہیں گے۔'},
        'en': {'recorded': f'Your acceptance of load {ref} is recorded 👍 We will confirm with the load owner shortly. Contact: {SUPPORT}',
               'yours': f'Load {ref} is assigned to you ✅ Details have been sent. Contact: {SUPPORT}',
               'taken': f'Thank you 🙏 Load {ref} was given to another driver. We will keep sending you new loads.'}}
    return texts.get(lang, {}).get(state)


def latest_offer(c, phone, hours=72):
    d = digits(phone)
    if len(d) < 9:
        return None
    return c.execute('''SELECT b.* FROM load_broadcast_recipients r JOIN load_broadcasts b ON b.id=r.broadcast_id
        WHERE right(r.phone,9)=%s AND r.status IN ('sent','accepted') AND r.sent_at > now() - (%s || ' hours')::interval
        ORDER BY r.sent_at DESC LIMIT 1''', (d[-9:], str(hours))).fetchone()


def driver_reply(phone, hint):
    """A recent offer recipient wrote in Urdu/English or only «????». Returns the reply text or None."""
    if hint not in ('ur', 'en', 'unclear'):
        return None
    init()
    with db() as c:
        b = latest_offer(c, phone)
        if not b:
            return None
        known = driver_language(c, phone)
        if hint in ('ur', 'en'):
            set_language(c, phone, hint)
            lang = hint
        else:
            lang = known if known in ('ur', 'en') else ''
    ref = 'AFT-' + str(b['id'])
    if lang:
        return offer_for(lang, ref, b)
    # Only «????» and no known language: Urdu first, then English.
    return offer_ur(ref, b) + '\n\n' + offer_en(ref, b)
