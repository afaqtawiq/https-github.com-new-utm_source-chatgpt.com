"""Customs tariff lookup for the Afaq agent.

Source: the GCC unified customs tariff at 12-digit level (official schedule published by Kuwait's
Public Authority for Industry, loaded into the gcc_tariff table on 30 Sep 2026: 13,353 codes with
Arabic/English descriptions, their heading context, unit and duty rate).

The agent may quote a candidate code and its duty rate from this table, always as a preliminary
classification: the final code is confirmed by the customs broker in FASAH, and Saudi-specific
requirements (SABER, SFDA, permits) come from customs_knowledge and the broker.
"""
import re

from app.storage import rows

SOURCE_NOTE = 'جدول التعرفة الجمركية الموحدة لدول مجلس التعاون (12 رقمًا)'


def format_code(code):
    code = re.sub(r'[^0-9]', '', str(code or ''))
    return ' '.join(code[i:i + 2] for i in range(0, len(code), 2)) if len(code) == 12 else code


def search(query_ar='', query_en='', limit=8):
    """Best matching tariff lines for a product description (Arabic and/or English) or a code prefix."""
    query_ar = str(query_ar or '').strip()[:120]
    query_en = str(query_en or '').strip().lower()[:120]
    digits = re.sub(r'[^0-9]', '', query_ar + query_en)
    try:
        if len(digits) >= 4 and not re.search(r'[A-Za-z\u0600-\u06ff]{3,}', query_ar + query_en):
            return rows('SELECT code,desc_ar,desc_en,context_ar,duty FROM gcc_tariff WHERE code LIKE ? ORDER BY code LIMIT ?',
                        (digits[:12] + '%', limit))
        return rows('''SELECT code,desc_ar,desc_en,context_ar,duty,
                GREATEST(word_similarity(?, search), word_similarity(?, search)) AS score
            FROM gcc_tariff
            WHERE GREATEST(word_similarity(?, search), word_similarity(?, search)) > 0.35
            ORDER BY score DESC, code LIMIT ?''',
                    (query_ar or query_en, query_en or query_ar, query_ar or query_en, query_en or query_ar, limit))
    except Exception:
        return []


def as_prompt(items):
    """Compact candidate list for Claude."""
    return [{'code': format_code(x['code']), 'description': x['desc_ar'], 'context': (x.get('context_ar') or '')[:220],
             'duty': x['duty']} for x in items]


def as_text(items, limit=5):
    if not items:
        return 'لم أجد بندًا مطابقًا في جدول التعرفة. جرّب وصفًا آخر للمنتج أو رقم البند.'
    lines = [f"{format_code(x['code'])} · {x['desc_ar']} · الرسم: {x['duty']}\n  ({(x.get('context_ar') or '')[:120]})"
             for x in items[:limit]]
    return ('بنود محتملة من ' + SOURCE_NOTE + ':\n' + '\n'.join(lines) +
            '\nتصنيف مبدئي؛ البند النهائي يؤكده المخلص في فسح حسب مواصفات المنتج.')


def search_many(terms_ar=None, terms_en=None, limit=12):
    """Search several phrasings (tariff wording works best) and merge the best distinct lines."""
    terms_ar = [t for t in (terms_ar if isinstance(terms_ar, list) else [terms_ar]) if t][:3]
    terms_en = [t for t in (terms_en if isinstance(terms_en, list) else [terms_en]) if t][:3]
    pairs = [(terms_ar[i] if i < len(terms_ar) else '', terms_en[i] if i < len(terms_en) else '')
             for i in range(max(len(terms_ar), len(terms_en)))]
    merged = {}
    for ar, en in pairs:
        for item in search(ar, en, limit=6):
            best = merged.get(item['code'])
            if not best or float(item.get('score') or 0) > float(best.get('score') or 0):
                merged[item['code']] = item
    return sorted(merged.values(), key=lambda x: -float(x.get('score') or 0))[:limit]
