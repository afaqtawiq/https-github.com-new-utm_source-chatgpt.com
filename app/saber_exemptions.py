"""Owner-approved SABER exceptions (محمد عبدالعزيز, 20 Nov 2026, from the office's clearance practice):
these goods are cleared without SABER. Other authorities' requirements (e.g. SFDA for medical items) still apply.
The owner can add more items through Faisal («سجّل مادة مستثناة من سابر: ...»).
"""
import re

DEFAULTS = (
    ('الفحم النباتي', r'فحم\s*(ال)?(نباتي|خشبي|شجر|شيشه|شيشة)|charcoal', ''),
    ('سلندر (أسطوانة) غاز الطهي', r'(سلندر|سلندرات|اسطوان[ةه]|أسطوان[ةه]|اسطوانات|أسطوانات|جر[ةه])\s*(ال)?غاز|gas\s*cylinder|lpg\s*cylinder', ''),
    ('أنبوب درب الحقن (أطقم المحاليل الوريدية)', r'درب\s*(ال)?حقن|انبوب\s*(ال)?درب|أنبوب\s*(ال)?درب|\bدرب\b.*(وريد|محلول|محاليل)|i\.?v\.?\s*set|infusion\s*set',
     'منتج طبي: تبقى متطلبات هيئة الغذاء والدواء (تسجيل الجهاز الطبي/إذن الفسح).'),
    ('أحواض غسيل المراكز الصحية', r'(احواض|أحواض|حوض)\s*(ال)?(غسيل|غسل)?.{0,25}(مراكز\s*(ال)?صحي|مركز\s*صحي|مستشف|طبي|عياد)', ''),
)
NOTE = 'حسب اعتماد مكتب آفاق طويق: تُفسح بدون سابر.'
_READY = False


def init():
    global _READY
    if _READY:
        return
    from app.storage import db
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS saber_exemptions(id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE,
            note TEXT, added_by TEXT, created_at TIMESTAMPTZ NOT NULL)''')
    _READY = True


def _norm(text):
    text = re.sub(r'[إأآ]', 'ا', str(text or '').lower())
    return re.sub(r'\s+', ' ', text.replace('ة', 'ه').replace('ى', 'ي')).strip()


def _added():
    try:
        from app.storage import db
        init()
        with db() as c:
            return c.execute('SELECT name,note FROM saber_exemptions ORDER BY id').fetchall()
    except Exception:
        return []


def match(text):
    """The office-approved exception the text is about, or None: {'name', 'note'}."""
    t = str(text or '')
    for name, pattern, note in DEFAULTS:
        if re.search(pattern, t, re.I):
            return {'name': name, 'note': note}
    n = _norm(t)
    for row in _added():
        if _norm(row['name']) and _norm(row['name']) in n:
            return {'name': row['name'], 'note': row.get('note') or ''}
    return None


def listing():
    items = [(n, note) for n, _, note in DEFAULTS] + [(r['name'], r.get('note') or '') for r in _added()]
    return 'مواد معتمدة من المكتب بدون سابر:\n' + '\n'.join(f'• {n}' + (f' — {note}' if note else '') for n, note in items)


def add(name, note='', actor=''):
    name = ' '.join(str(name or '').split())[:120]
    if len(name) < 3:
        return 'اكتب اسم المادة.'
    from app.storage import db, utcnow
    init()
    with db() as c:
        c.execute('INSERT INTO saber_exemptions(name,note,added_by,created_at) VALUES(%s,%s,%s,%s) ON CONFLICT(name) DO UPDATE SET note=EXCLUDED.note',
                  (name, str(note or '')[:200], actor, utcnow()))
    return f'✅ سجّلت «{name}» ضمن المواد المعتمدة بدون سابر.\n' + listing()


def reply(item):
    return (f"«{item['name']}»: {NOTE}" + (f"\n{item['note']}" if item.get('note') else '') +
            '\nبقية المستندات المعتادة للتخليص (الفاتورة، بوليصة الشحن، شهادة المنشأ حسب الحالة) تبقى مطلوبة.')
