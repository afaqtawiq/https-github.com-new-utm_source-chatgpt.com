"""Escaped, self-contained Arabic views for the operational finance subledger.

No database writes, remote assets, JavaScript, tax calculations or money movement.
The route layer owns validation and authorization; these views also hide actions
that the signed-in role cannot perform.
"""
from datetime import date
from html import escape
import json
from urllib.parse import quote, urlencode
from uuid import uuid4

KINDS = {
    'claim': 'مطالبة مالية',
    'opening_receivable': 'رصيد افتتاحي مدين',
    'opening_payable': 'رصيد افتتاحي دائن (دين على صاحب الحساب)',
    'payable': 'مستحق لجهة',
    'expense': 'مصروف',
    'receipt': 'إثبات قبض',
    'payment': 'إثبات دفع',
    'receivable_adjustment': 'تسوية غير نقدية للذمم المدينة',
    'payable_adjustment': 'تسوية غير نقدية للذمم الدائنة',
}
OPENING_KINDS = ('opening_receivable', 'opening_payable')
OPENING_NOTICE = 'رصيد تاريخي صافٍ؛ ليس إيرادًا أو مصروفًا جديدًا، ولا إثبات قبض أو دفع'
STATUSES = {
    'draft': 'مسودة', 'reviewed': 'تمت المراجعة', 'posted': 'مرحّل',
    'reversed': 'معكوس', 'reversal': 'قيد عكسي', 'void': 'ملغى دون حذف', 'voided': 'ملغى دون حذف', 'inactive': 'غير مفعّلة',
}
CURRENCIES = [(c, c) for c in ('SAR','AED','QAR','USD','EUR','GBP','OMR','BHD','KWD','JPY')]
SIDES = {'receivable': 'الذمم المدينة', 'payable': 'الذمم الدائنة'}
BASES = {'unknown': 'غير محدد', 'gross': 'إجمالي حسب المصدر', 'net': 'صافي حسب المصدر'}
ROLE_NAMES = {'admin': 'مدير النظام', 'finance': 'فريق المالية'}

