"""Escaped customer statement and internal DRAFT closing views."""
from urllib.parse import urlencode
from app import finance_view as v

LABELS = {'claim':'مطالبة مالية', 'receipt':'قبض مسجل', 'receivable_adjustment':'تسوية غير نقدية', 'opening_receivable':'إثبات رصيد افتتاحي'}


def query(report):
    return urlencode({key: report[key] for key in ('owner_id','counterparty_id','currency','start','end')})


def render_statement(session, report):
    e = v.esc
    currency = e(report['currency'])
    body = '<div class="actions no-print"><a class="btn secondary" href="/finance">العودة إلى المالية</a><a class="btn" href="/finance/monthly-statement.pdf?'+e(query(report))+'">تنزيل كشف العميل PDF</a></div>'
    body += v._hero('كشف حساب مفصل',report['counterparty_name']+' · '+report['start']+' إلى '+report['end'],eyebrow=report['owner_name'])
    body += '<div class="notice neutral">كشف حسب الحركات المثبتة حاليًا. تاريخ القيد العكسي هو يوم تسجيله بتوقيت الرياض. لا يعني الكشف تأكيد السداد خارج القيود المسجلة.</div>'
    body += '<section class="card"><dl class="detail-grid">'
    for key,label in (('opening','الرصيد قبل بداية الفترة'),('claims','مطالبات الفترة'),('receipts','القبض المسجل خلال الفترة'),('adjustments','التسويات غير النقدية'),('opening_movements','أرصدة افتتاحية أثبتت خلال الفترة'),('reversals','صافي القيود العكسية'),('closing','الرصيد في نهاية الفترة')):
        body += '<div><dt>'+label+'</dt><dd>'+v._number(report[key+'_display'])+' '+currency+'</dd></div>'
    body += '</dl></section>'
    rows = ''
    for item in report['movements']:
        title = ('عكس ' if item['phase']=='reversal' else '')+LABELS[item['kind']]
        rows += '<tr><td>'+e(item['effective_date'])+'</td><td>'+e(title)+' #'+e(item['document_id'])+'<span class="cell-sub">تاريخ المستند: '+e(item['document_date'])+'</span></td><td>'+e(item['invoice_ref'] or 'غير موثق')+'<span class="cell-sub">البيان: '+e(item['customs_ref'] or 'غير موثق')+'</span></td><td>'+v._number(item['debit_display'])+'</td><td>'+v._number(item['credit_display'])+'</td><td>'+v._number(item['running_display'])+'</td></tr>'
        if item['kind']=='claim':
            detail = item['claim_detail']
            if detail:
                text = 'قيمة البضاعة: '+str(detail['goods_amount'])+' '+str(detail['goods_currency'])+' · سعر التحويل: '+str(detail['exchange_rate'])+' · القيمة المحولة: '+str(detail['goods_value_display'])+' '+report['currency']+' · السجل: '+str(detail['registry_display'])+' · الضريبة: '+str(detail['tax_display'])+' · نسخة التفصيل: '+str(detail['revision'])
            else:
                text = 'تفصيل قيمة البضاعة وعملتها وسعر التحويل والسجل والضريبة غير موثق لهذه المطالبة'
            rows += '<tr><td colspan="6" class="quiet">'+e(text)+'</td></tr>'
    body += '<section class="card">'+v._table(['التاريخ','الحركة','الفاتورة / البيان','مدين','دائن','الرصيد الجاري'],rows or '<tr><td colspan="6">لا توجد حركات خلال الفترة</td></tr>','حركات الفترة · '+report['currency'])+'</section>'
    body += '<p class="legal">قيمة البضاعة للمعلومية ولا تضاف إلى إجمالي المطالبات. الأرصدة الافتتاحية أرصدة سابقة وليست مطالبات جديدة. الكشف ليس فاتورة ضريبية. لم يجهز إرسال تلقائي لهذا الكشف.</p>'
    return v._page(session,'كشف حساب مفصل',body)


def selector_forms(parties,can_view_profit=False):
    body = '<section class="card"><h2>تقارير شهرية</h2><p class="quiet">اختيار صريح للطرف والعملة والفترة، دون إرسال خارجي</p><form method="get" action="/finance/monthly-statement"><div class="formgrid">'
    body += v._select('owner_id','صاحب الحساب',v._party_options(parties,'owner'),required=True)
    body += v._select('counterparty_id','العميل',v._party_options(parties,'counterparty'),required=True)
    body += v._select('currency','العملة',v.CURRENCIES,required=True)
    body += v._field('start','من تاريخ',kind='date',required=True)+v._field('end','إلى تاريخ',kind='date',required=True)
    body += '</div><div class="actions"><button class="btn secondary">كشف العميل المفصل</button></div></form>'
    if not can_view_profit:return body+'</section>'
    body += '<div class="divider"></div><form method="get" action="/finance/monthly-closing"><div class="formgrid">'
    body += v._select('owner_id','صاحب حساب الإقفال',v._party_options(parties,'owner'),required=True)+v._field('month','شهر الإقفال',kind='month',required=True)
    return body+'</div><div class="actions"><button class="btn secondary">مسودة إقفال الشهر</button></div></form></section>'

