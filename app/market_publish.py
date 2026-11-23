"""Owner (23 Nov 2026): «من مهام خالد الأساسية الطلب من السائقين وإعلان الحمولات في التطبيق».

Every load Khaled sends to the drivers (AFT-n, after the owner's «نفذ») is also announced on سوق آفاق طويق
(app.afaqtawiqs.net) through its partner endpoint, so drivers who are not on our WhatsApp list see it too; every driver
reply invites him to register in the app. Afaq is the carrier: the app shows the driver price as the driver's net.
Needs MARKET_PARTNER_KEY (same value on both services). Never raises: returns a one-line Arabic result.
"""
import os
import re
import uuid

APP_URL = os.getenv('MARKET_APP_URL', 'https://app.afaqtawiqs.net').rstrip('/')
INVITE = {'ar': 'سجّل في تطبيق «سوق آفاق طويق» برقم جوالك فقط لتصلك كل الحمولات أول بأول: ' + APP_URL + '/market/',
          'ur': 'ہر نیا لوڈ سب سے پہلے پانے کے لیے صرف اپنے موبائل نمبر سے «سوق آفاق طویق» ایپ میں رجسٹر کریں: ' + APP_URL + '/market/',
          'en': 'Register in the «Afaq Tuwaiq Market» app with just your phone number to get every new load first: ' + APP_URL + '/market/'}


def invite(lang='ar'):
    return INVITE.get(lang) or INVITE['ar']


def _vehicle(text):
    t = str(text or '')
    if 'براد' in t or 'مبرد' in t:
        return 'براد'
    if 'سطح' in t or 'فلات' in t:
        return 'سطحة'
    return 'تريلا'


def _number(text):
    m = re.search(r'\d+(?:[.,]\d+)?', str(text or '').replace('٬', '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')))
    return m.group(0).replace(',', '') if m else None


def payload(b):
    price = _number(b['driver_price'])
    weight = _number(b['weight'])
    return {'origin': str(b['origin'])[:80], 'destination': str(b['destination'])[:80],
            'vehicle': _vehicle(' '.join(str(b.get(k) or '') for k in ('message', 'weight', 'unloading'))),
            'request_key': str(uuid.uuid5(uuid.NAMESPACE_URL, 'afaq-agent-load:' + str(b['id']))),
            'cargo_description': 'حمولة عامة من آفاق طويق (الناقل) — التفاصيل والتواصل بعد القبول',
            'weight_mode': 'exact' if weight and float(weight) > 0 else 'open',
            'weight_tons': weight if weight and float(weight) > 0 else None,
            'price_mode': 'fixed', 'advertised_price': price, 'original_price': price, 'agreement_confirmed': True,
            'price_currency': 'SAR', 'contact_phone': '+966507665873',
            'private_notes': f"وكيل آفاق AFT-{b['id']} — التنزيل: {b.get('unloading') or '-'} — الدفع: {b.get('payment') or '-'}"[:1000],
            'commission': '0', 'reference': f"AFT-{b['id']}"}


def publish(bid):
    import httpx
    from app.storage import db
    key = os.getenv('MARKET_PARTNER_KEY', '')
    if len(key) < 32:
        return 'تطبيق سوق آفاق طويق: الربط غير مفعّل بعد (مفتاح الشريك ناقص)؛ أُرسلت الحمولة واتساب فقط.'
    with db() as c:
        b = c.execute('SELECT * FROM load_broadcasts WHERE id=%s', (bid,)).fetchone()
    if not b:
        return ''
    body = payload(b)
    if not body['advertised_price']:
        return 'تطبيق سوق آفاق طويق: سعر السائق غير رقمي؛ لم تُعلن الحمولة في التطبيق.'
    try:
        r = httpx.post(APP_URL + '/api/partner/loads', json=body, headers={'X-Partner-Key': key}, timeout=30)
    except httpx.HTTPError as exc:
        return f'تطبيق سوق آفاق طويق: تعذر الاتصال ({type(exc).__name__})؛ الحمولة أُرسلت واتساب فقط.'
    if r.status_code == 201:
        with db() as c:
            c.execute('ALTER TABLE load_broadcasts ADD COLUMN IF NOT EXISTS market_id BIGINT')
            c.execute('UPDATE load_broadcasts SET market_id=%s WHERE id=%s', (r.json().get('shipment_id'), bid))
        return f'📱 أُعلنت AFT-{bid} في تطبيق سوق آفاق طويق ({APP_URL}/market/) — يراها كل السائقين المسجلين في التطبيق.'
    detail = ''
    try:
        detail = str(r.json().get('detail') or '')[:120]
    except Exception:
        pass
    return f'تطبيق سوق آفاق طويق: لم تُعلن الحمولة ({r.status_code} {detail}).'
