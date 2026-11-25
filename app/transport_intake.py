"""WhatsApp → internal transport quote draft (pilot, owner request 25 Nov 2026; from Afaaq_WhatsApp_Quote_Pilot.zip).

intake(messages): customer messages of ONE conversation/shipment → ready request / the missing fields only /
human or role review / carrier (→ Khaled). quote(card, rates, today): ONE approved, fully matching rate card →
internal draft for Reem (send_allowed False); otherwise → Khaled without any amount.
Pure functions: no network, database, sending or price changes. Storage and the WhatsApp hook live below them.
"""
from decimal import Decimal, InvalidOperation
import re

TRANSLATE = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹أإآىة٫','01234567890123456789ااايه.')
CITIES = {'جده':'jeddah','الرياض':'riyadh','الدمام':'dammam','مكه':'makkah','المدينه':'madinah','الخرج':'al_kharj','دبي':'dubai','البطحاء':'al_batha'}
CITY = '|'.join(CITIES)
ROUTE = re.compile(rf'(?<!\w)({CITY})\s*(?:الي|→|->)\s*({CITY})(?!\w)')
FIELDS = {'origin':'مدينة التحميل','destination':'الوجهة','cargo':'نوع البضاعة','equipment':'نوع الشاحنة أو مقاس الحاوية',
          'tons':'الوزن الفعلي','loading':'يوم التحميل','empty_return':'هل رجوع الفارغ مشمول؟','unit':'هل السعر للرحلة أو للحاوية؟'}

NOT_APPLICABLE = 'not_applicable'

def norm(s):
    return re.sub(r'[ً-ٰـ]', '', s.lower().translate(TRANSLATE))

def unique(values):
    values = set(values)
    return next(iter(values)) if len(values) == 1 else None

def intake(messages):
    """Inputs must already be scoped to a single shipment and trusted inbound conversation."""
    t = ' '.join(norm(m) for m in messages)
    if re.search(r'(?:^|\s)(?:ايقاف|لا ترسل|الغي الطلب)(?=$|[\s،.])', t):
        return {'state':'stopped'}
    if re.search(r'تخليص جمركي|تخليص فقط|تصدير|التصحيح|عدل|بدل|ليس|\b(?:مو|مش)\s',t):
        return {'state':'human_review'}
    shipper = re.search(r'عندي (?:حموله|بضاعه|شحنه)|(?:نحتاج|محتاج) (?:ناقل|شاحنه|نقل|سطحه)|(?:ابي|ابغى) انقل',t)
    carrier = re.search(r'عندي (?:شاحنه|تريلا|سطحه)|شاحناتنا|اسطولنا|اعرض شاحنتي|انا ناقل|نوفر شاحنات',t)
    if carrier and not shipper:
        return {'state':'carrier','owner':'خالد'}
    if not shipper or carrier:
        return {'state':'role_review'}
    routes = set(ROUTE.findall(t))
    a,b = next(iter(routes)) if len(routes)==1 else (None,None)
    sizes = set(re.findall(r'\b(\d+)\s*(?:قدم|ft)\b',t))
    curtain, flatbed = 'ستاره' in t, 'سطحه' in t
    eq = None
    if curtain and not (flatbed or sizes or 'حاويه' in t):
        eq = 'curtain'
    elif not curtain and sizes in ({'20'},{'40'}):
        eq = 'container_'+next(iter(sizes))
    elif flatbed and not (curtain or sizes or 'حاويه' in t):
        eq = 'flatbed'
    weights = [] if re.search(r'(?:حتي|سعه|تتحمل|حد اقصي|بحد اقصي)\s+\d|\d+\s*(?:الي|او|-)\s*\d+',t) else re.findall(r'(?<![\d.,٬])(\d+(?:\.\d+)?)\s*(?:طن|tons?)(?!\w)',t)
    cargo = unique(re.findall(r'بضاعه[: ]+(خشب|اخشاب|حديد|اغذيه|ملابس|اثاث|ورق|بلاستيك)(?=[،.,]|$)',t))
    loading = unique(re.findall(r'(?:التحميل|نحمل)\s*(?:يوم\s+|[: ]+)?(اليوم|بكره|غدا|الخميس|الجمعه|السبت|الاحد|الاثنين|الثلاثاء|الاربعاء|20\d{2}-\d{2}-\d{2})\b',t))
    exclude = bool(re.search(r'(?:بدون|لا يشمل)\s+(?:رجوع|اعاده)\s+(?:الحاويه\s+)?الفارغ',t))
    include = bool(re.search(r'(?<!لا )(?<!\w)(?:مع|يشمل|شامل)\s+(?:رجوع|اعاده)\s+(?:الحاويه\s+)?الفارغ',t))
    if len(routes)>1 or len(sizes)>1 or (curtain and (flatbed or sizes)) or (include and exclude):
        return {'state':'human_review'}
    unit = unique('trip' if u=='رحله' else 'container' for u in re.findall(r'(?:لكل |بال)(رحله|حاويه)\b',t))
    container = eq is not None and eq.startswith('container_')
    returned = True if include else False if exclude else None
    if eq is not None and not container and returned is None:
        returned = NOT_APPLICABLE  # empty return only exists for containers; never confused with «not included»
    q = dict(origin=CITIES.get(a) if a!=b else None,destination=CITIES.get(b) if a!=b else None,
             cargo='خشب' if cargo=='اخشاب' else cargo,equipment=eq,
             tons=unique(Decimal(x) for x in weights if 0 < Decimal(x) <= 100),
             loading=loading,empty_return=returned,unit=unit)
    missing = [label for key,label in FIELDS.items() if q[key] is None]
    return {'state':'need_details' if missing else 'ready','details':q,'missing':missing}