CLOSING_AMOUNTS = (
    ('shared_service_income_minor','إيراد خدمات ضمن شواهد (قبل المصروفات)'),
    ('agency_only_income_minor','إيراد خاص بالوكالة بالكامل'),
    ('saber_revenue_minor','إيراد سابر، هامشه للوكالة بالكامل'),
    ('tax_reserve_minor','احتياطي الضريبة منفصل عن الربح'),
    ('pass_through_minor','مبالغ محصلة لحساب الغير'),
    ('goods_value_minor','قيمة البضاعة للمعلومية فقط'),
    ('shared_actual_cost_minor','تكلفة فعلية على نشاط شواهد'),
    ('agency_only_actual_cost_minor','تكلفة فعلية على نشاط الوكالة الخاص'),
    ('saber_fixed_cost_minor','تكلفة سابر الثابتة المعتمدة للتقرير فقط'),
)


def _amount(value,currency):
    from app.finance_core import display_minor
    return 'غير مكتمل' if value is None else display_minor(value,currency)+' '+currency


def render_closing(session, report):
    e=v.esc
    query=urlencode(dict(owner_id=report['owner_id'],month=report['month']))
    body='<div class="actions no-print"><a class="btn secondary" href="/finance">العودة إلى المالية</a><a class="btn" href="/finance/monthly-closing.pdf?'+e(query)+'">تنزيل مسودة الإقفال PDF</a></div>'
    body+=v._hero('مسودة إقفال الشهر وتوزيع الربح',report['owner_name']+' · '+report['month'],eyebrow='داخلي · DRAFT')
    body+='<div class="notice danger">هذا تقرير إعداد داخلي فقط. لا يعتمد توزيعًا ولا يرحّل ربحًا ولا ينفذ دفعًا. صافي الذمم ليس ربحًا، وقيمة البضاعة ليست إيرادًا. احتياطي الضريبة منفصل عن الأرباح.</div>'
    body+='<div class="notice">اقتراح شواهد بعد المصروفات الفعلية: 50% للوكالة و50% لشريك شواهد. هامش سابر بالكامل للوكالة. لا تطبق أي نسبة مدير أو قاعدة ترانزيت غير محسومة. لا تستنتج الضريبة أو الزكاة أو سعر التحويل من مبالغ المطالبات.</div>'
    body+='<section class="card"><h2>حالة اكتمال الإعداد</h2>'
    body+=('<p>الحساب مكتمل كاقتراح للمراجعة فقط</p>' if report['ready_for_distribution'] else '<p>التوزيع غير متاح حتى استكمال البنود التالية</p>')
    body+='<ul>'+''.join('<li>'+e(b)+'</li>' for b in report['blockers'])+'</ul></section>'
    for bucket in report['currencies']:
        cur=bucket['currency']
        body+='<section class="card"><h2>'+e(cur)+'</h2><dl class="detail-grid">'
        for key,label in CLOSING_AMOUNTS+(('shared_profit_minor','صافي شواهد بعد التكاليف'),('agency_only_profit_minor','صافي نشاط الوكالة الخاص، شامل سابر'),('profit_minor','صافي الربح المحسوب'),('agency_share_minor','حصة الوكالة المقترحة'),('partner_share_minor','حصة شريك شواهد المقترحة')):
            body+='<div><dt>'+e(label)+'</dt><dd>'+e(_amount(bucket.get(key),cur))+'</dd></div>'
        body+='</dl><p class="hint">عند وجود نصف وحدة نقدية في القسمة تؤول الوحدة المتبقية للشريك؛ يظل التقريب مقترحًا للمراجعة.</p></section>'
    body+='<section class="card"><h2>مطابقة مستندات الشهر</h2><p class="quiet">المطالبة تصنف إلى خدمات وضريبة ومبالغ للغير، ولا تعتبر المصروفات مدفوعة لمجرد إثباتها. تسجل التكاليف الفعلية مرة واحدة كمستندات مصروفات مستقلة. يمكن إثبات تكلفة سابر ثابتة معتمدة للتقرير فقط دون قيد التزام أو دفع، ولا تجمع مع تكلفة فعلية مكررة.</p>'
    if not report['documents']:body+='<p>لا توجد مستندات دخل أو تكلفة خلال الشهر. يلزم تأكيد اكتمال المصدر قبل الاستنتاج.</p>'
    for d in report['documents']:
        body+='<details><summary>#'+e(d['document_id'])+' · '+e(d['counterparty_name'])+' · '+e(v.KINDS[d['kind']])+' · '+e(d['document_date'])+' · '+e(_amount(d['amount_minor'],d['currency']) if d['currency'] and d['amount_minor'] is not None else 'مبلغ أو عملة غير مكتملين')+'</summary>'
        body+='<p>'+e(v.STATUSES[d['status']])+' · الفاتورة: '+e(d['invoice_ref'])+' · البيان: '+e(d['customs_ref'])+' · نسخة التصنيف: '+e(d['mapping_revision'] or 'لم يصنف')+'</p>'
        mapping=d['mapping'] or {}
        if v._can_approve(session) and d['status']=='posted' and d['kind'] in ('claim','expense'):
            body+='<form method="post" action="/finance/documents/'+str(d['document_id'])+'/closing-input">'+v._tokens(session)+'<input type="hidden" name="expected_revision" value="'+str(d['mapping_revision'] or 0)+'"><input type="hidden" name="expected_detail_revision" value="'+str(d.get('claim_detail_revision') or 0)+'"><div class="formgrid">'
            body+=v._select('basis_status','حالة أساس احتساب الإيراد',[('unresolved','غير محسوم'),('undefined','غير معرف'),('confirmed','موثق ومؤكد')],value=mapping.get('basis_status','unresolved'),blank=None)
            for name,label in (('basis_ref','مرجع إثبات أساس احتساب الإيراد / التكلفة'),('allocation_ref','مرجع اعتماد تصنيف النشاط وحصة شواهد / الوكالة')):
                body+=v._field(name,label,value=mapping.get(name,''),required=True,attrs='maxlength="1000"')
            for name,label in CLOSING_AMOUNTS:
                val=mapping.get(name,0 if name=='saber_fixed_cost_minor' else None)
                from app.finance_core import display_minor
                body+=v._field(name,label+' ('+d['currency']+')',value='' if val is None else display_minor(val,d['currency']),hint='اتركه فارغًا إن لم يتأكد؛ صفر يعني صفرًا مؤكدًا',attrs='inputmode="decimal" dir="ltr"')
            body+=v._field('saber_fixed_cost_ref','مرجع موافقة صاحب الحساب على تكلفة سابر الثابتة',value=mapping.get('saber_fixed_cost_ref',''),hint='التكلفة الثابتة لا تثبت السداد ولا تسجل مرة أخرى كمصروف لنفس الشحنة',attrs='maxlength="1000"')
            body+='<label class="check"><input name="saber_fixed_cost_approved" type="checkbox" value="1"'+(' checked' if mapping.get('saber_fixed_cost_approved') else '')+'><span>توجد موافقة صريحة من صاحب الحساب على تكلفة سابر الثابتة لهذه المطالبة، للتقرير فقط</span></label>'
            body+=v._field('related_document_id','معرف المطالبة المرتبطة بالتكلفة (للمصروف فقط)',value=mapping.get('related_document_id') or '',kind='number',attrs='min="1" step="1"')
            body+=v._field('reason','سبب المراجعة ومرجع دليل التكلفة',required=True,kind='textarea',attrs='maxlength="1000"')+'</div>'
            body+='<label class="check"><input name="costs_complete" type="checkbox" value="1"'+(' checked' if mapping.get('costs_complete') else '')+'><span>اكتملت التكاليف الفعلية المتعلقة بهذه الحركة؛ لا توجد تكاليف منتظرة</span></label>'
            body+='<label class="check"><input name="confirmation" type="checkbox" value="1" required><span>راجعت التصنيف ودليله؛ هذه بيانات تقرير فقط ولا تثبت قبضًا أو دفعًا ولا تنشئ قيدًا</span></label><div class="actions"><button class="btn secondary">حفظ مراجعة التصنيف</button><button class="btn secondary" type="reset">إلغاء التغييرات</button></div></form>'
        else:
            body+='<ul>'+''.join('<li>'+e(label)+': '+e(_amount(mapping.get(name),d['currency']) if d['currency'] else 'غير مكتمل')+'</li>' for name,label in CLOSING_AMOUNTS)+'</ul>'
        body+='</details>'
    body+='</section>'
    if v._can_approve(session):
        body+='<section class="card no-print"><h2>مراجعة اكتمال الشهر</h2><p class="quiet">مرتبطة بهذه النسخة من المستندات وتصنيفاتها. أي تغيير يتطلب إعادة المراجعة.</p><form method="post" action="/finance/monthly-closing/'+str(report['owner_id'])+'/'+e(report['month'])+'/review">'+v._tokens(session)+'<input type="hidden" name="expected_revision" value="'+str(report['review_revision'])+'"><input type="hidden" name="snapshot_hash" value="'+e(report['snapshot_hash'])+'">'
        for name,label in (('income_complete','تمت مطابقة جميع إيرادات الشهر، بما فيها العمليات غير المسجلة سابقًا'),('expenses_complete','اكتملت جميع المصروفات والتكاليف الفعلية للشهر ولا توجد تكاليف منتظرة'),('mapping_complete','حُسمت أسس احتساب الإيراد والضريبة والمبالغ للغير ونسب الأنشطة بدليل موثق')):
            body+='<label class="check"><input name="'+name+'" type="checkbox" value="1"><span>'+label+'</span></label>'
        body+=v._field('confirmation_ref','مرجع المطابقة واعتماد اكتمال المدخلات',required=True,kind='textarea',attrs='maxlength="1000"')+'<label class="check"><input name="confirmation" type="checkbox" value="1" required><span>مراجعة إعداد التقرير فقط، دون اعتماد أرباح أو تحويلها</span></label><button class="btn secondary">حفظ مراجعة الاكتمال</button></form></section>'
    return v._page(session,'مسودة إقفال الشهر',body)
