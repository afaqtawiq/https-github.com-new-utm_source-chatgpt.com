"""Owner-requested (Nov 2026): «مدير التخليص لازم يعرف أي مادة وش المطلوب عليها».

One tool for Faisal: product description (+ optional HS code, origin, use) ->
  1) GCC tariff candidates and duty (local table),
  2) live SABER result for each candidate 12-digit code (official saber.sa, anonymous),
  3) web research limited to official Saudi sources (ZATCA, SASO/SABER, SFDA, MEWA, CST, NCEC, Civil Defence,
     Umm Al-Qura import-licensing guide) for the competent authority, permits, restrictions and documents,
and returns one Arabic report that leads with blockers/contradictions and ends with a customer-ready message.
Nothing is sent anywhere; unverified points are labelled as such.
"""
import asyncio
import json
import os
import re

import httpx

OFFICIAL = ('zatca.gov.sa', 'saber.sa', 'saso.gov.sa', 'sfda.gov.sa', 'mewa.gov.sa', 'cst.gov.sa', 'ncec.gov.sa',
            '998.gov.sa', 'uqn.gov.sa', 'my.gov.sa', 'mim.gov.sa', 'modon.gov.sa', 'momrah.gov.sa')

PROMPT = """You are a senior Saudi customs-clearance manager. Determine what is required to IMPORT this product into Saudi Arabia.
Product: {product}
HS code given: {hs}
Origin / supplier: {origin}
Use: {use}
Tariff candidates from the GCC tariff table: {tariff}
Live SABER (saber.sa HS-code list) results: {saber}

Search and read ONLY official Saudi sources ({domains}) to establish, for THIS product:
- competent authority/authorities (SASO/SABER, SFDA, MEWA, CST, NCEC (chemicals/environment), Civil Defence, Ministry of Industry, Ministry of Interior/other) and whether the product is prohibited or restricted;
- import permits/licences/registrations required before shipping (with the official name);
- SABER path: PCoC/COC or self-declaration + SCoC (use the SABER results above when present);
- documents at customs;
- practical risks (e.g. dangerous goods, chemicals list, labelling, end-use).
Never invent a requirement or an exemption. If a point cannot be confirmed from an official page, put it in "unverified".
Flag contradictions first (e.g. the supplier on the document is a Saudi factory -> it may be a local purchase, not an import).

Answer with ONE JSON object only:
{{"blockers": ["...contradictions or must-clarify points, Arabic"],
  "hs_code": "12-digit or empty", "duty": "e.g. 5%",
  "authorities": [{{"name": "Arabic", "requirement": "Arabic", "source": "url"}}],
  "saber": "Arabic one line",
  "permits": ["Arabic"], "documents": ["Arabic"], "restrictions": ["Arabic"],
  "unverified": ["Arabic"],
  "questions_for_customer": ["Arabic"],
  "customer_message": "short Saudi-Arabic WhatsApp reply for the customer, no promises, ends with: فريق آفاق طويق — 0507665873"}}"""


def enabled():
    return bool(os.getenv('ANTHROPIC_API_KEY')) and os.getenv('IMPORT_REQUIREMENTS_RESEARCH', '1') != '0'


def tariff_candidates(product_ar, product_en, hs):
    from app import tariff_lookup
    try:
        if hs:
            items = tariff_lookup.search(re.sub(r'\D', '', hs)[:12], '', limit=5)
            if items:
                return items
        return tariff_lookup.search_many([product_ar] if product_ar else None, [product_en] if product_en else None, limit=5)
    except Exception as exc:
        print('IMPORT_REQ_TARIFF', type(exc).__name__, str(exc)[:120], flush=True)
        return []


async def saber_for(codes):
    from app.saber_lookup import lookup_saber
    out = {}
    for code in codes[:3]:
        try:
            r = await lookup_saber(code)
        except Exception as exc:
            r = {'status': 'unavailable', 'reason': type(exc).__name__}
        out[code] = {'status': r.get('status'), 'results': (r.get('results') or [])[:3], 'source': r.get('source_url')}
    return out


