"""Afaaq customer answers and conservative intake; no quotes or carrier claims."""
import re

WELCOME = 'أهلًا وسهلًا بك في آفاق طويق 🌷\nنساعدك في التخليص الجمركي والنقل والشحن والتخزين وخدمات الباب إلى الباب.'
QUESTIONS = [('service','كيف نقدر نخدمك؟'), ('route','ما ميناء الوصول أو المنفذ الجمركي؟ وللنقل، ما نقطة الانطلاق والوجهة؟'), ('cargo','ما نوع البضاعة والوزن أو الكمية؟'), ('deadline','ما الموعد المتوقع أو المطلوب؟')]

def normalized(text):
    return re.sub(r'[\u064b-\u065f\u0670ـ]', '', text).translate(str.maketrans('أإآى','اااي')).strip().lower()

def reply(fields, pending, text, selection, updates, greeting):
    fields = dict(fields)
    raw = text.strip()
    t = normalized(raw)
    question = '?' in raw or '؟' in raw or bool(re.match(r'^(هل|كيف|متي|كم|ما هي|ماهي|ايش|وش|ممكن|اقدر)\b',t))
    answer = ''
    status_query = t in ('status','حالة الطلب','متابعة','الحالة')
    if 'بوليص' in t or 'بوالص' in t or 'bill of lading' in t:
        answer = ('نعم، البوليصة تساعد في متابعة الشحنة. اكتب رقم البوليصة واسم الخط الملاحي وميناء الوصول هنا. '
                  'تحليل مرفقات واتساب تلقائيًا غير مفعّل حاليًا، لذلك نحتاج هذه البيانات كتابةً. '
                  'موعد الوصول المذكور في المستند تقديري ويحتاج تأكيدًا من الخط الملاحي.')
    elif any(x in t for x in ('متي تصل','تاريخ الوصول','موعد الوصول','وصلت الشحنة')) and question:
        answer = 'لم أتحقق من موعد الوصول لدى الناقل بعد. اكتب رقم البوليصة واسم الخط الملاحي وميناء الوصول لتجهيز بيانات المتابعة؛ لا أستطيع تأكيد الوصول من الرسالة وحدها.'
    elif any(x in t for x in ('سعر','تكلفة','تكلفه','بكم','اسعار')) and question:
        answer = 'التكلفة تعتمد على تفاصيل الشحنة والخدمة. بعد استكمال البيانات وتوفير تكلفة التنفيذ، يُجهز عرض سعر لموافقة الإدارة قبل إرساله إليك.'
    elif any(x in t for x in ('مستند','اوراق','وثائق')) and question:
        answer = 'لتجهيز مراجعة الطلب نحتاج بيانات البوليصة والفاتورة وقائمة التعبئة ونوع البضاعة والمنفذ. أي مستندات إضافية تُحدد بعد مراجعة تفاصيل الشحنة.'
    elif any(x in t for x in ('خدماتكم','تقدمون','تقدمو','تخدمون')) and question:
        answer = 'نقدم التخليص الجمركي والنقل والشحن والتخزين وخدمات الباب إلى الباب في السعودية والخليج. ما الخدمة التي تحتاجها؟'
    # Labelled updates are explicit. Questions and greetings never fill a pending slot.
    if not selection and not greeting and not status_query:
        fields.update(updates)
        if not updates and not question and not answer:
            if 'تخليص' in t:
                fields['service'] = 'التخليص الجمركي'
                fields['shipment_context'] = raw[:12000]
                if 'بعد اسبوع' in t:
                    fields['deadline'] = 'بعد أسبوع حسب إفادة العميل؛ يحتاج تأكيد تاريخ الوصول'
            elif pending and raw:
                fields[pending] = raw[:12000]
            elif raw:
                fields['latest_follow_up'] = raw[:12000]
    missing = [(k,q) for k,q in QUESTIONS if not fields.get(k)]
    next_field = missing[0][0] if missing else None
    state = 'collecting' if missing else 'ready_for_review'
    if selection or greeting:
        answer = WELCOME
    elif status_query:
        labels = dict(service='الخدمة',route='المسار أو المنفذ',cargo='البضاعة',deadline='الموعد')
        answer = 'بيانات طلبك الحالية:\n' + '\n'.join(labels[k]+': '+str(fields[k]) for k,_ in QUESTIONS if fields.get(k))
    elif not answer and question:
        answer = 'أهلًا بك. هل استفسارك عن التخليص أو النقل أو الشحن أو التخزين؟ وضّح النقطة التي تحتاجها حتى أطلب المعلومات المناسبة، ولا أؤكد معلومة غير متوفرة.'
    elif not answer and 'تخليص' in t:
        answer = 'أهلًا بك، يمكننا تجهيز طلب التخليص الجمركي لشحنتك.'
        if 'مستعجل' in t: answer += ' ذكرت أن الطلب مستعجل؛ يلزم مراجعة الموعد والمستندات قبل تأكيد إمكانية التنفيذ.'
    elif not answer:
        answer = 'شكرًا لتوضيحك.'
    if missing:
        answer += '\n\n' + missing[0][1]
    elif not question and not greeting and not selection:
        answer += '\nاكتملت بيانات الطلب الأساسية للمراجعة وتجهيز عرض السعر بعد توفير تكلفة التنفيذ. تأكيد السعر أو الحجز يحتاج اعتمادًا.'
    return fields, next_field, state, answer