STYLE = '''<style>
:root{--navy:#081621;--panel:#102737;--panel2:#0d202e;--line:#29414f;--gold:#e7b64b;--gold2:#ffdc8a;--text:#f3f7fa;--muted:#adbeca;--green:#79ddb4;--red:#ffb6b8;--blue:#a9cefa;color-scheme:dark}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(ellipse at 95% 0,#19394a 0,transparent 46%),#081621;color:var(--text);font-family:Tahoma,"Segoe UI",Arial,sans-serif;line-height:1.8;font-size:14px}a{color:var(--gold2);text-underline-offset:4px}button,input,select,textarea{font:inherit}a,button,input,select,textarea,summary{outline-offset:4px}a:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid var(--gold2)}button{cursor:pointer}.shell{max-width:1480px;margin:auto;padding:24px 36px 36px}.skip{position:fixed;top:-100px;right:20px;z-index:100;background:var(--gold);color:#07131f;padding:10px}.skip:focus{top:10px}.topbar{display:flex;justify-content:space-between;align-items:center;gap:20px;padding-bottom:21px;border-bottom:1px solid var(--line)}.brand{display:flex;gap:13px;align-items:center;text-decoration:none;color:var(--text)}.brandmark{height:48px;width:48px;border-radius:15px;display:grid;place-items:center;background:linear-gradient(140deg,var(--gold2),var(--gold));color:var(--navy);font-weight:900;font-size:21px}.brand-title{font-weight:800;font-size:18px}.eyebrow{color:var(--gold2);font-size:10px;letter-spacing:2px;font-weight:700}.account{font-size:12px;text-align:left;color:var(--muted)}.account strong{color:var(--text);font-weight:500}.nav{display:flex;gap:7px;overflow-x:auto;padding:16px 0 21px;white-space:nowrap}.nav a{color:var(--muted);text-decoration:none;padding:8px 13px;border-radius:9px;font-size:13px}.nav a:hover{background:#193347;color:white}.nav a[aria-current]{background:#27372e;color:var(--gold2);box-shadow:inset 0 0 0 1px #63552f}.nav .nav-back{margin-inline-start:auto}.hero{display:flex;justify-content:space-between;gap:24px;align-items:center;padding:25px 29px 27px;border:1px solid #566047;border-radius:19px;background:linear-gradient(115deg,#122b3a,#132b32);margin-bottom:20px}.hero h1{font-size:clamp(25px,3.1vw,36px);line-height:1.45;margin:7px 0}.hero p{max-width:720px;margin:4px 0;color:var(--muted)}.hero .eyebrow{font-size:11px}.hero-art{flex-shrink:0;width:100px;height:100px;border:1px solid #796b43;transform:rotate(-7deg);border-radius:24px;display:grid;place-content:center;background:#233b3d;color:var(--gold2);font-size:42px;font-weight:400}.hero-art span{transform:rotate(7deg)}h1,h2,h3,p{overflow-wrap:anywhere}h2{font-size:19px;line-height:1.5;margin:0 0 5px}h3{font-size:15px;margin:0 0 6px}.muted,.hint{color:var(--muted)}.hint{font-size:12px;display:block;margin:5px 0 0;line-height:1.7}.small{font-size:12px}.quiet{color:var(--muted);font-size:12px}.notice{padding:13px 17px;border:1px solid #526047;border-inline-start:3px solid var(--gold);border-radius:11px;background:#202f2c;margin:17px 0;color:#f5e6be;font-size:13px}.notice strong{color:var(--gold2)}.notice.danger{background:#35272b;border-color:#78464a;color:#ffd7d8}.notice.neutral{background:#102939;border-color:#3b6177;color:#c8dfed}.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px;margin:19px 0}.stat{padding:18px 20px;border:1px solid var(--line);border-radius:14px;background:linear-gradient(130deg,#112b3c,#10232f)}.stat-label{color:var(--muted);font-size:12px}.stat b{font-size:29px;color:var(--gold2);display:block;font-variant-numeric:tabular-nums;line-height:1.5}.stat small{color:var(--muted);font-size:11px}.workspace{display:grid;grid-template-columns:minmax(0,1fr) 310px;gap:20px;align-items:start}.card{background:linear-gradient(125deg,#112938,#0d202e);border:1px solid var(--line);border-radius:16px;padding:21px;margin:0 0 20px;min-width:0}.section-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:15px}.section-head p{margin:3px 0 0;font-size:12px;color:var(--muted)}.tag{display:inline-flex;gap:5px;align-items:center;padding:3px 9px;border:1px solid #496071;background:#1b3346;color:#c4d8e8;border-radius:7px;font-size:11px;white-space:nowrap}.tag.posted,.tag.reviewed{border-color:#386a58;background:#163e35;color:#a7efcf}.tag.draft{border-color:#756032;background:#44391f;color:#ffda87}.tag.reversed,.tag.reversal{border-color:#754850;background:#3c2a32;color:#ffc0c8}.actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-top:15px}.btn{display:inline-flex;align-items:center;justify-content:center;min-height:43px;padding:9px 16px;border:1px solid transparent;border-radius:9px;background:var(--gold);color:#14212a;text-decoration:none;font-weight:700;font-size:13px}.btn:hover{background:var(--gold2)}.btn.secondary{background:#1a3649;color:#e5eef4;border-color:#36566a}.btn.secondary:hover{background:#25475b}.btn.danger{background:#5a3038;color:#ffe3e7;border-color:#88505d}.btn.small{font-size:12px;padding:6px 11px;min-height:34px}.btn:disabled{opacity:.55;cursor:not-allowed}.scroll{max-width:100%;overflow:auto;scrollbar-width:thin;border-radius:10px;border:1px solid var(--line)}table{width:100%;border-collapse:collapse;min-width:720px;font-size:12px}caption{text-align:right;padding:11px 14px;color:var(--muted);font-size:12px;background:#102735}th,td{padding:12px 14px;border-bottom:1px solid #263e4c;text-align:right;vertical-align:middle}th{font-size:11px;color:#bacbd7;background:#0a1b27;font-weight:500;white-space:nowrap}tbody tr:last-child td{border-bottom:0}tbody tr:hover{background:#163345}td strong{font-weight:700;font-size:13px}.num{font-variant-numeric:tabular-nums;white-space:nowrap;direction:ltr;unicode-bidi:isolate;display:inline-block}.amount{color:var(--gold2);font-weight:700}.cell-sub{display:block;font-size:10px;color:var(--muted);margin-top:3px}.empty{padding:31px 18px;text-align:center;color:var(--muted);border:1px dashed #3d5565;border-radius:11px}.empty strong{display:block;color:var(--text);font-size:15px;margin-bottom:7px}.empty p{margin:0 auto;max-width:460px;font-size:12px}.formgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 16px}.formgrid.three{grid-template-columns:repeat(3,minmax(0,1fr))}.span-all{grid-column:1/-1}.field{display:flex;flex-direction:column;gap:5px;font-size:12px;color:#dce7ed;min-width:0}.field label{font-weight:600}input,select,textarea{width:100%;background:#091d2a;border:1px solid #3e5a6c;border-radius:8px;padding:10px 12px;color:var(--text);font-size:13px;min-height:43px}input::placeholder,textarea::placeholder{color:#8299aa}input:focus,select:focus,textarea:focus{border-color:var(--gold);outline:2px solid #b58b3544}textarea{min-height:87px;resize:vertical}input[type=checkbox]{width:18px;height:18px;min-height:0;accent-color:var(--gold);flex-shrink:0}input[type=date]{direction:ltr;text-align:right}fieldset{border:0;margin:0 0 20px;padding:0;min-width:0}legend{font-size:13px;color:var(--gold2);padding:0 0 11px;font-weight:700}.check{display:flex;gap:9px;align-items:flex-start;margin:13px 0;font-size:12px;color:#d5e1e8}.check input{margin-top:4px}.divider{height:1px;background:var(--line);margin:19px 0}.side-heading{display:flex;gap:9px;align-items:center;margin-bottom:12px}.dot{width:7px;height:7px;border-radius:50%;background:var(--gold)}.checklist{padding:0;margin:0;list-style:none}.checklist li{padding:12px 0;border-bottom:1px solid var(--line);font-size:12px;color:var(--muted)}.checklist li:last-child{border:0;padding-bottom:0}.checklist strong{display:block;color:var(--text);font-size:13px;font-weight:500;margin-bottom:4px}.step{display:inline-grid;width:23px;height:23px;place-items:center;border-radius:7px;background:#243f4f;color:var(--gold2);font-size:11px;margin-inline-end:5px}.audit{list-style:none;margin:0;padding:0}.audit li{border-inline-start:1px solid #51604a;padding:0 15px 18px;margin-inline-start:4px;position:relative}.audit li:before{content:"";position:absolute;inset-inline-start:-4px;top:7px;width:7px;height:7px;border-radius:50%;background:var(--gold)}.audit li:last-child{padding-bottom:0}.audit .audit-head{font-size:12px;color:#f2f6f8}.audit p{font-size:11px;color:var(--muted);margin:3px 0;overflow-wrap:anywhere}.audit time{font-size:10px;color:#a5bccb;direction:ltr;display:inline-block}.detail-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.detail-grid dt{color:var(--muted);font-size:11px;margin:0 0 5px}.detail-grid dd{margin:0;font-size:14px;overflow-wrap:anywhere}.detail-grid .wide{grid-column:1/-1}dl{margin:0}.source{background:#0a1b28;border:1px solid var(--line);border-radius:9px;padding:14px;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;color:#cadce8;font-family:inherit;font-size:12px;max-height:350px;overflow:auto;direction:auto}.detail-money{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:19px 0}.money-tile{border:1px solid #334b5a;background:#0c2231;border-radius:11px;padding:15px}.money-tile small{display:block;color:var(--muted);font-size:11px}.money-tile strong{display:block;font-size:22px;font-weight:600;color:var(--gold2);margin-top:5px}.process{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.process span{font-size:12px;border:1px solid var(--line);border-radius:8px;padding:6px 12px;color:var(--muted)}.process .current{color:var(--gold2);border-color:#8b743e;background:#423921}details{margin-top:12px}summary{cursor:pointer;color:var(--gold2);font-size:13px;padding:5px 0}.legal{color:var(--muted);font-size:11px;margin:18px 0 0;padding-top:16px;border-top:1px solid var(--line)}.footer{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;color:#a1b7c6;font-size:11px;padding:8px 0}.print-only{display:none}.role-note{font-size:11px;padding:8px 10px;background:#1a3445;border-radius:8px;color:#bdd0dc}.noncash{color:#c4b8f8}.stack>*:last-child{margin-bottom:0}
@media(max-width:1120px){.workspace{grid-template-columns:minmax(0,1fr) 270px}.shell{padding:20px}.formgrid.three{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:900px){.workspace{grid-template-columns:1fr}.sidebar{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.sidebar>.card{margin-bottom:0}.stats{gap:9px}.stat{padding:14px}.hero-art{width:76px;height:76px;font-size:33px}.detail-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:580px){.shell{padding:15px}.topbar{align-items:flex-start;gap:10px}.brand-title{font-size:15px}.brandmark{width:41px;height:41px;font-size:19px}.account{font-size:10px;max-width:125px;overflow-wrap:anywhere}.eyebrow{font-size:8px;letter-spacing:1px}.nav{margin:0 -15px;padding:13px 15px 18px}.nav a{font-size:12px;padding:7px 10px}.hero{padding:19px;gap:10px}.hero-art{display:none}.hero p{font-size:12px}.hero h1{font-size:26px}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.stat b{font-size:26px}.card{padding:17px;border-radius:13px}.section-head{align-items:flex-start;flex-wrap:wrap}.formgrid,.formgrid.three,.detail-money,.sidebar{grid-template-columns:1fr}.detail-grid{gap:15px;grid-template-columns:1fr 1fr}.detail-money{gap:8px}.money-tile{display:flex;align-items:center;justify-content:space-between;gap:10px}.money-tile strong{font-size:19px;margin:0}.btn{min-height:44px}.actions>.btn{flex-grow:1}h2{font-size:18px}.footer{font-size:10px}.notice{font-size:12px}}@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}@media print{body{background:white;color:black;font-size:11px}.shell{max-width:none;padding:0}.topbar,.nav,.no-print,.sidebar,.footer,.hero-art{display:none}.hero,.card,.stat,.money-tile{background:white;border-color:#bbb;box-shadow:none;color:black;break-inside:avoid}.hero{padding:12px}.hero h1{font-size:24px}.workspace{display:block}.muted,.quiet,.hint,.legal,.hero p,dt,th,.cell-sub{color:#444!important}.num,.amount,.money-tile strong,.tag{color:black!important}.scroll{overflow:visible;border-color:#aaa}table{min-width:0;font-size:10px}th,td{padding:7px;border-color:#bbb}th{background:#eee}.tag{background:#eee}.print-only{display:block}.eyebrow{color:#555}.notice{background:white;color:#444;border-color:#aaa}a{color:black}.section-head{margin-bottom:8px}}
.finance-summary{border:1px solid #69734b;border-radius:18px;padding:23px;margin:0 0 20px;background:linear-gradient(120deg,#152f39,#102431)}.finance-summary>.section-head{margin-bottom:10px}.finance-summary h2{font-size:23px}.summary-scope{margin:0 0 18px;color:var(--muted);font-size:12px}.summary-group{padding-top:18px;border-top:1px solid #3b5359;margin-top:18px;min-width:0}.summary-group-head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:14px}.summary-group-head h3{font-size:17px}.summary-currency{flex-shrink:0;color:var(--gold2);border:1px solid #686044;border-radius:8px;padding:4px 10px;font-size:12px}.summary-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.summary-card{padding:19px;border:1px solid #405967;border-radius:13px;background:#0c2231;min-width:0}.summary-card.net{background:#233831;border-color:#667847}.summary-card dt{font-size:13px;color:#d8e4ec;font-weight:700}.summary-card dd{margin:8px 0 0}.summary-value{display:block;color:var(--gold2);font-size:clamp(25px,2.8vw,35px);font-weight:700;line-height:1.5}.summary-value .num{white-space:normal;overflow-wrap:anywhere}.summary-card p{margin:10px 0 0;font-size:11px;color:var(--muted)}.summary-warning{margin-bottom:0}.summary-limit{margin:18px 0 0;font-size:12px;color:#d6dfd4}
@media(max-width:700px){.finance-summary{padding:18px}.summary-cards{grid-template-columns:1fr}.summary-group-head{flex-wrap:wrap}.summary-card{padding:16px}.summary-value{font-size:29px}}@media print{.finance-summary,.summary-card,.summary-card.net{background:white;color:black;border-color:#aaa;break-inside:avoid}.summary-currency,.summary-card dt,.summary-card p,.summary-limit,.summary-scope{color:#444}.summary-value{color:black}}
</style>'''


def esc(value):
    return escape('' if value is None else str(value), quote=True)


def _id(value):
    return quote('' if value is None else str(value), safe='')


def _badge(status):
    css = status if status in STATUSES else 'inactive'
    return '<span class="tag '+css+'">'+esc(STATUSES.get(status, status or 'غير محدد'))+'</span>'


def _currency(value):
    return esc(value) if value else 'عملة غير محددة'


