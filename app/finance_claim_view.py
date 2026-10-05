"""Escaped itemization and customer-only claim HTML. No outbound actions."""
from html import escape
from uuid import uuid4
from app.finance_claim_core import COMPONENTS
from app.finance_core import CURRENCIES


def esc(value):
    return escape(str(value if value is not None else ''), quote=True)


def amount(value):
    return '<bdi dir="ltr">'+esc(value)+'</bdi>'


def claim_summary(document, detail):
    currency = esc(document['currency'])
    goods = ('<div class="claim-goods"><h3>قيمة فاتورة البضاعة</h3><p>'+amount(detail['goods_amount'])+' '+esc(detail['goods_currency'])+
             '</p><p>سعر التحويل الموثق: '+amount(detail['exchange_rate'])+' '+currency+' لكل '+esc(detail['goods_currency'])+
             '</p><p>قيمة البضاعة بعملة المطالبة: <strong>'+amount(detail['goods_value_display'])+' '+currency+
             '</strong></p><p class="hint">لبيان قيمة البضاعة فقط؛ لا تضاف إلى إجمالي المطالبة</p></div>')
    values = detail['component_display']
    rows = '<tr><td>1</td><td>جمارك<span class="claim-sub">جمرك: '+amount(values['customs_duty'])+' + رسوم أخرى: '+amount(values['customs_other'])+'</span></td><td>'+amount(detail['customs_total_display'])+'</td></tr>'
    for index, (key, label) in enumerate(COMPONENTS[2:], 2):
        rows += '<tr><td>'+str(index)+'</td><td>'+label+'</td><td>'+amount(values[key])+'</td></tr>'
    return goods+'<table class="claim-table"><caption>بنود المطالبة · '+currency+'</caption><thead><tr><th scope="col">#</th><th scope="col">البند</th><th scope="col">المبلغ</th></tr></thead><tbody>'+rows+'</tbody><tfoot><tr><th colspan="2" scope="row">إجمالي المطالبة دون قيمة البضاعة</th><td>'+amount(detail['claim_total_display'])+' '+currency+'</td></tr></tfoot></table>'


STYLE = '''<style>
.claim-goods{padding:16px 20px;border:1px solid #bcc9d1;border-radius:10px;margin:18px 0}.claim-goods p{margin:4px 0}.claim-table{width:100%;border-collapse:collapse;text-align:right}.claim-table caption{text-align:right;font-weight:bold;margin:12px 0}.claim-table td,.claim-table th{padding:12px 15px;border-bottom:1px solid #b5c4cb;white-space:normal}.claim-table td:last-child{text-align:left}.claim-table tfoot{font-size:17px;font-weight:bold}.claim-sub{display:block;font-size:11px;opacity:.8;margin-top:4px}.claim-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.claim-field{display:grid;gap:5px}.claim-field input,.claim-field textarea,.claim-field select{width:100%;padding:9px;box-sizing:border-box}.claim-wide{grid-column:1/-1}@media(max-width:600px){.claim-fields{grid-template-columns:1fr}.claim-table td,.claim-table th{padding:9px 5px}.claim-table tfoot{font-size:14px}}
</style>'''