def quote(card,rates,today):
    if card.get('state')!='ready':
        return card
    q=card['details']
    def eligible(r):
        try:
            cap=Decimal(str(r['max_tons']))
            keys=('origin','destination','equipment','empty_return','unit','cargo')
            return (
                cap.is_finite() and 0 < q['tons'] <= cap <= 100
                and all(type(r[k]) is type(q[k]) and r[k]==q[k] for k in keys)
                and r['approved'] is True and r['currency']=='SAR'
                and type(r['amount_sar']) is int and 0 < r['amount_sar'] <= 60000
                and bool(r['ref']) and r['valid_from'] <= today <= r['valid_until']
                and bool(r['charges_terms']) and type(r['tax_included']) is bool)
        except (KeyError,TypeError,InvalidOperation):
            return False
    matches=[r for r in rates if eligible(r)]
    if len(matches)!=1:
        return {'state':'rate_review','owner':'خالد','reason':'ambiguous' if matches else 'no_exact_approved_rate'}
    r=matches[0]
    return {'state':'internal_draft','owner':'ريم','amount_sar':r['amount_sar'],'rate_ref':r['ref'],
            'valid_until':r['valid_until'].isoformat(),'charges_terms':r['charges_terms'],'tax_included':r['tax_included'],
            'details':dict(q,tons=str(q['tons'])),'send_allowed':False}


# ---------- storage: approved rate cards (full conditions) and internal drafts — never prices from approved_routes ----------

import hashlib
import json
import os


HINT = re.compile(r'نقل|حموله|شاحنه|تريلا|سطحه|ستاره|حاويه|\d+\s*طن|' + ROUTE.pattern)


def relevant(messages):
    """Only transport-looking conversations enter the pilot (greetings and clearance chats stay on the current path)."""
    return bool(HINT.search(' '.join(norm(str(m or '')) for m in messages)))


def pilot_enabled():
    return os.getenv('TRANSPORT_QUOTE_PILOT', '0') == '1'


def init():
    from app.storage import db
    with db() as c:
        # Approved rate CARDS carry every condition a price depends on. Empty until the owner approves cards; the
        # route+amount rows of approved_routes and raw driver survey prices are deliberately NOT used here.
        c.execute('''CREATE TABLE IF NOT EXISTS transport_rate_cards(id BIGSERIAL PRIMARY KEY, ref TEXT UNIQUE NOT NULL,
            origin TEXT NOT NULL, destination TEXT NOT NULL, equipment TEXT NOT NULL, max_tons NUMERIC NOT NULL,
            empty_return TEXT NOT NULL CHECK(empty_return IN ('true','false','not_applicable')), unit TEXT NOT NULL,
            cargo TEXT NOT NULL, currency TEXT NOT NULL, amount_sar INTEGER NOT NULL, tax_included BOOLEAN NOT NULL,
            charges_terms TEXT NOT NULL, valid_from DATE NOT NULL, valid_until DATE NOT NULL, approved BOOLEAN NOT NULL DEFAULT FALSE,
            approved_by TEXT, approved_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS transport_quote_drafts(draft_key TEXT PRIMARY KEY, account_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL, sender TEXT NOT NULL, state TEXT NOT NULL, owner TEXT, reason TEXT, next_step TEXT,
            details_json TEXT NOT NULL DEFAULT '{}', missing_json TEXT NOT NULL DEFAULT '[]', amount_sar INTEGER, rate_ref TEXT,
            created_at TIMESTAMPTZ NOT NULL)''')