def _number(value, missing='غير محدد'):
    return '<bdi class="num">'+esc(missing if value is None or value == '' else value)+'</bdi>'


def _can_edit(session):
    return session.get("role") in ("admin", "finance") and bool(session.get("can_edit_finance", True))


def _can_approve(session):
    return session.get("role") == "admin" and bool(session.get("can_approve_finance", True))


def _tokens(session):
    return '<input type="hidden" name="csrf" value="'+esc(session.get('csrf', ''))+'"><input type="hidden" name="idempotency_key" value="'+str(uuid4())+'">'


def _field(name, label, *, value='', kind='text', required=False, hint='', placeholder='', attrs=''):
    field_id = 'f-'+name+'-'+uuid4().hex[:8]
    help_id = field_id+'-help'
    attributes = ' id="'+field_id+'" name="'+name+'"'+(' required' if required else '')
    if hint:
        attributes += ' aria-describedby="'+help_id+'"'
    attributes += ' '+attrs if attrs else ''
    control = ('<textarea'+attributes+' placeholder="'+esc(placeholder)+'">'+esc(value)+'</textarea>' if kind == 'textarea' else
               '<input type="'+kind+'"'+attributes+' value="'+esc(value)+'" placeholder="'+esc(placeholder)+'">')
    return '<div class="field"><label for="'+field_id+'">'+esc(label)+(' <span aria-label="مطلوب">*</span>' if required else '')+'</label>'+control+('<small class="hint" id="'+help_id+'">'+esc(hint)+'</small>' if hint else '')+'</div>'


def _select(name, label, choices, *, required=False, blank='اختر', value='', hint=''):
    field_id = 'f-'+name+'-'+uuid4().hex[:8]
    options = '<option value="">'+esc(blank)+'</option>' if blank is not None else ''
    options += ''.join('<option value="'+esc(key)+'"'+(' selected' if str(key) == str(value) else '')+'>'+esc(text)+'</option>' for key, text in choices)
    return '<div class="field"><label for="'+field_id+'">'+esc(label)+(' <span aria-label="مطلوب">*</span>' if required else '')+'</label><select id="'+field_id+'" name="'+name+'"'+(' required' if required else '')+(' aria-describedby="'+field_id+'-help"' if hint else '')+'>'+options+'</select>'+('<small class="hint" id="'+field_id+'-help">'+esc(hint)+'</small>' if hint else '')+'</div>'


def _party_options(parties, kind, confirmed_only=False):
    return [(p.get('id'), p.get('name', '')+(' · غير مؤكدة' if not p.get('confirmed') else ''))
            for p in parties if p.get('kind') == kind and (not confirmed_only or p.get('confirmed'))]


