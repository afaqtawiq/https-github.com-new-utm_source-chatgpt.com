SERVICE_RULES=[('Customs Clearance',['تخليص','جمرك','customs','broker','clearance']),('Transport',['نقل','شاحن','transport','trucking','fleet']),('Shipping',['شحن','freight','shipping','بحري','جوي']),('Warehousing',['مستودع','تخزين','warehouse','warehousing','storage']),('Door to Door',['باب إلى باب','door to door','last mile'])]
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
    rationale=[]
    if services:rationale.append('الخدمات المطابقة: '+', '.join(services))
    rationale.append('قوة نية الشراء: '+intent)
    rationale.append('درجة الفرصة: '+str(score)+'/100')
    next_action='مراجعة المصدر والتحقق من الجهة والموعد والمتطلبات قبل إعداد عرض.' if priority!='P3' else 'استكمال البحث والتأهيل قبل تخصيص وقت مبيعات.'
    return {'priority':priority,'intent':intent,'services':services,'rationale':' | '.join(rationale),'next_action':next_action}
