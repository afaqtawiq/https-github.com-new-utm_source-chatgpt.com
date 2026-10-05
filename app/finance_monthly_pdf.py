"""Local-only paginated Arabic reports, with explicit customer/internal projections."""
from io import BytesIO
import re
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from app import finance_claim_pdf as common
from app import finance_monthly_view as view


class Report:
    def __init__(self, title, subtitle):
        common._fonts()
        self.stream = BytesIO()
        self.pdf = canvas.Canvas(self.stream, pagesize=A4, pageCompression=1, invariant=1)
        self.pdf.setTitle(title)
        self.pdf.setAuthor('')
        self.pdf.setCreator('Local financial report')
        self.pdf.setSubject(subtitle)
        self.title, self.subtitle, self.page = title, subtitle, 0
        self.left, self.right = 42, A4[0]-42
        self.header()

    def draw(self, text, y, *, size=10, bold=False, color=None):
        self.pdf.setFont(common._BOLD if bold else common._FONT,size)
        self.pdf.setFillColor(color or common._INK)
        # Direction markers are application-owned and added after input cleaning.
        # Keep ISO dates, decimal numbers and Latin references in their original order.
        text=re.sub(r'[+-]?[A-Za-z0-9#][A-Za-z0-9._/#-]*',lambda match:'\u202a'+match.group(0)+'\u202c',text)
        self.pdf.drawRightString(self.right,y,common._visual(text))

    def header(self):
        self.page += 1
        self.y = A4[1]-50
        for text,size in ((self.title,19),(self.subtitle,10)):
            for line in common._wrap(common._text(text,1000),self.right-self.left,common._BOLD,size):
                self.draw(line,self.y,size=size,bold=True)
                self.y -= size+9
        self.pdf.setStrokeColor(common._ACCENT)
        self.pdf.line(self.left,self.y,self.right,self.y)
        self.y -= 26

    def footer(self):
        self.draw('صفحة '+str(self.page),28,size=9,color=common._MUTED)

    def ensure(self,height):
        if self.y-height < 55:
            self.footer(); self.pdf.showPage(); self.header()

    def line(self,text,*,bold=False,size=10,gap=5):
        for line in common._wrap(common._text(text,2000),self.right-self.left,common._BOLD if bold else common._FONT,size):
            self.ensure(size+7)
            self.draw(line,self.y,size=size,bold=bold)
            self.y -= size+7
        self.y -= gap

    def rule(self):
        self.ensure(20)
        self.pdf.setStrokeColor(common._BORDER)
        self.pdf.line(self.left,self.y,self.right,self.y)
        self.y -= 20

    def finish(self):
        self.footer(); self.pdf.save()
        return self.stream.getvalue()


def render_statement(report):
    # Only these explicit fields are rendered. No dictionary iteration over data.
    r = Report('كشف حساب مفصل',str(report['owner_name'])+' | '+str(report['counterparty_name'])+' | '+report['start']+' - '+report['end'])
    r.line('العميل: '+str(report['counterparty_name']),bold=True,size=12)
    r.line('الفترة: '+report['start']+' إلى '+report['end']+' | العملة: '+report['currency'])
    for key,label in (('opening','الرصيد قبل بداية الفترة'),('claims','مطالبات الفترة'),('receipts','القبض المسجل'),('adjustments','التسويات غير النقدية'),('opening_movements','أرصدة افتتاحية خلال الفترة'),('reversals','صافي القيود العكسية'),('closing','الرصيد في نهاية الفترة')):
        r.line(label+': '+report[key+'_display']+' '+report['currency'],bold=key in ('opening','closing'))
    r.rule()
    r.line('حركات الفترة',bold=True,size=13)
    if not report['movements']:
        r.line('لا توجد حركات خلال الفترة')
    for item in report['movements']:
        r.ensure(180)
        title = ('عكس ' if item['phase']=='reversal' else '')+view.LABELS[item['kind']]
        r.line(item['effective_date']+' | '+title+' #'+str(item['document_id']),bold=True)
        r.line('تاريخ المستند: '+str(item['document_date'])+' | الفاتورة: '+str(item.get('invoice_ref') or 'غير موثق')+' | البيان: '+str(item.get('customs_ref') or 'غير موثق'))
        r.line('مدين: '+item['debit_display']+' | دائن: '+item['credit_display']+' | الرصيد الجاري: '+item['running_display']+' '+report['currency'],bold=True)
        if item['kind']=='claim':
            d = item.get('claim_detail')
            if d:
                r.line('قيمة البضاعة الأصلية: '+str(d['goods_amount'])+' '+str(d['goods_currency'])+' | سعر التحويل: '+str(d['exchange_rate']))
                r.line('قيمة البضاعة المحولة: '+str(d['goods_value_display'])+' '+report['currency']+' | السجل: '+str(d['registry_display'])+' | الضريبة: '+str(d['tax_display']))
                r.line('نسخة التفصيل: '+str(d['revision']),size=9)
            else:
                r.line('تفصيل قيمة البضاعة وعملتها وسعر التحويل والسجل والضريبة غير موثق',size=9)
        r.rule()
    r.line('قيمة البضاعة للمعلومية ولا تضاف إلى إجمالي المطالبات. الأرصدة الافتتاحية أرصدة سابقة وليست مطالبات جديدة.',size=9)
    r.line('حسب الحركات المثبتة حاليًا. يؤرخ العكس بيوم تسجيله بتوقيت الرياض. الكشف ليس فاتورة ضريبية ولا تأكيدًا للسداد خارج القيود المسجلة.',size=9)
    return r.finish()


