"""Sales & marketing playbooks for Reem's department (owner, 24 Nov 2026: «عايز كل المهارات» في قسم المبيعات والتسويق).

app/sales_playbooks/ holds 50 expert playbooks (Corey Haines' MIT «marketing-skills» library: prospecting, cold email,
ads, ad creative, social, copywriting, offers, pricing, PR, events, referrals, CRO, SEO, marketing plans, sales
enablement…) plus Afaq Tuwaiq's own B2B-outreach and brand-content skills. The sales_playbook tool returns the guide
that fits a task, so the department follows a proven method before it drafts a campaign, a cold email or an offer.
"""
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), 'sales_playbooks')
OWN = {
    'afaq-b2b-outreach': 'Afaq Tuwaiq B2B sales campaigns: verified logistics/import leads, bilingual outreach emails/WhatsApp, lead tracker',
    'afaq-brand-content': 'Afaq Tuwaiq marketing content: videos, posts, ads, designs, captions with the approved logo, petrol/gold brand, cinematic style',
    'afaq-video-production': 'Afaq Tuwaiq video desk: which video tool (cinematic_video paid AI commercial, stock_video free), scripts, hooks, storyboards, shot prompts, editing, platform specs, captions, cadence',
}
# Arabic words the owner and the team use -> playbooks
ARABIC = {
    'afaq-b2b-outreach': ('حملة', 'حملات', 'تواصل', 'رسالة تعريف', 'شركات الشحن', 'المستوردين', 'b2b'),
    'afaq-video-production': ('فيديو', 'فديو', 'ريلز', 'ريل', 'يوتيوب', 'شورتس', 'تيك توك', 'سناب', 'سكربت', 'سيناريو', 'ستوري بورد',
                              'مونتاج', 'سينمائي', 'اعلان فيديو', 'إعلان فيديو', 'لقطات', 'تصوير', 'video', 'reel'),
    'afaq-brand-content': ('هوية', 'شعار', 'براند', 'تصميم', 'بوستر', 'محتوى آفاق'),
    'cold-email': ('بريد بارد', 'ايميل بارد', 'إيميل بارد', 'رسالة باردة', 'متابعة', 'follow'),
    'prospecting': ('عملاء محتملين', 'عملاء جدد', 'ابحث', 'قائمة شركات', 'استهداف', 'leads'),
    'ads': ('اعلان', 'إعلان', 'اعلانات', 'إعلانات', 'ممول', 'جوجل', 'سناب', 'ميتا'),
    'ad-creative': ('نص اعلان', 'نص إعلان', 'كريتف', 'صورة اعلان'),
    'social': ('سوشيال', 'منشور', 'بوست', 'تيك توك', 'انستغرام', 'إنستغرام', 'لينكدان', 'فيسبوك', 'تقويم محتوى'),
    'content-strategy': ('خطة محتوى', 'استراتيجية محتوى', 'مواضيع'),
    'copywriting': ('صياغة', 'نص', 'كتابة', 'صفحة هبوط', 'الموقع'),
    'copy-editing': ('تدقيق', 'تحسين النص', 'راجع النص'),
    'offers': ('عرض', 'عروض', 'باقة', 'خصم', 'ضمان'),
    'pricing': ('تسعير', 'اسعار', 'أسعار', 'باقات'),
    'emails': ('سلسلة رسائل', 'نشرة', 'رسائل متتابعة', 'ايميلات'),
    'sms': ('واتساب', 'رسائل نصية', 'sms'),
    'marketing-plan': ('خطة تسويق', 'خطة تسويقية', 'خطة مبيعات', '90 يوم', 'ربع سنة'),
    'marketing-ideas': ('افكار', 'أفكار', 'فكرة'),
    'marketing-psychology': ('اقناع', 'إقناع', 'علم نفس', 'سلوك العميل'),
    'public-relations': ('علاقات عامة', 'صحافة', 'خبر صحفي', 'اعلام', 'إعلام'),
    'events': ('معرض', 'معارض', 'فعالية', 'مؤتمر', 'ويبينار'),
    'referrals': ('احالة', 'إحالة', 'توصية', 'عمولة وسيط', 'شركاء'),
    'co-marketing': ('شراكة', 'شراكات', 'تسويق مشترك'),
    'competitor-profiling': ('منافس', 'منافسين', 'المنافسة'),
    'customer-research': ('بحث عملاء', 'استبيان', 'مقابلات العملاء', 'رأي العملاء'),
    'sales-enablement': ('عرض تقديمي', 'بروشور', 'دليل المبيعات', 'اعتراضات', 'pitch'),
    'cro': ('تحويل', 'نموذج', 'زيادة الطلبات'),
    'seo-audit': ('سيو', 'seo', 'جوجل بحث', 'ترتيب'),
    'ai-seo': ('ذكاء اصطناعي', 'شات جي بي تي', 'chatgpt'),
    'video': ('فيديو', 'ريلز', 'يوتيوب'),
    'image': ('صورة', 'صور', 'جرافيك'),
    'lead-magnets': ('مغناطيس', 'دليل مجاني', 'ملف مجاني'),
    'launch': ('اطلاق', 'إطلاق', 'خدمة جديدة'),
    'influencer-marketing': ('مؤثر', 'مشاهير', 'سناب شات مشهور'),
    'churn-prevention': ('عملاء قدامى', 'استرجاع', 'فقدنا', 'احتفاظ'),
    'analytics': ('تحليلات', 'قياس', 'تتبع'),
}