def itemization_section(session, document):
    if document.get('kind') != 'claim':
        return ''
    detail = document.get('claim_details')
    active = document.get('status') in ('draft', 'reviewed', 'posted')
    body = STYLE+'<section class="card" id="claim-details"><h2>تفصيل المطالبة المالية</h2>'
    if detail:
        body += claim_summary(document, detail)
        body += '<p class="hint">نسخة التفصيل: '+esc(detail['id'])+' · مرجع المطابقة: '+esc(detail['source_ref'])+'</p>'
        if document.get('status') == 'posted':
            base = '/finance/documents/'+esc(document['id'])
            body += '<div class="actions no-print"><a class="btn" href="'+base+'/claim.pdf">تنزيل المطالبة PDF</a><a class="btn secondary" href="'+base+'/claim">معاينة نسخة العميل</a></div>'
        else:
            body += '<p class="hint">تنزيل نسخة العميل متاح للمطالبة المرحّلة النشطة فقط</p>'
    else:
        body += '<p>لم يسجل تفصيل منفصل لهذه المطالبة بعد. أضف قيمة البضاعة وبنود الرسوم من المصدر المعتمد.</p>'
    can_approve = session.get('can_approve_finance', session.get('role') == 'admin') and session.get('role') == 'admin'
    if can_approve and active and document.get('currency'):
        def field(name, label, value='', kind='text'):
            return '<label class="claim-field" for="claim-'+name+'">'+label+'<input id="claim-'+name+'" name="'+name+'" type="'+kind+'" value="'+esc(value)+'" required maxlength="32" inputmode="decimal" dir="ltr"></label>'
        data = detail or {}
        body += '<details class="no-print"'+(' open' if not detail else '')+'><summary>'+('تصحيح التفصيل بنسخة جديدة موثقة' if detail else 'تسجيل تفصيل المطالبة')+'</summary>'
        body += '<p class="hint">المجموع المطلوب: '+amount(document.get('amount_display'))+' '+esc(document['currency'])+'. يلزم إدخال كل بند بما فيه الصفر، وسعر التحويل الموثق. لا تُستنتج ضريبة أو زكاة أو رسوم تلقائيًا.</p>'
        body += '<form method="post" action="/finance/documents/'+esc(document['id'])+'/claim-details"><input type="hidden" name="csrf" value="'+esc(session.get('csrf'))+'"><input type="hidden" name="idempotency_key" value="'+str(uuid4())+'"><input type="hidden" name="expected_revision" value="'+esc(data.get('id',0))+'"><div class="claim-fields">'
        body += field('goods_amount','قيمة فاتورة البضاعة الأصلية',data.get('goods_amount',''))
        body += '<label class="claim-field" for="claim-goods-currency">عملة فاتورة البضاعة<select id="claim-goods-currency" name="goods_currency" required><option value="">اختر العملة الموثقة</option>'+''.join('<option value="'+code+'"'+(' selected' if code == data.get('goods_currency') else '')+'>'+code+'</option>' for code in CURRENCIES)+'</select></label>'
        body += field('exchange_rate','سعر التحويل إلى '+esc(document['currency'])+' لكل وحدة أصلية (1 لنفس العملة)',data.get('exchange_rate',''))
        for key,label in COMPONENTS:
            body += field(key,label+' · '+esc(document['currency']),data.get('component_display',{}).get(key,''))
        for name,label in (('source_ref','مرجع المصدر المعتمد للتفصيل'),('reason','سبب الإضافة أو التصحيح ومرجع اعتماده')):
            body += '<label class="claim-field claim-wide" for="claim-'+name+'">'+label+'<textarea id="claim-'+name+'" name="'+name+'" required maxlength="1000" rows="2">'+esc(data.get('source_ref','') if name == 'source_ref' else '')+'</textarea></label>'
        body += '</div><label class="check"><input type="checkbox" name="confirmation" value="1" required><span>راجعت البنود وقيمة البضاعة وسعر التحويل، ويطابق مجموع الرسوم مبلغ المطالبة دون إضافة البضاعة. أحفظ التفصيل للعرض فقط، وتبقى الأدلة الأصلية والقيود والأرصدة محفوظة.</span></label><div class="actions"><button class="btn" type="submit">حفظ التفصيل المعتمد</button><button class="btn secondary" type="reset">إلغاء التغييرات</button></div></form></details>'
    return body+'</section>'


def render_customer_claim(document, detail):
    base = '/finance/documents/'+esc(document['id'])
    pairs = [('صاحب المطالبة',document['owner_name']),('المطالبة إلى',document['counterparty_name']),('تاريخ المطالبة',document['document_date']),('رقم الفاتورة الأصلية',document['invoice_ref'] or 'غير محدد'),('البيان الجمركي',document['customs_ref'] or 'غير محدد'),('عملة المطالبة',document['currency'])]
    metadata = ''.join('<div><dt>'+label+'</dt><dd>'+esc(value)+'</dd></div>' for label,value in pairs)
    return '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مطالبة مالية تفصيلية</title>'+STYLE+'''<style>body{font:15px/1.8 Tahoma,Arial,sans-serif;color:#163342;background:#e9eef1;margin:0}.paper{max-width:780px;margin:30px auto;background:white;padding:36px;border-top:6px solid #b18b43}h1{margin:0;font-size:28px}h2{font-size:18px}.claim-meta{display:grid;grid-template-columns:1fr 1fr;gap:15px;border-bottom:1px solid #ccd7dd;padding-bottom:20px}dt{font-size:12px;color:#506472}dd{margin:0;overflow-wrap:anywhere}a{color:#174766;margin-left:20px}.hint{color:#506472;font-size:12px}.claim-ref{color:#667985;font-size:12px}.no-print{margin-bottom:24px}@media(max-width:600px){.paper{margin:0;padding:18px}.claim-meta{grid-template-columns:1fr}}@media print{@page{size:A4;margin:15mm}body{background:white}.paper{margin:0;padding:0;max-width:none}.no-print{display:none}tr,.claim-goods{break-inside:avoid}}</style></head><body><main class="paper"><nav class="no-print"><a href="'''+base+'/claim.pdf">تنزيل PDF لإرساله للعميل</a><a href="'+base+'#claim-details">العودة إلى المستند</a></nav><h1>مطالبة مالية تفصيلية</h1><p class="claim-ref">مرجع المطالبة: '+esc(document['id'])+' · نسخة التفصيل: '+esc(detail['id'])+'</p><dl class="claim-meta">'+metadata+'</dl>'+claim_summary(document, detail)+'<p class="hint">مطالبة مالية وليست فاتورة ضريبية أو إثبات سداد.</p></main></body></html>'