def render_closing(report):
    r=Report('مسودة إقفال الشهر - DRAFT',str(report['owner_name'])+' | '+report['month'])
    r.line('داخلي للمراجعة فقط. لا يمثل اعتماد أرباح أو توزيعًا أو إثبات دفع.',bold=True)
    r.line('قيمة البضاعة ليست إيرادًا. صافي الذمم ليس ربحًا. احتياطي الضريبة منفصل عن الربح.',size=9)
    r.line('حالة الإعداد: '+('مكتمل كاقتراح للمراجعة' if report['ready_for_distribution'] else 'معلق حتى استكمال المدخلات'),bold=True)
    for blocker in report['blockers']:r.line('- '+blocker,size=9)
    for bucket in report['currencies']:
        r.rule();r.line('عملة التقرير: '+bucket['currency'],bold=True,size=13)
        for key,label in view.CLOSING_AMOUNTS+(('shared_profit_minor','صافي شواهد بعد التكاليف'),('agency_only_profit_minor','صافي نشاط الوكالة الخاص، شامل سابر'),('profit_minor','صافي الربح المحسوب'),('agency_share_minor','حصة الوكالة المقترحة'),('partner_share_minor','حصة شريك شواهد المقترحة')):
            r.line(label+': '+view._amount(bucket.get(key),bucket['currency']))
    r.rule();r.line('مطابقة مستندات الشهر',bold=True,size=13)
    for d in report['documents']:
        r.ensure(75)
        r.line('#'+str(d['document_id'])+' | '+str(d['document_date'])+' | '+d['counterparty_name'],bold=True)
        r.line(view.v.KINDS[d['kind']]+' | '+view.v.STATUSES[d['status']]+' | '+(view._amount(d['amount_minor'],d['currency']) if d['currency'] else 'عملة غير مكتملة'))
        m=d['mapping'] or {}
        r.line('نسخة التصنيف: '+str(d['mapping_revision'] or 'غير موثق')+' | أساس الاحتساب: '+str(m.get('basis_status') or 'غير موثق'))
        for key,label in view.CLOSING_AMOUNTS:
            r.line(label+': '+(view._amount(m.get(key),d['currency']) if d['currency'] else 'غير مكتمل'),size=9)
        r.rule()
    r.line('شواهد: 50% للوكالة و50% للشريك بعد المصروفات الفعلية. هامش سابر بالكامل للوكالة. وحدة التقريب المتبقية للشريك في الاقتراح فقط.',size=9)
    r.line('أي أساس غير محسوم أو تكلفة منتظرة يمنع اقتراح التوزيع. لا تطبق قاعدة ترانزيت أو نسبة مدير غير محددة.',size=9)
    return r.finish()