def _table(headers, body, caption):
    return '<div class="scroll" role="region" aria-label="'+esc(caption)+'" tabindex="0"><table><caption>'+esc(caption)+'</caption><thead><tr>'+''.join('<th scope="col">'+esc(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+body+'</tbody></table></div>'


def _empty(title, detail):
    return '<div class="empty"><strong>'+esc(title)+'</strong><p>'+esc(detail)+'</p></div>'


def _page(session, title, body):
    role = ROLE_NAMES.get(session.get('role'), 'عرض فقط')
    user_name = session.get('name') or session.get('email') or 'المستخدم'
    return '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+' | آفاق طويق</title>'+STYLE+'</head><body><a href="#main" class="skip">تجاوز إلى المحتوى</a><div class="shell"><header class="topbar"><a href="/dashboard" class="brand" aria-label="آفاق طويق، الرئيسية"><span class="brandmark" aria-hidden="true">آط</span><span><span class="brand-title">آفاق طويق</span><br><span class="eyebrow" lang="en" dir="ltr">AFAQ TUWAIQ · OPERATIONS</span></span></a><div class="account"><strong>'+esc(user_name)+'</strong><br>'+esc(role)+' · مساحة المالية</div></header><nav class="nav" aria-label="التنقل الرئيسي"><a href="/finance" aria-current="page">المحاسبة والمالية</a><a href="/shipments">الشحنات</a><a href="/accounts">العملاء</a><a href="/activity">سجل النشاط</a><a class="nav-back" href="/dashboard">الرئيسية ←</a></nav><main id="main">'+body+'</main><footer class="footer"><span>آفاق طويق · السجل المالي التشغيلي</span><span>الأرصدة حسب الجهة والعملة · كل تغيير قابل للتتبع</span></footer></div></body></html>'


def _hero(title, description, eyebrow='مساحة العمل المالية', art='≡'):
    return '<section class="hero"><div><div class="eyebrow">'+esc(eyebrow)+'</div><h1>'+esc(title)+'</h1><p>'+esc(description)+'</p></div><div class="hero-art" aria-hidden="true"><span>'+esc(art)+'</span></div></section>'


AUDIT_LABELS = {'party_confirmed':'تأكيد هوية مالية','owner_display_name_changed':'تصحيح اسم عرض صاحب الحساب','document_created':'تسجيل مسودة','document_reviewed':'مراجعة المستند','document_posted':'اعتماد الترحيل','document_reversed':'عكس المستند','document_voided':'إلغاء المسودة مع حفظ الدليل','allocation_created':'تخصيص تسوية','allocation_reversed':'عكس التخصيص','inactive_rule_created':'حفظ قاعدة غير مفعلة'}

def _audit(items):
    if not items:
        return '<p class="quiet">لا توجد أحداث مسجلة للعرض حتى الآن</p>'
    return '<ol class="audit">'+''.join('<li><div class="audit-head">'+esc(item.get('actor_name') or 'مستخدم النظام')+' · '+esc(AUDIT_LABELS.get(item.get('action'), item.get('action', '')))+'</div><p>'+esc(item.get('detail', ''))+'</p><time>'+esc(item.get('created_at', ''))+'</time></li>' for item in items)+'</ol>'


def _kind_cell(document):
    kind = document.get('kind')
    body = esc(KINDS.get(kind, kind or ''))
    if kind in OPENING_KINDS:
        body += '<span class="cell-sub noncash">'+esc(OPENING_NOTICE)+'</span>'
        if document.get('opening_cutoff'):
            body += '<span class="cell-sub">تاريخ القطع: '+esc(document['opening_cutoff'])+'</span>'
    elif kind in ('receivable_adjustment', 'payable_adjustment'):
        body += '<span class="cell-sub noncash">تسوية غير نقدية</span>'
    return '<td>'+body+'</td>'


def _opening_form_details():
    return (
        '<details><summary>تفاصيل الرصيد الافتتاحي المدين أو الدائن فقط</summary>'
        '<p class="hint">املأ هذه البيانات عند اختيار رصيد افتتاحي مدين أو دائن فقط. تحفظ مع دليل المصدر دون تعديل لاحق؛ '
        'وأي تصحيح يتطلب مستندًا بديلًا موثقًا.</p><div class="formgrid">'
        +_field('opening_cutoff', 'تاريخ قطع الرصيد الافتتاحي', kind='date',
                hint='مطلوب للرصيد الافتتاحي؛ يجب أن يطابق تاريخ المستند')
        +_field('opening_confirmation_ref', 'مرجع اعتماد صافي الرصيد الافتتاحي', kind='textarea',
                hint='مرجع موافقة صريحة من المستخدم أو صاحب الحساب على صافي الرصيد حتى تاريخ القطع؛ اعتماد الرصيد لا يثبت التحقق المستقل من المصدر')
        +'</div><ul class="checklist">'
        '<li>اختر نوع المصدر «ملخص تجميعي» (summary)، وأساس المبلغ «صافي حسب المصدر» (net).</li>'
        '<li>اجعل تاريخ المستند مساويًا لتاريخ القطع، واترك روابط الشحنة والفاتورة والبيان الجمركي فارغة.</li>'
        '<li>احتفظ بنص المبلغ الأصلي ودقته العشرية وإشارته كما وردت؛ إقرار التقريب مستقل أثناء المراجعة.</li>'
        '<li>للرصيد الافتتاحي الدائن، أدخل مبلغ الدين على صاحب الحساب كقيمة رقمية موجبة، '
        'حتى لو كان نص المبلغ الأصلي سالبًا؛ يبقى النص الأصلي بإشارته محفوظًا دون تغيير.</li>'
        '<li>'+esc(OPENING_NOTICE)+'. يتضمن صافي المطالبات أو الديون والتسويات التاريخية حتى تاريخ القطع، '
        'ولا تعاد إضافة الحركات التاريخية المشمولة فيه.</li>'
        '<li>إذا كانت القيمة من صيغة خارجية مخزنة، يبقى هذا الوصف محفوظًا. يلزم مرجع اعتماد صريح لصافي الرصيد '
        'من المستخدم أو صاحب الحساب؛ ولا يُسمى هذا الاعتماد تحققًا مستقلًا.</li>'
        '</ul></details>'
    )


def _document_rows(documents):
    return ''.join('<tr><td><a href="/finance/documents/'+_id(d.get('id'))+'"><strong>'+esc(d.get('source_ref') or '#'+str(d.get('id', '')))+'</strong></a><span class="cell-sub">'+esc(d.get('document_date') or 'تاريخ غير محدد')+'</span></td><td>'+esc(d.get('owner_name', ''))+'<span class="cell-sub">'+esc(d.get('counterparty_name', ''))+'</span></td>'+_kind_cell(d)+'<td><span class="amount">'+_number(d.get('amount_display'))+'</span><span class="cell-sub">'+_currency(d.get('currency'))+'</span></td><td>'+_badge(d.get('status'))+'</td><td><a class="btn secondary small" href="/finance/documents/'+_id(d.get('id'))+'">تفاصيل <span class="small" aria-hidden="true">↗</span></a></td></tr>' for d in documents)


def _document_form(session, parties):
    return '<section class="card no-print" id="new-document"><div class="section-head"><div><h2>تسجيل مستند مالي</h2><p>ابدأ بالمصدر. يحفظ المستند كمسودة حتى المراجعة والترحيل</p></div><span class="tag draft">مسودة جديدة</span></div><form method="post" action="/finance/documents">'+_tokens(session)+'<fieldset><legend>01 · أطراف العملية</legend><div class="formgrid">'+_select('owner_id','صاحب الحساب',_party_options(parties,'owner'),required=True)+_select('counterparty_id','الجهة المقابلة',_party_options(parties,'counterparty'),required=True)+'</div></fieldset><fieldset><legend>02 · بيانات المستند والمبلغ</legend><div class="formgrid three">'+_select('kind','نوع المستند',KINDS.items(),required=True)+_field('document_date','تاريخ المستند',kind='date',hint='يمكن تركه غير محدد في المسودة؛ مطلوب قبل الترحيل')+_select('currency','العملة',CURRENCIES,blank='غير محددة في المصدر',hint='لا توجد عملة افتراضية أو تحويلات بين العملات')+_field('amount','المبلغ الرقمي',required=True,placeholder='0.00',hint='رقم عشري مطابق للمصدر، حتى 8 منازل؛ دون فواصل آلاف. للرصيد الافتتاحي الدائن فقط، أدخل مقدار الدين موجبًا مع حفظ إشارة المصدر في نصه الأصلي',attrs='inputmode="decimal" dir="ltr" autocomplete="off"')+_field('source_amount_raw','نص المبلغ الأصلي',required=True,hint='انسخ المبلغ كما هو، بما فيه الإشارة والعملة أو الفواصل إن وجدت')+_select('amount_basis','أساس المبلغ',BASES.items(),value='unknown',blank=None,hint='لا يفترض النظام ضريبة أو صافي ربح')+'</div></fieldset><fieldset><legend>03 · دليل المصدر والربط</legend><div class="formgrid">'+_field('economic_ref','مرجع الحركة الاقتصادية',required=True,placeholder='رقم الفاتورة أو سند القبض أو الدفع',hint='مرجع فريد للحدث المالي، ولو ظهر في أكثر من مصدر')+_select('source_role','نوع المصدر',[('detail','حركة تفصيلية'),('summary','ملخص تجميعي')],blank=None,value='detail',hint='الملخص دليل فقط، إلا عند توثيق صافي رصيد افتتاحي معتمد')+_field('source_ref','مرجع المصدر',required=True,placeholder='اسم المستند أو مرجعه')+_field('source_locator','موضع الدليل في المصدر',required=True,placeholder='اسم الملف / رقم الصفحة / رقم السطر',hint='مرجع يمكن الرجوع إليه والتحقق منه؛ لا يُفتح خارجيًا تلقائيًا')+_field('invoice_ref','مرجع الفاتورة',placeholder='اختياري')+_field('customs_ref','رقم البيان الجمركي',placeholder='اختياري')+_field('shipment_id','معرّف الشحنة',kind='number',hint='ربط يدوي بشحنة موجودة، عند التحقق من المعرف',attrs='min="1" step="1"')+_field('notes','ملاحظات المراجعة',kind='textarea',placeholder='أي نقص أو التباس يحتاج مراجعة')+'</div><details><summary>تفاصيل إضافية عن دليل المصدر</summary><div class="formgrid">'+_field('source_date_raw','نص التاريخ في المصدر',hint='انسخ التاريخ كما ورد، حتى إن كان ناقصًا')+_field('source_status_raw','الحالة كما كتبها المصدر',hint='وصف المصدر فقط؛ لا يعد تحققًا من السداد')+_select('source_verification','مستوى التحقق',[('recorded','مسجل من المصدر فقط'),('independently_verified','تم التحقق بدليل مستقل')],blank=None,value='recorded',hint='اختر التحقق المستقل فقط بعد مطابقته بدليل موثق')+_field('verification_ref','مرجع دليل التحقق المستقل',hint='مطلوب عند اختيار التحقق المستقل؛ اذكر المستند أو الصفحة التي طابقتها')+'</div><label class="check"><input type="checkbox" name="source_cached_external" value="1"><span>القيمة من نتيجة صيغة مخزنة تعتمد على ملف خارجي؛ يلزم تحقق مستقل، أو اعتماد صريح لصافي رصيد افتتاحي وفق التفاصيل أدناه.</span></label></details>'+_opening_form_details()+'</fieldset><div class="notice">سجّل كل حدث مالي مرة واحدة. ملخص المصدر دليل فقط، وليس مطالبة إضافية فوق حركاته التفصيلية. الاستثناء رصيد افتتاحي صافي معتمد لا تعاد إضافة حركاته التاريخية المشمولة.</div><div class="notice neutral">إثبات القبض أو الدفع يسجل حدثًا موثقًا. التسويات غير نقدية، والتسجيل لا ينفذ تحويلًا ماليًا.</div><div class="actions"><button class="btn" type="submit">حفظ مسودة المستند</button><span class="quiet">لا يؤثر الحفظ على الأرصدة المرحّلة</span></div></form></section>'


def _party_form(session):
    return '<details class="no-print"><summary>إضافة هوية مالية مؤكدة</summary><form method="post" action="/finance/parties">'+_tokens(session)+'<div class="formgrid">'+_field('name','الاسم المثبت بالمصدر',required=True)+_select('kind','دور الهوية',[('owner','صاحب حساب'),('counterparty','جهة مقابلة')],required=True)+_field('identity_ref','مرجع التحقق من الهوية',required=True,hint='مرجع موثق يميز الجهة عن غيرها')+'</div><label class="check"><input type="checkbox" name="confirmed" value="1" required><span>تحققت من الهوية ومرجعها. هذه الجهة مستقلة عن أي اسم مشابه.</span></label><button class="btn secondary" type="submit">حفظ الهوية المؤكدة</button></form></details>'


def _owner_name_form(session, owner):
    return (
        '<details class="no-print"><summary>تصحيح اسم عرض صاحب الحساب: '+esc(owner.get('name'))+'</summary>'
        '<p class="hint">معرّف صاحب الحساب: '+_number(owner.get('id'))+
        '. يتغير الاسم الظاهر في المالية والكشوف فقط. تبقى الهوية الأصلية ومراجع المصدر والأرصدة '
        'والروابط محفوظة، ويسجل الاسم السابق والجديد وسبب التصحيح.</p>'
        '<form method="post" action="/finance/owners/'+_id(owner.get('id'))+'/display-name">'+_tokens(session)+
        '<input type="hidden" name="expected_revision" value="'+esc(owner.get('name_revision', 0))+'">'
        '<div class="formgrid">'+_field('name','اسم العرض الجديد',value=owner.get('name'),required=True,attrs='maxlength="200"')+
        _field('reason','سبب التصحيح ومرجع الاعتماد',kind='textarea',required=True,attrs='maxlength="1000"')+'</div>'
        '<label class="check"><input type="checkbox" name="confirmation" value="1" required>'
        '<span>أعتمد تصحيح اسم العرض لنفس صاحب الحساب، دون إنشاء هوية جديدة أو نقل أرصدة.</span></label>'
        '<div class="actions"><button class="btn secondary" type="submit">حفظ تصحيح اسم العرض</button>'
        '<button class="btn secondary" type="reset">إلغاء التغييرات</button></div></form></details>'
    )


def _rules_section(session, parties, rules):
    body = '<section class="card" id="rules"><div class="section-head"><div><h2>قواعد النسب والتوزيع</h2><p>تعريفات مبدئية تنتظر توثيق الاتفاق وأساس الاحتساب</p></div><span class="tag">غير مفعّلة</span></div><div class="notice">هذه القواعد مسودات غير نشطة. لا تُحتسب نسب أو أرباح ولا تُنشأ قيود منها.</div>'
    if rules:
        rows = ''.join('<tr><td>'+esc(r.get('owner_name'))+'</td><td>'+esc(r.get('company_scope'))+'</td><td>'+_number(r.get('rate'))+'</td><td>'+esc(r.get('basis'))+'</td><td><span class="tag">مسودة غير مفعّلة</span></td></tr>' for r in rules)
        body += _table(['صاحب الحساب','نطاق الشركة','النسبة المقترحة','أساس مقترح','الحالة'],rows,'القواعد المسجلة للمراجعة فقط')
    else:
        body += _empty('لا توجد نسب مفترضة','تُضاف النسبة من اتفاق موثق وبقرار إداري. لا توجد قيمة افتراضية.')
    if _can_approve(session):
        body += '<details class="no-print"><summary>تسجيل مقترح قاعدة</summary><form method="post" action="/finance/rules">'+_tokens(session)+'<div class="formgrid">'+_select('owner_id','صاحب الحساب للقاعدة',_party_options(parties,'owner'),required=True)+_field('company_scope','نطاق الشركة',required=True)+_field('rate','النسبة المقترحة (%)',required=True,attrs='inputmode="decimal" dir="ltr"')+_field('basis','أساس الاحتساب المقترح',required=True,hint='وصف حر؛ لا تُجرى أي حسابات بناءً عليه')+'</div><div class="actions"><button class="btn secondary" type="submit">حفظ المقترح غير المفعّل</button></div></form></details>'
    return body+'</section>'


def _financial_totals(totals):
    """Render service-supplied posted totals without calculating or netting money."""
    body = (
        '<section class="finance-summary" id="financial-summary" aria-labelledby="financial-summary-title">'
        '<div class="section-head"><div><h2 id="financial-summary-title">ملخص الأرصدة المسجلة</h2>'
        '<p>إجماليات مستقلة لكل صاحب حساب وعملة؛ لا يوجد إجمالي جامع بينها</p></div>'
        '<span class="tag posted">من البيانات المسجلة والمرحّلة فقط</span></div>'
        '<p class="summary-scope">تشمل الإجماليات أثر إثباتات القبض والدفع والتسويات والقيود العكسية المرحّلة، '
        'دون خصم التخصيصات مرة ثانية. المسودات والمستندات قيد المراجعة مستبعدة.</p>'
    )
    cards = (
        ('receivable_display', 'إجمالي الأرصدة المستحقة',
         'رصيد الذمم المدينة المسجل: الموجب مستحق لصاحب الحساب، والسالب رصيد دائن للجهات المقابلة.'),
        ('payable_display', 'إجمالي الديون المسجلة',
         'رصيد الذمم الدائنة المسجل: الموجب دين على صاحب الحساب، والسالب رصيد مدين لصالحه لدى الجهات المقابلة.'),
        ('net_display', 'صافي الرصيد المسجل',
         'الذمم المدينة ناقص الذمم الدائنة؛ الموجب يعني أن رصيد المدينة أعلى من الدائنة، والسالب يعني العكس.'),
    )
    if not totals:
        body += _empty('لا تتوفر إجماليات مرحّلة للعرض',
                       'لا تُفترض أرصدة صفرية عند غياب الإجماليات، ولا يثبت غياب البيانات عدم وجود التزامات فعلية.')
    for index, total in enumerate(totals or []):
        heading_id = 'financial-summary-owner-'+str(index)
        body += (
            '<article class="summary-group" data-owner-id="'+esc(total.get('owner_id'))
            +'" data-currency="'+esc(total.get('currency'))+'" aria-labelledby="'+heading_id+'">'
            '<header class="summary-group-head"><div><h3 id="'+heading_id+'">صاحب الحساب: <bdi>'
            +esc(total.get('owner_name') or 'اسم غير محدد')+'</bdi></h3>'
            '<span class="quiet">معرّف صاحب الحساب: '+_number(total.get('owner_id'))+'</span></div>'
            '<span class="summary-currency">العملة: <bdi>'+_currency(total.get('currency'))+'</bdi></span></header>'
            '<dl class="summary-cards">'
        )
        for field, label, explanation in cards:
            body += (
                '<div class="summary-card'+(' net' if field == 'net_display' else '')+'"><dt>'+label+'</dt>'
                '<dd><span class="summary-value">'+_number(total.get(field))+'</span>'
                '<span class="quiet">'+_currency(total.get('currency'))+' · مسجل ومرحّل فقط</span></dd>'
                '<dd><p>'+explanation+'</p></dd></div>'
            )
        body += '</dl>'
        if total.get('payable_document_count') == 0:
            body += (
                '<div class="notice summary-warning"><strong>لا توجد مستندات ديون مرحّلة مسجلة لهذا الحساب بهذه العملة.</strong> '
                'غياب مستندات الديون، أو ظهور رصيد صفري، لا يثبت عدم وجود التزامات فعلية؛ قد توجد ديون لم تُسجل بعد.</div>'
            )
        body += '</article>'
    return body+(
        '<p class="summary-limit">الصافي فرق حسابي ضمن السجل فقط، ولا يمثل ربحًا أو نقدًا متاحًا أو صورة مالية مكتملة، '
        'ولا ينفذ مقاصة بين الجهات. تبقى الالتزامات غير المسجلة خارج هذه الإجماليات.</p></section>'
    )


def render_dashboard(session, parties, documents, summary, audit, rules, totals=None):
    """Return a complete, escaped HTML document for the finance landing page."""
    parties, documents, summary, audit, rules = (list(x or []) for x in (parties, documents, summary, audit, rules))
    can_write = _can_edit(session)
    body = _hero('المحاسبة والمالية', 'المطالبات والمستحقات والمصروفات وإثباتات القبض والدفع، مرتبطة بمصادرها وتحت مراجعة واضحة.', 'AFAQ TUWAIQ · FINANCE WORKSPACE')
    body += _financial_totals(totals)
    body += '<div class="stats">'+''.join('<div class="stat"><span class="stat-label">'+title+'</span><b>'+str(count)+'</b><small>'+description+'</small></div>' for title,count,description in [
        ('المستندات المعروضة',len(documents),'سجل موثق بالمصدر'),('بانتظار المراجعة',sum(d.get('status')=='draft' for d in documents),'مسودات لا تدخل الأرصدة'),('بانتظار الترحيل',sum(d.get('status')=='reviewed' for d in documents),'تحتاج اعتماد المدير'),('الجهات المسجلة',len(parties),'أصحاب حسابات وجهات مقابلة')])+'</div>'
    body += '<div class="workspace"><div class="stack"><section class="card" id="balances"><div class="section-head"><div><h2>الأرصدة المرحّلة</h2><p>عرض مستقل لكل صاحب حساب وجهة وعملة؛ المدينة والدائنة منفصلتان</p></div><span class="tag">من القيود المرحّلة فقط</span></div>'
    if summary:
        summary_rows = ''.join('<tr><td><strong>'+esc(s.get('owner_name'))+'</strong></td><td>'+esc(s.get('counterparty_name'))+'</td><td>'+_currency(s.get('currency'))+'</td><td class="amount">'+_number(s.get('receivable_display'))+'</td><td>'+_number(s.get('payable_display'))+'</td></tr>' for s in summary)
        body += _table(['صاحب الحساب','الجهة المقابلة','العملة','ذمم مدينة','ذمم دائنة'],summary_rows,'لا تُجمع عملات مختلفة ولا تجري مقاصة تلقائية')
    else:
        body += _empty('لا توجد أرصدة مرحّلة بعد','ابدأ بتوثيق الهويات والمستندات. تظهر الأرصدة بعد المراجعة والاعتماد فقط.')
    body += '</section><section class="card" id="documents"><div class="section-head"><div><h2>سجل المستندات</h2><p>من الدليل الأصلي إلى القيد المرحّل</p></div>'+('<a class="btn small" href="#new-document">+ تسجيل مستند</a>' if can_write else '<span class="tag">عرض فقط</span>')+'</div>'
    body += _table(['المستند / التاريخ','صاحب الحساب / الجهة','النوع','المبلغ / العملة','الحالة','المراجعة'],_document_rows(documents),'المستندات المالية المتاحة للعرض') if documents else _empty('سجل نظيف، جاهز للبدء','لم تُضف مستندات مالية بعد. لا يتم تحويل البيانات القديمة إلى قيود تلقائيًا.')
    body += '</section>'
    if can_write:
        body += _document_form(session, parties)
    body += '<section class="card" id="parties"><div class="section-head"><div><h2>الهويات المالية</h2><p>هوية صريحة لصاحب الحساب والجهة المقابلة قبل الاعتماد</p></div></div>'
    if parties:
        body += _table(['الاسم','الدور','مرجع الهوية','التحقق'],''.join('<tr><td><strong>'+esc(p.get('name'))+'</strong></td><td>'+('صاحب حساب' if p.get('kind')=='owner' else 'جهة مقابلة')+'</td><td>'+esc(p.get('identity_ref'))+'</td><td>'+('<span class="tag posted">مؤكدة</span>' if p.get('confirmed') else '<span class="tag draft">غير مؤكدة</span>')+'</td></tr>' for p in parties),'هويات مستقلة دون دمج تلقائي للأسماء')
    else:
        body += _empty('لم تسجل هويات مالية','يضيف المدير الهوية بعد التحقق من اسم الجهة ومرجعها.')
    if _can_approve(session):
        body += ''.join(_owner_name_form(session,p) for p in parties if p.get('kind')=='owner' and p.get('confirmed'))
        body += _party_form(session)
    body += '</section>'+_rules_section(session, parties, rules)+'</div><aside class="sidebar" aria-label="الكشوف وإرشادات المراجعة"><section class="card"><div class="side-heading"><span class="dot" aria-hidden="true"></span><h2>كشف حساب</h2></div><p class="quiet">حدد الطرفين والعملة ونوع الذمة للاطلاع على الحركة</p><form action="/finance/statement" method="get"><div class="formgrid" style="grid-template-columns:1fr">'+_select('owner_id','صاحب الحساب للكشف',_party_options(parties,'owner'),required=True)+_select('counterparty_id','الجهة المقابلة للكشف',_party_options(parties,'counterparty'),required=True)+_select('currency','عملة الكشف',CURRENCIES,required=True,blank='اختر العملة المؤكدة',hint='رمز العملة كما ورد في المستندات')+_select('side','نوع الذمة',SIDES.items(),blank=None,value='receivable')+'</div><div class="actions"><button type="submit" class="btn secondary">عرض كشف الحساب</button></div></form></section><section class="card"><div class="side-heading"><span class="dot" aria-hidden="true"></span><h2>مسار الاعتماد</h2></div><ol class="checklist"><li><strong><span class="step">1</span>توثيق المصدر</strong>المبلغ الأصلي وموضعه والجهتان دون تخمين</li><li><strong><span class="step">2</span>مراجعة التفاصيل</strong>الهوية والعملة والتاريخ وأي تقريب عشري</li><li><strong><span class="step">3</span>ترحيل إداري</strong>اعتماد صريح قبل التأثير على الأرصدة</li><li><strong><span class="step">4</span>تسوية قابلة للتتبع</strong>ربط إثباتات القبض والدفع بالمستندات دون تحويل أموال</li></ol></section><section class="card"><h2>آخر النشاط</h2><p class="quiet">من قام بالإجراء ومتى</p>'+_audit(audit)+'</section><section class="card"><h3>نطاق هذه المساحة</h3><p class="quiet">سجل مساعد تشغيلي للذمم. لا يمثل دفتر أستاذ متكاملًا بالقيد المزدوج أو نظام فواتير ضريبية معتمدًا.</p><div class="divider"></div><p class="quiet">الضريبة وصافي الربح غير محسوبين. ربط المستند بشحنة لا يثبت تلقائيًا الإيراد أو التكلفة.</p></section></aside></div>'
    return _page(session,'المحاسبة والمالية',body)


def _definition(label, value, wide=False):
    return '<div'+(' class="wide"' if wide else '')+'><dt>'+esc(label)+'</dt><dd>'+esc(value if value is not None and value != '' else 'غير محدد')+'</dd></div>'


def _review_controls(session, document):
    role, status, doc_id = session.get('role'), document.get('status'), _id(document.get('id'))
    if not _can_edit(session) and not _can_approve(session):
        return '<p class="role-note">صلاحيتك الحالية للعرض فقط</p>'
    issues = document.get('validation_issues') or []
    body = '<section class="card no-print"><div class="section-head"><div><h2>المراجعة والاعتماد</h2><p>كل إجراء يحفظ في سجل التدقيق</p></div></div>'
    if issues:
        body += '<div class="notice danger"><strong>نقاط تحتاج معالجة قبل الترحيل</strong><ul>'+''.join('<li>'+esc(x)+'</li>' for x in issues)+'</ul></div>'
    if status == 'draft' and _can_edit(session):
        body += '<form method="post" action="/finance/documents/'+doc_id+'/review">'+_tokens(session)+_field('reason','ملاحظة المراجعة',kind='textarea',required=True,placeholder='ما الذي راجعته في المصدر؟ وما نتيجة التحقق؟')+'<label class="check"><input type="checkbox" name="confirmation" value="1" required><span>راجعت المصدر والجهتين ونوع المستند والمبلغ والعملة والتاريخ، وفهمت أي بيانات ناقصة موضحة أعلاه.</span></label>'
        if document.get('kind') in OPENING_KINDS:
            body += '<label class="check"><input type="checkbox" name="opening_ack" value="1" required><span>أقر أن صافي الرصيد الافتتاحي المعتمد يشمل المطالبات أو الديون والتسويات التاريخية حتى تاريخ القطع، وألا تعاد إضافة الحركات التاريخية المشمولة فيه. '+esc(OPENING_NOTICE)+'.</span></label>'
        if document.get('rounding_required'):
            body += '<label class="check"><input type="checkbox" name="rounding_ack" value="1" required><span>راجعت الفرق بين المبلغ الأصلي والمبلغ المقرب المعروض، وأقر التقريب وفق دقة العملة.</span></label>'
        body += '<button class="btn" type="submit">تسجيل المراجعة</button><p class="hint">المراجعة لا ترحّل المستند ولا تنفذ أي دفع</p></form>'
    elif status == 'reviewed' and _can_approve(session):
        body += '<form method="post" action="/finance/documents/'+doc_id+'/post">'+_tokens(session)+_field('reason','سبب الاعتماد',kind='textarea',required=True)+'<label class="check"><input type="checkbox" name="confirmation" value="1" required><span>أعتمد ترحيل هذا المستند بالمبلغ والعملة والجهتين المعروضين. سيؤثر في سجل الذمم، ولا ينفذ تحويلًا ماليًا.</span></label>'
        if document.get('kind') in OPENING_KINDS:
            body += '<label class="check"><input type="checkbox" name="opening_ack" value="1" required><span>أعتمد صافي الرصيد الافتتاحي حتى تاريخ القطع وفق مرجع موافقة المستخدم أو صاحب الحساب، وأقر أنه يشمل المطالبات أو الديون والتسويات التاريخية وألا تعاد إضافة الحركات المشمولة فيه. '+esc(OPENING_NOTICE)+'.</span></label>'
        body += '<button class="btn" type="submit"'+(' disabled' if issues else '')+'>اعتماد وترحيل المستند</button></form>'
    elif status == 'reviewed':
        body += '<div class="notice neutral">تمت المراجعة. ينتظر المستند اعتماد مدير النظام للترحيل.</div>'
    elif status == 'posted' and _can_approve(session):
        body += '<p class="quiet">المستند مرحّل. تصحيح أثره يكون بقيد عكسي موثق مع الاحتفاظ بالقيد الأصلي.</p><details><summary>عكس المستند المرحّل</summary><form method="post" action="/finance/documents/'+doc_id+'/reverse">'+_tokens(session)+_field('reason','سبب العكس',required=True,kind='textarea')+'<label class="check"><input type="checkbox" name="confirmation" value="1" required><span>أعتمد إنشاء قيد عكسي لهذا المستند. سيبقى القيد الأصلي في السجل، ولا يمثل العكس استردادًا أو تحويلًا ماليًا.</span></label><button class="btn danger" type="submit">اعتماد القيد العكسي</button></form></details>'
    elif status in ('void','voided'):
        body += '<div class="notice neutral">ألغي هذا المستند دون حذف الدليل أو التأثير على الأرصدة المرحّلة.</div>'
    elif status == 'reversed':
        body += '<div class="notice neutral">تم عكس الأثر بقيد مستقل. يحتفظ السجل بالمستند الأصلي وسبب العكس.</div>'
    elif status == 'posted':
        body += '<p class="quiet">المستند مرحّل ومحفوظ في سجل الذمم</p>'
    else:
        body += '<p class="quiet">يتطلب هذا الإجراء صلاحية مراجعة المستندات</p>'
    if _can_approve(session) and status in ('draft','reviewed'):
        body += '<div class="divider"></div><details><summary>إلغاء المستند دون حذف الدليل</summary><p class="quiet">إذا كانت بيانات المسودة خاطئة، ألغها مع ذكر السبب ثم أنشئ مستندًا صحيحًا. يحتفظ السجل بالدليل الأصلي.</p><form method="post" action="/finance/documents/'+doc_id+'/void">'+_tokens(session)+_field('void-reason','سبب الإلغاء',required=True,kind='textarea').replace('name="void-reason"','name="reason"')+'<div class="actions"><button class="btn danger" type="submit">إلغاء المستند دون حذف</button></div></form></details>'
    return body+'</section>'


def _allocation_section(session, document, allocations, candidates):
    body = '<section class="card"><div class="section-head"><div><h2>الربط والتسوية</h2><p>تخصيص إثبات قبض أو دفع أو تسوية غير نقدية لمستند من الجهتين والعملة نفسيهما</p></div></div>'
    if allocations:
        rows = ''.join('<tr><td>'+esc(a.get('id'))+'</td><td><a href="/finance/documents/'+_id(a.get('credit_id'))+'">#'+esc(a.get('credit_id'))+'</a></td><td><a href="/finance/documents/'+_id(a.get('document_id'))+'">#'+esc(a.get('document_id'))+'</a></td><td>'+_number(a.get('amount_display'))+'</td><td>'+('<span class="tag reversed">معكوس · غير مطبق</span>' if a.get('reversed_at') else '<span class="tag posted">نشط · مطبق</span>')+'</td><td>'+esc(a.get('created_at'))+'</td><td>'+esc(a.get('reversed_at') or '—')+'</td></tr>' for a in allocations)
        body += _table(['الربط','إثبات / تسوية دائنة','المستند المقابل','المبلغ','حالة التخصيص','تاريخ التسجيل','تاريخ العكس'],rows,'التخصيصات النشطة والمعكوسة لهذا المستند')+'<p class="hint">التخصيص المعكوس محفوظ للتدقيق فقط؛ لا يدخل في المبلغ المخصص أو المتبقي لأي من المستندين. التخصيص نفسه لا يغيّر رصيد الذمة.</p>'
    else:
        body += '<p class="quiet">لا توجد تخصيصات مسجلة لهذا المستند</p>'
    kind, status = document.get('kind'), document.get('status')
    is_credit = kind in ('receipt','payment','receivable_adjustment','payable_adjustment')
    if _can_approve(session) and status == 'posted' and candidates:
        allowed = []
        compatible_kinds = ('claim','opening_receivable') if kind in ('receipt','receivable_adjustment') else ('payable','expense','opening_payable') if kind in ('payment','payable_adjustment') else ('receipt','receivable_adjustment') if kind in ('claim','opening_receivable') else ('payment','payable_adjustment') if kind in ('payable','expense','opening_payable') else ()
        for c in candidates:
            if c.get('kind') not in compatible_kinds or c.get('status') != 'posted' or str(c.get('id')) == str(document.get('id')):
                continue
            if any(str(c.get(k)) != str(document.get(k)) for k in ('owner_id','counterparty_id','currency')):
                continue
            opening = document if kind in OPENING_KINDS else c if c.get('kind') in OPENING_KINDS else None
            credit = document if is_credit else c
            if opening is not None:
                try:
                    cutoff = date.fromisoformat(str(opening.get('opening_cutoff')))
                    credit_date = date.fromisoformat(str(credit.get('document_date')))
                except ValueError:
                    continue
                if credit_date <= cutoff:
                    continue
            allowed.append((c.get('id'),'#'+str(c.get('id'))+' · '+str(KINDS.get(c.get('kind'),''))+' · '+str(c.get('source_ref') or '')+' · متبقٍ '+str(c.get('remaining_display','غير محدد'))+' '+str(c.get('currency') or '')))
        if allowed:
            fixed_name, choice_name = ('credit_id','document_id') if is_credit else ('document_id','credit_id')
            body += '<details class="no-print"><summary>تسجيل تخصيص جديد</summary><form method="post" action="/finance/allocations">'+_tokens(session)+'<input type="hidden" name="'+fixed_name+'" value="'+esc(document.get('id'))+'"><div class="formgrid">'+_select(choice_name,'المستند المقابل',allowed,required=True)+_field('allocation-amount','مبلغ التخصيص',required=True,attrs='inputmode="decimal" dir="ltr"').replace('name="allocation-amount"','name="amount"')+'</div><p class="hint">ربط محاسبي فقط، دون نقل أموال. يجب ألا يتجاوز المبلغ المتبقي في أي من المستندين.</p><div class="actions"><button class="btn secondary" type="submit">حفظ التخصيص</button></div></form></details>'
    return body+'</section>'


def render_document(session, document, allocations, audit, candidates):
    """Render source evidence, status, review controls and same-ledger allocations."""
    document = document or {}
    doc_id, status = document.get('id'), document.get('status')
    kind_label = KINDS.get(document.get('kind'), document.get('kind') or 'مستند مالي')
    body = '<div class="actions no-print" style="margin:0 0 16px"><a class="btn secondary small" href="/finance">← العودة إلى مساحة المالية</a>'+_badge(status)+'</div>'
    body += _hero(kind_label+' #'+str(doc_id or ''), 'راجع الدليل الأصلي والأطراف والمبلغ قبل اتخاذ أي إجراء في السجل.', 'تفاصيل المستند · '+str(document.get('source_ref') or ''), '↗')
    if document.get('supersedes_id'):
        body += '<div class="notice neutral">هذا المستند بديل موثق للمستند <a href="/finance/documents/'+_id(document['supersedes_id'])+'">#'+esc(document['supersedes_id'])+'</a> بعد إلغائه أو عكسه. يظل الدليل السابق محفوظًا دون تعديل.</div>'
    body += '<div class="process" aria-label="مراحل المستند">'+''.join('<span'+(' class="current" aria-current="step"' if status == step else '')+'>'+label+'</span>' for step,label in [('draft','01 · مسودة'),('reviewed','02 · مراجعة'),('posted','03 · ترحيل'),('reversed','04 · عكس عند الحاجة')])+'</div>'
    if document.get('kind') in ('receivable_adjustment','payable_adjustment'):
        body += '<div class="notice neutral">تسوية غير نقدية: لا تمثل قبضًا أو دفعًا أو تنفيذ تحويل مالي.</div>'
    if document.get('kind') in OPENING_KINDS:
        is_payable = document.get('kind') == 'opening_payable'
        direction = 'صافي الدين التاريخي على صاحب الحساب' if is_payable else 'صافي المستحق التاريخي لصاحب الحساب'
        settlement = 'إثبات دفع فعلي أو تسوية غير نقدية للذمم الدائنة' if is_payable else 'إثبات قبض فعلي أو تسوية غير نقدية للذمم المدينة'
        body += '<section class="card"><h2>'+esc(kind_label)+'</h2><div class="notice neutral">'+esc(OPENING_NOTICE)+'. يمثل '+direction+' المعتمد حتى تاريخ القطع؛ لا تعاد إضافة المطالبات أو الديون أو التسويات التاريخية المشمولة فيه. يخصص له لاحقًا '+settlement+' بتاريخ بعد القطع فقط.</div>'
        if is_payable:
            body += '<p class="hint">مبلغ الدين على صاحب الحساب يسجل كقيمة رقمية موجبة؛ يبقى نص المبلغ الأصلي بإشارته محفوظًا دون تغيير.</p>'
        body += '<dl class="detail-grid">'+_definition('تاريخ قطع الرصيد الافتتاحي',document.get('opening_cutoff'))+_definition('مرجع اعتماد صافي الرصيد من المستخدم أو صاحب الحساب',document.get('opening_confirmation_ref'),True)+_definition('إقرار شمول الحركات التاريخية ومنع تكرارها','تم الإقرار أثناء المراجعة' if document.get('opening_review_ack') else 'بانتظار إقرار المراجعة')+'</dl><p class="hint">تاريخ القطع ومرجع الاعتماد محفوظان دون تعديل لاحق. اعتماد صافي الرصيد لا يعني تحققًا مستقلًا من المصدر، وإقرار التقريب منفصل.</p></section>'
    body += '<div class="workspace"><div class="stack"><section class="card"><div class="section-head"><div><h2>تفاصيل القيد</h2><p>'+esc(SIDES.get(document.get('side'), 'الجهة المحاسبية تُحدد أثناء التحقق'))+'</p></div>'+_badge(status)+'</div><dl class="detail-grid">'+''.join(_definition(label,document.get(key)) for label,key in [('صاحب الحساب','owner_name'),('الجهة المقابلة','counterparty_name'),('تاريخ المستند','document_date'),('مرجع المصدر','source_ref'),('مرجع الحركة الاقتصادية','economic_ref'),('مرجع الفاتورة','invoice_ref'),('البيان الجمركي','customs_ref'),('معرّف الشحنة','shipment_id'),('العملة','currency')])+_definition('أساس المبلغ',BASES.get(document.get('amount_basis'),'غير محدد'))+'</dl><div class="detail-money">'+''.join('<div class="money-tile"><small>'+label+'</small><strong>'+_number(document.get(key))+'</strong></div>' for label,key in [('قيمة المستند','amount_display'),('المبلغ المخصص','allocated_display'),('المتبقي للتخصيص','remaining_display')])+'</div><p class="hint">جميع القيم بعملة المستند: '+_currency(document.get('currency'))+'. التخصيص يربط المستندات ولا ينشئ حركة نقدية جديدة.</p></section><section class="card"><div class="section-head"><div><h2>الدليل والمبلغ الأصلي</h2><p>القيم المحفوظة من المصدر، دون استبدالها بافتراضات</p></div><span class="tag">قابل للتتبع</span></div><dl class="detail-grid">'+_definition('موضع الدليل في المصدر',document.get('source_locator'),True)+_definition('نص المبلغ الأصلي',document.get('source_amount_raw'),True)+_definition('مقدار الرصيد الدائن قبل التقريب' if document.get('kind') == 'opening_payable' else 'القيمة العشرية الأصلية',document.get('source_amount'))+_definition('المبلغ وفق دقة العملة',document.get('rounded_amount_display') or document.get('amount_display'))+_definition('نوع المصدر',('ملخص تجميعي لصافي الرصيد الافتتاحي' if document.get('kind') in OPENING_KINDS else 'ملخص تجميعي: دليل فقط') if document.get('source_role')=='summary' else 'حركة تفصيلية' if document.get('source_role')=='detail' else 'غير محدد')+_definition('التاريخ كما ورد بالمصدر',document.get('source_date_raw'))+_definition('حالة المصدر الأصلية',document.get('source_status_raw'))+_definition('مستوى التحقق','تم التحقق بدليل مستقل' if document.get('source_verification')=='independently_verified' else 'مسجل من المصدر فقط')+_definition('مرجع التحقق المستقل',document.get('verification_ref'))+_definition('اعتماد على صيغة خارجية مخزنة',('نعم؛ يستند الرصيد الافتتاحي إلى مرجع الاعتماد الصريح أعلاه، ولا يعد ذلك تحققًا مستقلًا' if document.get('kind') in OPENING_KINDS and document.get('opening_confirmation_ref') else 'نعم؛ يلزم مرجع اعتماد صريح لصافي الرصيد الافتتاحي' if document.get('kind') in OPENING_KINDS else 'نعم؛ يلزم تحقق مستقل') if document.get('source_cached_external') else 'غير معلّم كمصدر خارجي مخزن')+'</dl>'
    if document.get('rounding_required'):
        body += '<div class="notice"><strong>يتطلب إقرار التقريب</strong><br>الدقة العشرية في المصدر تتجاوز دقة العملة. راجع المبلغ الأصلي والمبلغ المقرب أعلاه قبل اعتماد المراجعة.</div>'
    if not document.get('currency'):
        body += '<div class="notice danger">العملة غير محددة. لا يمكن ترحيل هذا المستند حتى توثيق العملة الصحيحة.</div>'
    source_raw = document.get('source_raw')
    if source_raw is not None:
        if not isinstance(source_raw,str):
            source_raw = json.dumps(source_raw,ensure_ascii=False,indent=2,default=str)
        body += '<details><summary>عرض سجل المصدر المحفوظ</summary><pre class="source">'+esc(source_raw)+'</pre></details>'
    if document.get('notes'):
        body += '<div class="divider"></div><h3>ملاحظات المستند</h3><div class="source">'+esc(document.get('notes'))+'</div>'
    body += '</section>'+_review_controls(session,document)+_allocation_section(session,document,allocations or [],candidates or [])+'</div><aside class="sidebar" aria-label="التدقيق وحالة المستند"><section class="card"><h2>سجل التدقيق</h2><p class="quiet">تسلسل الإجراءات لهذا المستند</p>'+_audit(audit or [])+'</section><section class="card"><h2>أثر المستند</h2><dl class="detail-grid" style="grid-template-columns:1fr">'+_definition('أنشئ في',document.get('created_at'))+_definition('تمت المراجعة بواسطة',document.get('reviewed_by'))+_definition('تم الترحيل بواسطة',document.get('posted_by'))+'</dl>'
    if document.get('reversal_reason'):
        body += '<div class="divider"></div><h3>سبب العكس</h3><p class="quiet">'+esc(document.get('reversal_reason'))+'</p>'
    body += '<p class="legal">الاعتماد يحدّث السجل التشغيلي فقط. الضريبة وصافي الربح غير محسوبين، وهذه الصفحة ليست فاتورة ضريبية.</p></section></aside></div>'
    return _page(session,'تفاصيل مستند #'+str(doc_id or ''),body)


def render_statement(session, owner, counterparty, currency, entries, balance, side='receivable'):
    """Render one counterparty/currency/side; never net different subledgers."""
    owner, counterparty, entries = owner or {}, counterparty or {}, list(entries or [])
    side = side if side in SIDES else 'receivable'
    query = urlencode({'owner_id':owner.get('id',''),'counterparty_id':counterparty.get('id',''),'currency':currency or '','side':side})
    body = '<div class="actions no-print" style="margin:0 0 16px"><a class="btn secondary small" href="/finance">← العودة إلى مساحة المالية</a><a class="btn secondary small" href="/finance/statement.csv?'+esc(query)+'">تنزيل الكشف CSV</a></div>'
    body += _hero('كشف حساب · '+SIDES[side], 'حركة مستقلة لصاحب الحساب والجهة المقابلة بالعملة المحددة، مع الاحتفاظ بالقيود الأصلية والعكسية.', 'STATEMENT · OPERATIONAL SUBLEDGER','≡')
    body += '<section class="card"><dl class="detail-grid">'+_definition('صاحب الحساب',owner.get('name'))+_definition('الجهة المقابلة',counterparty.get('name'))+_definition('العملة',currency or 'غير محددة')+'</dl><div class="detail-money"><div class="money-tile"><small>رصيد '+SIDES[side]+'</small><strong>'+_number(balance)+'</strong></div><div class="money-tile"><small>عملة الكشف</small><strong>'+_currency(currency)+'</strong></div><div class="money-tile"><small>عدد الحركات المعروضة</small><strong>'+str(len(entries))+'</strong></div></div><p class="hint">الرصيد يخص '+SIDES[side]+' فقط. '+('الرصيد الموجب مستحق على الجهة، والسالب رصيد لصالحها. ' if side=='receivable' else 'الرصيد الموجب التزام للجهة، والسالب رصيد مقدم. ')+'لا تجري مقاصة مع نوع الذمة الآخر ولا تحويل بين العملات.</p></section><section class="card"><div class="section-head"><div><h2>حركة الحساب</h2><p>المستندات المرحّلة وقيود العكس المستقلة بحسب السجل</p></div><span class="tag">'+esc(SIDES[side])+'</span></div>'
    if entries:
        statement_rows = ''.join('<tr><td>'+esc(e.get('document_date') or 'غير محدد')+'<span class="cell-sub">سُجل: '+esc(e.get('created_at') or 'غير محدد')+'</span></td><td><a href="/finance/documents/'+_id(e.get('document_id',e.get('id')))+'">'+esc(e.get('source_ref') or '#'+str(e.get('id','')))+'</a><span class="cell-sub">'+esc(e.get('invoice_ref'))+'</span></td>'+_kind_cell(e)+'<td>'+_badge(e.get('status'))+'</td><td>'+_number(e.get('debit_display'))+'</td><td>'+_number(e.get('credit_display'))+'</td><td class="amount">'+_number(e.get('running_display'))+'</td></tr>' for e in entries)
        body += _table(['التاريخ','المصدر / الفاتورة','النوع','حالة القيد','مدين','دائن','الرصيد الجاري'],statement_rows,'كشف '+SIDES[side]+' · '+str(currency or 'عملة غير محددة'))
    else:
        body += _empty('لا توجد حركات لهذا الكشف','لم تسجل حركات مرحّلة تطابق الطرفين والعملة ونوع الذمة المختار.')
    body += '<p class="legal">سجل مساعد تشغيلي؛ ليس دفتر أستاذ متكاملًا بالقيد المزدوج. المستند المعكوس وقيده العكسي يحتفظان بمسار تدقيق مستقل. لا يشمل الكشف ضريبة محسوبة أو صافي ربح.</p></section>'
    return _page(session,'كشف حساب · '+SIDES[side],body)