def index():
    """{name: when-to-use} for every playbook on disk."""
    found = {}
    path = os.path.join(ROOT, 'INDEX.md')
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            m = re.match(r'\|\s*`([a-z0-9-]+)`\s*\|\s*(.+?)\s*\|\s*$', line)
            if m:
                found[m.group(1)] = m.group(2)
    found.update(OWN)
    return {k: v for k, v in found.items() if os.path.exists(os.path.join(ROOT, k, 'GUIDE.md'))}


def choose(topic, limit=3):
    """Best playbooks for a free-text task (Arabic or English)."""
    text = ' ' + str(topic or '').lower() + ' '
    scores = {}
    for name, use in index().items():
        score = 0
        if name in text or name.replace('-', ' ') in text:
            score += 10
        for word in ARABIC.get(name, ()):
            if word.lower() in text:
                score += 4
        for word in re.findall(r'[a-z]{4,}', use.lower()):
            if word in text:
                score += 1
        if score:
            scores[name] = score
    if 'افاق' in text or 'آفاق' in text or 'طويق' in text:
        for name in ('afaq-b2b-outreach', 'afaq-brand-content', 'afaq-video-production'):
            if name in scores:
                scores[name] += 3
    if 'afaq-video-production' in scores:  # our own video desk comes before the generic AI-video guide
        scores['afaq-video-production'] += 2
    return [n for n, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:limit]]


def guide(name, limit=14000):
    path = os.path.join(ROOT, re.sub(r'[^a-z0-9-]', '', str(name or '')), 'GUIDE.md')
    if not os.path.exists(path):
        return ''
    text = open(path, encoding='utf-8').read()
    return text if len(text) <= limit else text[:limit] + '\n\n[…الدليل أطول؛ اطلب قسمًا محددًا من المراجع إن احتجت]'


def reference(name, heading, limit=8000):
    """One section of a playbook's REFERENCES.md, found by its heading words."""
    path = os.path.join(ROOT, re.sub(r'[^a-z0-9-]', '', str(name or '')), 'REFERENCES.md')
    if not os.path.exists(path):
        return ''
    text = open(path, encoding='utf-8').read()
    want = str(heading or '').lower().strip()
    parts = re.split(r'(?m)^(?=#{1,3} )', text)
    for part in parts:
        first = part.splitlines()[0].lower() if part.strip() else ''
        if want and want in first:
            return part[:limit]
    return ''


def answer(topic='', name='', heading=''):
    """The tool's reply: the chosen playbook (or a reference section) and the other fitting ones."""
    catalog = index()
    if name and heading:
        return reference(name, heading) or f'لا يوجد قسم «{heading}» في مراجع {name}.'
    picks = [name] if name in catalog else choose(topic)
    if not picks:
        return ('ما لقيت دليلًا مطابقًا. الأدلة المتاحة: ' + '، '.join(sorted(catalog)) +
                '\nاطلبي باسم الدليل (مثل cold-email أو prospecting أو offers).')
    main = picks[0]
    others = [p for p in picks[1:]]
    return (f'📘 دليل «{main}» — {catalog.get(main, "")}\n'
            'اتبعي الدليل بلغة السوق الخليجي وبمعلومات آفاق طويق المعروفة (لا تخترعي أرقامًا أو عملاء).\n\n'
            + guide(main)
            + (('\n\nأدلة أخرى مناسبة: ' + '، '.join(others)) if others else ''))
