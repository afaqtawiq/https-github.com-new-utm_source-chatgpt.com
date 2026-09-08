SERVICE_RULES=[('التخليص الجمركي',['تخليص','جمرك','customs','broker','clearance']),('النقل البري',['نقل','شاحن','transport','trucking','fleet']),('الشحن',['شحن','freight','shipping','بحري','جوي']),('التخزين',['مستودع','تخزين','warehouse','warehousing','storage']),('الباب إلى الباب',['باب إلى باب','door to door','last mile'])]
INTENT_RULES=[('High',['طلب عروض','مناقصة','rfq','rfx','tender','request for quotation','request for proposal']),('Medium',['تبحث عن','مطلوب','seeking','looking for provider','vendor'])]

def analyze(opportunity):
    text=' '.join(str(opportunity.get(k,'') or '') for k in ('company_name','signal','source_url')).lower()
    services=[]
    for service,terms in SERVICE_RULES:
        if any(t.lower() in text for t in terms): services.append(service)
    intent='Low'
    for level,terms in INTENT_RULES:
        if any(t.lower() in text for t in terms): intent=level; break
    score=int(opportunity.get('score') or 0)
    if score>=80 or intent=='High': priority='P1'
    elif score>=60 or intent=='Medium': priority='P2'
    else: priority='P3'
    evidence=(opportunity.get('signal') or '').strip()[:1400]
    rationale=[]
    if services:rationale.append('الخدمات المطابقة: '+', '.join(services))
    rationale.append('قوة نية الشراء: '+intent)
    rationale.append('درجة الفرصة: '+str(score)+'/100')
    next_action='مراجعة المصدر والتحقق من اسم الجهة والموعد والمتطلبات، ثم اعتماد مسودة العرض ومهمة المتابعة.' if priority!='P3' else 'استكمال البحث والتأهيل قبل تخصيص وقت مبيعات.'
    service_text='، '.join(services) if services else 'الخدمات اللوجستية المناسبة بعد التحقق من المتطلبات'
    company=(opportunity.get('company_name') or 'الجهة').strip()
    proposal=('مسودة داخلية — غير مرسلة\n\nالسادة/ '+company+'،\n'
              'استنادًا إلى الإشارة العامة المرصودة، يمكن لآفاق طويق دراسة تقديم '+service_text+'. '
              'تشمل الخطوة التالية مراجعة نطاق العمل والمتطلبات والمنافذ أو المسارات ذات الصلة، ثم إعداد عرض فني وتجاري دقيق.\n\n'
              'مهم: يجب التحقق من الجهة والموعد وجميع المتطلبات من المصدر الرسمي قبل اعتماد أو إرسال أي عرض.')
    return {'priority':priority,'intent':intent,'services':services,'rationale':' | '.join(rationale),'evidence':evidence,'next_action':next_action,'proposal_draft':proposal}