async def research(fields):
    key = os.getenv('ANTHROPIC_API_KEY', '')
    model = os.getenv('IMPORT_REQUIREMENTS_MODEL') or os.getenv('TRACKING_RESEARCH_MODEL') or os.getenv('LOAD_VISION_MODEL', 'claude-sonnet-5')
    prompt = PROMPT.format(domains=', '.join(OFFICIAL), **fields)
    tool_sets = ([{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 6, 'allowed_domains': list(OFFICIAL)},
                  {'type': 'web_fetch_20250910', 'name': 'web_fetch', 'max_uses': 6, 'allowed_domains': list(OFFICIAL)}],
                 [{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 6, 'allowed_domains': list(OFFICIAL)}])
    async with httpx.AsyncClient(timeout=180) as client:
        for tools in tool_sets:
            headers = {'x-api-key': key, 'anthropic-version': '2023-06-01'}
            if any(t['name'] == 'web_fetch' for t in tools):
                headers['anthropic-beta'] = 'web-fetch-2025-09-10'
            messages = [{'role': 'user', 'content': prompt}]
            text = ''
            refused = False
            for _ in range(5):
                r = await client.post('https://api.anthropic.com/v1/messages', headers=headers,
                                      json={'model': model, 'max_tokens': 3000, 'tools': tools, 'messages': messages})
                if r.status_code == 400:
                    print('IMPORT_REQ_REFUSED', r.text[:200], flush=True)
                    refused = True
                    break
                r.raise_for_status()
                data = r.json()
                text = ''.join(b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text')
                if data.get('stop_reason') != 'pause_turn':
                    break
                messages = [messages[0], {'role': 'assistant', 'content': data.get('content', [])}]
            if refused:
                continue
            m = re.search(r'\{.*\}', text or '', re.S)
            try:
                return json.loads(m.group(0)) if m else None
            except ValueError:
                return None
    return None


def _saber_line(saber):
    lines = []
    for code, r in (saber or {}).items():
        if r.get('status') == 'results' and r.get('results'):
            row = r['results'][0]
            vals = row if isinstance(row, dict) else {}
            reg = vals.get('regulation') or ''
            cert = vals.get('certificates') or vals.get('certificate') or ''
            lines.append(f'{code}: خاضع للائحة «{reg}» — الشهادة: {cert}'.strip())
        elif r.get('status') == 'no_results':
            lines.append(f'{code}: لم يظهر في قائمة البنود الخاضعة للوائح في سابر (المسار المتوقع: إقرار ذاتي + شهادة إرسالية؛ عدم الظهور ليس إعفاءً)')
        else:
            lines.append(f'{code}: تعذر الوصول لسابر الآن — يُراجع على saber.sa/Home/HSCodes')
    return lines


def render(product, tariff, saber, found):
    from app.tariff_lookup import format_code
    out = [f'🛃 متطلبات استيراد: {product}']
    f = found or {}
    if f.get('blockers'):
        out.append('\n⚠️ قبل أي شيء:')
        out += ['• ' + x for x in f['blockers']]
    out.append('\n📑 التصنيف والرسوم (مبدئي، يُعتمد في فسح):')
    if f.get('hs_code'):
        out.append(f"• البند المرجّح: {format_code(f['hs_code'])}" + (f" — الرسم {f['duty']}" if f.get('duty') else ''))
    for t in tariff[:3]:
        out.append(f"• {format_code(t['code'])} {t.get('desc_ar') or ''} — رسم {t.get('duty') or 'غير مذكور'}")
    out.append('\n✅ سابر:')
    out += ['• ' + x for x in _saber_line(saber)] or ['• لم يُحدد بند كامل للبحث في سابر']
    if f.get('saber'):
        out.append('• ' + f['saber'])
    if f.get('authorities'):
        out.append('\n🏛️ الجهات المختصة:')
        out += [f"• {a.get('name')}: {a.get('requirement')}" + (f" ({a['source']})" if a.get('source') else '') for a in f['authorities']]
    for key, title in (('permits', '📝 تصاريح/تسجيلات قبل الشحن'), ('restrictions', '⛔ قيود وتنبيهات'),
                       ('documents', '📂 المستندات عند التخليص'), ('unverified', '❓ غير متحقق (يُراجع قبل التأكيد للعميل)')):
        if f.get(key):
            out.append(f'\n{title}:')
            out += ['• ' + x for x in f[key]]
    if f.get('questions_for_customer'):
        out.append('\n🙋 نحتاج من العميل:')
        out += ['• ' + x for x in f['questions_for_customer']]
    if f.get('customer_message'):
        out.append('\n— رسالة جاهزة للعميل:\n' + f['customer_message'])
    if not found:
        out.append('\n(البحث في المصادر الرسمية لم يكتمل الآن؛ التقرير مبني على التعرفة وسابر فقط.)')
    return '\n'.join(out)


async def requirements(product, product_en='', hs='', origin='', use=''):
    product = str(product or product_en or '').strip()[:200]
    if not product:
        return 'اكتب اسم المادة أو وصفها.'
    tariff = tariff_candidates(product, str(product_en or '')[:120], str(hs or ''))
    codes = [re.sub(r'\D', '', str(t.get('code'))) for t in tariff if len(re.sub(r'\D', '', str(t.get('code')))) == 12]
    hs_digits = re.sub(r'\D', '', str(hs or ''))
    if len(hs_digits) == 12 and hs_digits not in codes:
        codes.insert(0, hs_digits)
    saber = await saber_for(codes)
    found = None
    if enabled():
        try:
            found = await research({'product': product + (f' / {product_en}' if product_en else ''), 'hs': hs or 'not given',
                                    'origin': origin or 'not given', 'use': use or 'not given',
                                    'tariff': json.dumps(tariff[:3], ensure_ascii=False, default=str),
                                    'saber': json.dumps(saber, ensure_ascii=False, default=str)[:3000]})
        except Exception as exc:
            print('IMPORT_REQ_RESEARCH', type(exc).__name__, str(exc)[:160], flush=True)
    return render(product, tariff, saber, found)
