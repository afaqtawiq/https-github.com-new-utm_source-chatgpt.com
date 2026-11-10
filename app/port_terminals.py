"""Jeddah Islamic Port terminal operators and port storage (owner request, 10 Nov 2026).

Sources reviewed 10 Nov 2026: RSGT e-portal and FAQ, DP World Jeddah FAQ/contact pages, and the Law of Port Service
Tariffs and Fees as published by RSGT (Feb 2026); see the project doc «jeddah-terminal-operators-guide-2026-11-10».
Port storage (أرضيات الميناء) is SEPARATE from the shipping line's detention; both run together.
Kept outside customs_knowledge.KNOWLEDGE on purpose (that text is hash-pinned for the public excerpt).
"""
import datetime as dt

FREE_DAYS = 3
# (from_day, to_day|None, SAR/day 20ft, SAR/day 40ft) — import loaded containers, counted from the discharge day.
IMPORT_TIERS = ((4, 10, 350, 450), (11, 15, 400, 500), (16, None, 500, 600))
REVIEWED = '10 نوفمبر 2026'

KNOWLEDGE = """

18) مشغلو محطات الحاويات في ميناء جدة الإسلامي وأجور الميناء — مراجعة المصادر الرسمية 10 نوفمبر 2026
- الهيئة العامة للموانئ (موانئ) تشرف وتنظم وتصدر لائحة الأجور ولا تشغل المحطات. المشغلان: «بوابة البحر الأحمر RSGT» (المحطة الشمالية، الأكبر) و«موانئ دبي العالمية – جدة DP World» (المحطة الجنوبية). الحاوية تنزل في إحداهما حسب الباخرة؛ تُعرف المحطة بالبحث برقم الحاوية أو البوليصة أو البيان في بوابة المشغل.
- بوابة البحر الأحمر: البوابة portal.rsgt.com (تتبع بالحاوية/البوليصة/البيان، جدول البواخر، الفواتير والدفع). خدمة العملاء 920007025 والبريد c.s@rsgt.com. المطالبات rsgtclaims@rsgt.com ويُبلّغ عن الضرر خلال 24–48 ساعة من الاستلام. التسليم 24 ساعة بعد سداد فاتورة المحطة.
- موانئ دبي – جدة: الموقع dpworld.sa (تسجيل بدور مستورد أو مخلص). خدمة العملاء dpwjed.customerservice@dpworld.com وجوال 0533345029. الفواتير Billingdpwjeddah@dpworld.com. الدفع من محفظة مسبقة الدفع في الموقع وتصدر فاتورتان (فاتورة الميناء وفاتورة موانئ دبي)، وبعد السداد يُرفع البيان النهائي ليصدر تصريح البوابة.
- أرضيات الميناء (تخزين الحاوية الواردة المحملة، على صاحب البضاعة، من يوم التنزيل، للمحطتين): الأيام 1–3 مجانًا؛ 4–10: 350 ريال/يوم (20 قدم) و450 (40 قدم)؛ 11–15: 400 و500؛ من اليوم 16: 500 و600. البضائع الخطرة (فئات 1 و5 و7) أعلى، والحمولات خارج المقاس 3 أضعاف.
- أرضيات الميناء غير غرامة تأخير الحاوية عند الوكيل الملاحي (الديمرج/الديتنشن)؛ كل واحدة لها أيام سماح وفاتورة مستقلة وتُحسبان معًا.
- أجور أخرى على صاحب البضاعة حسب اللائحة: مناولة الحاوية الواردة 330 (20 قدم) و550 (40 قدم)؛ المعاينة الجمركية في جدة 492 (20 قدم) و588 (أكبر)؛ عدم الحضور لموعد المعاينة 240؛ إعادة الفحص بالأشعة بسبب خطأ المستندات 577؛ الحاوية المبردة بعد 3 أيام 200 ريال/يوم.
- هذه أجور اللائحة المنشورة وليست فاتورة؛ المبلغ النهائي حسب فاتورة المشغل الرسمية. لا تعد العميل بإعفاء أو تمديد من أرضيات الميناء.
"""


def size_key(size):
    return 20 if str(size or '').strip().startswith('2') else 40


def storage(discharged, size=None, until=None):
    """Port storage for an import loaded container. Day 1 = discharge day. Returns dict(days, chargeable, cost, next, free_until)."""
    until = until or dt.date.today()
    days = max((until - discharged).days + 1, 0)
    col = 2 if size_key(size) == 20 else 3
    cost = 0
    for lo, hi, *rates in IMPORT_TIERS:
        if days >= lo:
            cost += (min(days, hi if hi else days) - lo + 1) * rates[col - 2]
    nxt = next((r[col] for r in IMPORT_TIERS if r[0] <= days + 1 and (r[1] is None or days + 1 <= r[1])), 0)
    return {'days': days, 'chargeable': max(days - FREE_DAYS, 0), 'cost': cost, 'next': nxt,
            'free_until': discharged + dt.timedelta(days=FREE_DAYS - 1)}


def storage_text(discharged, size=None, until=None, label=''):
    s = storage(discharged, size, until)
    head = f"أرضيات الميناء{(' — ' + label) if label else ''} (حاوية {size_key(size)} قدم، نزلت {discharged.strftime('%d/%m/%Y')}):"
    if not s['chargeable']:
        left = (s['free_until'] - (until or dt.date.today())).days
        return (f"{head} داخل الأيام المجانية — آخر يوم مجاني {s['free_until'].strftime('%d/%m')}"
                + (f' (باقي {left} يوم)' if left > 0 else ' (اليوم)') + f"، وبعده {IMPORT_TIERS[0][2 if size_key(size) == 20 else 3]} ريال/يوم.")
    return (f"{head} {s['days']} يوم في الميناء، منها {s['chargeable']} بأجر = {s['cost']:,.0f} ريال تقريبًا، ويزيد {s['next']:,.0f} ريال غدًا. "
            'حسب لائحة أجور الموانئ؛ المبلغ النهائي بفاتورة المشغل، وهو غير غرامة الوكيل الملاحي.')