def rate_cards():
    """Approved cards in the shape quote() expects."""
    from app.storage import db
    init()
    with db() as c:
        rows = c.execute('SELECT * FROM transport_rate_cards WHERE approved').fetchall()
    out = []
    for r in rows:
        er = {'true': True, 'false': False}.get(r['empty_return'], NOT_APPLICABLE)
        out.append(dict(origin=r['origin'], destination=r['destination'], equipment=r['equipment'], max_tons=r['max_tons'],
                        empty_return=er, unit=r['unit'], cargo=r['cargo'], approved=bool(r['approved']), currency=r['currency'],
                        amount_sar=int(r['amount_sar']), ref=r['ref'], valid_from=r['valid_from'], valid_until=r['valid_until'],
                        tax_included=bool(r['tax_included']), charges_terms=r['charges_terms']))
    return out


NEXT = {'internal_draft': 'ريم تراجع المسودة وتعتمدها قبل أي إرسال للعميل',
        'need_details': 'اسأل العميل عن الناقص فقط',
        'rate_review': 'خالد يسعّر الطلب (لا يوجد سعر معتمد مطابق) — بدون ذكر مبلغ للعميل',
        'carrier': 'خالد: المتكلم ناقل/صاحب شاحنة — شريك وليس عميلًا',
        'role_review': 'تحديد هل المتكلم صاحب شحنة أو ناقل',
        'human_review': 'مراجعة بشرية (تخليص أو طلب مختلط أو تصحيح أو أكثر من مسار/مقاس)',
        'stopped': 'العميل طلب الإيقاف'}


def _plain(details):
    return {k: (str(v) if not isinstance(v, (bool, type(None), str)) else v) for k, v in (details or {}).items()}


def process(account_id, conversation_id, sender, messages, today=None):
    """Shadow run: intake → quote → one stored internal draft per (account, conversation, request version).
    Returns the stored result (or the existing one). Sends nothing and changes no price."""
    import datetime as dt
    from app.storage import db, utcnow
    today = today or dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).date()
    card = intake([str(m or '') for m in messages if str(m or '').strip()])
    result = quote(card, rate_cards(), today)
    details = _plain(result.get('details') or card.get('details'))
    version = hashlib.sha256(json.dumps([result['state'], details, result.get('missing') or card.get('missing') or [],
                                         result.get('rate_ref')], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    key = hashlib.sha256('|'.join((str(account_id), str(conversation_id), version)).encode()).hexdigest()[:32]
    owner = result.get('owner') or ('ريم' if result['state'] == 'need_details' else None)
    init()
    with db() as c:
        c.execute('''INSERT INTO transport_quote_drafts(draft_key,account_id,conversation_id,sender,state,owner,reason,next_step,
            details_json,missing_json,amount_sar,rate_ref,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(draft_key) DO NOTHING''',
                  (key, str(account_id), str(conversation_id), str(sender), result['state'], owner, result.get('reason'),
                   NEXT.get(result['state'], ''), json.dumps(details, ensure_ascii=False),
                   json.dumps(result.get('missing') or card.get('missing') or [], ensure_ascii=False),
                   result.get('amount_sar'), result.get('rate_ref'), utcnow()))
    return dict(result, draft_key=key, send_allowed=False)


def drafts_text(limit=10):
    """Staff view (Reem / Khaled): the latest drafts with reason and next step — no customer texts."""
    from app.storage import db
    init()
    with db() as c:
        rows = c.execute('SELECT * FROM transport_quote_drafts ORDER BY created_at DESC LIMIT %s', (limit,)).fetchall()
    if not rows:
        return 'لا توجد مسودات نقل من واتساب بعد (التجربة ' + ('مفعّلة' if pilot_enabled() else 'غير مفعّلة') + ').'
    labels = {'internal_draft': '📝 مسودة عرض', 'need_details': '❓ بيانات ناقصة', 'rate_review': '💲 تسعير عند خالد',
              'carrier': '🚚 ناقل', 'role_review': '❔ دور غير واضح', 'human_review': '👤 مراجعة بشرية', 'stopped': '⛔ إيقاف'}
    out = ['🚚 مسودات طلبات النقل من واتساب (داخلية — لا يُرسل شيء):']
    for r in rows:
        d = json.loads(r['details_json'] or '{}')
        route = f"{d.get('origin') or '؟'} → {d.get('destination') or '؟'}"
        line = f"{labels.get(r['state'], r['state'])} — +{r['sender'][-4:].rjust(4, '•')} — {route}"
        if r['amount_sar']:
            line += f" — {r['amount_sar']:,} ريال (بطاقة {r['rate_ref']})"
        missing = json.loads(r['missing_json'] or '[]')
        if r['state'] == 'need_details' and missing:
            line += '\n   الناقص: ' + '، '.join(missing)
        line += '\n   التالي: ' + (r['next_step'] or '—')
        out.append(line)
    return '\n'.join(out)
