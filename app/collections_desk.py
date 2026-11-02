"""Collections: who owes what, since when, and quick payment recording (owner-requested, Nov 2026).

- /collections: receivable balance per counterparty (posted entries only), drafts awaiting approval,
  oldest posted claim, last receipt, link to the statement, and a ready reminder text.
- WhatsApp team tools: customer_balance («كم على الياسمين») and record_payment («استلمنا 50000 من الياسمين»).
  A payment is created as a finance DRAFT receipt; the owner reviews and posts it. Nothing is sent to customers.
"""
import datetime as dt
import re
import uuid
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.storage import db

router = APIRouter()

BALANCES = '''SELECT p.id, p.name,
    COALESCE(SUM(e.signed_minor) FILTER (WHERE e.side='receivable'),0) receivable_minor,
    COALESCE(SUM(e.signed_minor) FILTER (WHERE e.side='payable'),0) payable_minor,
    MIN(d.document_date) FILTER (WHERE d.kind IN ('claim','opening_receivable') AND d.status='posted') oldest_claim,
    MAX(d.document_date) FILTER (WHERE d.kind='receipt' AND d.status='posted') last_receipt,
    (SELECT COUNT(*) FROM finance_documents x WHERE x.counterparty_id=p.id AND x.status IN ('draft','reviewed')) drafts
  FROM finance_party_display p
  LEFT JOIN finance_documents d ON d.counterparty_id=p.id AND d.status IN ('posted','reversed') AND d.currency='SAR'
  LEFT JOIN finance_entries e ON e.document_id=d.id
  WHERE p.kind='counterparty'
  GROUP BY p.id,p.name ORDER BY receivable_minor DESC'''


def sar(minor):
    return format(Decimal(minor or 0) / 100, ',.2f')


def balances():
    with db() as c:
        return c.execute(BALANCES).fetchall()


def fold(text):
    text = re.sub(r'[ً-ٰٟـ]', '', str(text or '')).lower()
    return text.translate(str.maketrans('أإآىئة', 'اااييه')).replace('ال', '', 1).strip()


def find_party(name):
    target = fold(name)
    if not target:
        return None
    rows = [r for r in balances() if target in fold(r['name']) or fold(r['name']) in target]
    return rows[0] if len(rows) == 1 else (rows if rows else None)


def reminder_text(row):
    return ('السلام عليكم ورحمة الله،\nنفيدكم بأن الرصيد المستحق لمؤسسة آفاق طويق للتخليص الجمركي في حسابكم '
            + sar(row['receivable_minor']) + ' ريال.\nنأمل التكرم بالسداد، ويسعدنا تزويدكم بكشف الحساب التفصيلي عند الطلب.\n'
            'للاستفسار: 0507665873 — مع الشكر.')


def customer_balance_text(name):
    found = find_party(name)
    if not found:
        return 'لم أجد عميلًا بهذا الاسم في المالية.'
    if isinstance(found, list):
        return 'وجدت أكثر من جهة: ' + '، '.join(r['name'] for r in found[:6]) + '. حدد الاسم.'
    r = found
    text = r['name'] + ': الرصيد المستحق ' + sar(r['receivable_minor']) + ' ريال'
    if r['oldest_claim']:
        text += '\nأقدم مطالبة مرحّلة: ' + r['oldest_claim'].isoformat()
    if r['last_receipt']:
        text += '\nآخر دفعة: ' + r['last_receipt'].isoformat()
    if r['drafts']:
        text += '\nمسودات بانتظار الاعتماد: ' + str(r['drafts'])
    return text


def record_payment(name, amount, actor, *, date=None, ref=''):
    found = find_party(name)
    if not found or isinstance(found, list):
        return customer_balance_text(name) if found else 'لم أجد هذه الجهة في المالية؛ لم يُسجل شيء.'
    try:
        value = Decimal(str(amount).replace(',', '').strip())
    except InvalidOperation:
        return 'المبلغ غير واضح؛ لم يُسجل شيء.'
    if value <= 0:
        return 'المبلغ غير صالح؛ لم يُسجل شيء.'
    date = date or dt.date.today()
    from app import finance_service as service
    with db() as c:
        owner = c.execute("SELECT id FROM finance_party_display WHERE kind='owner' AND confirmed ORDER BY id LIMIT 1").fetchone()
    key = uuid.uuid5(uuid.NAMESPACE_URL, 'payment:%s:%s:%s:%s' % (found['id'], value, date, ref or ''))
    form = {'kind': 'receipt', 'currency': 'SAR', 'amount': format(value, 'f'), 'document_date': date.isoformat(),
            'amount_basis': 'gross', 'source_role': 'detail', 'source_verification': 'recorded',
            'owner_id': str(owner['id']), 'counterparty_id': str(found['id']),
            'source_ref': 'دفعة من ' + found['name'] + (' — ' + ref if ref else '') + ' بتاريخ ' + date.isoformat(),
            'source_locator': 'إفادة الفريق عبر واتساب' + (' — ' + ref if ref else ''),
            'economic_ref': 'RECEIPT:' + str(found['id']) + ':' + date.isoformat() + ':' + format(value, 'f') + (':' + ref if ref else ''),
            'source_amount_raw': format(value, 'f') + ' SAR', 'notes': 'دفعة مسجلة من واتساب الفريق؛ مسودة بانتظار مراجعة صاحب الحساب وترحيلها وربطها بالمطالبات.',
            'idempotency_key': str(key)}
    try:
        doc_id = service.create_document(form, actor)
    except Exception as exc:
        return 'تعذر تسجيل الدفعة: ' + str(getattr(exc, 'detail', exc))[:200]
    return ('سُجلت دفعة ' + format(value, ',.2f') + ' ريال من ' + found['name'] + ' كمسودة قبض رقم ' + str(doc_id)
            + '. اعتمدها من صفحة المالية لتُخصم من الرصيد.')


@router.get('/collections', response_class=HTMLResponse)
def page(request: Request):
    from app.social_content import e, page as layout
    from app.social_publishing import admin
    admin(request)
    rows = [r for r in balances() if r['receivable_minor'] or r['drafts']]
    total = sum(r['receivable_minor'] for r in rows if r['receivable_minor'] > 0)
    today = dt.date.today()
    body = '<div class="nav"><a href="/finance">المحاسبة والمالية</a><a href="/billing">فوترة البيانات</a></div>'
    body += ('<div class="hero"><h1>التحصيل</h1><p>إجمالي المستحق لكم (مرحّل): <b>' + sar(total) + ' ريال</b></p>'
             '<p class="muted">الأرصدة من القيود المرحّلة فقط. المسودات لا تدخل الرصيد حتى تعتمدها. التذكير نص جاهز تنسخه وترسله بنفسك.</p></div>')
    body += '<div class="card scroll"><table><tr><th>الجهة</th><th>المستحق</th><th>أقدم مطالبة</th><th>آخر دفعة</th><th>مسودات</th><th></th></tr>'
    for r in rows:
        age = (today - r['oldest_claim']).days if r['oldest_claim'] else None
        body += ('<tr><td>' + e(r['name']) + '</td><td><b>' + sar(r['receivable_minor']) + '</b></td><td>' +
                 (e(r['oldest_claim']) + ' (' + str(age) + ' يوم)' if age is not None else '—') + '</td><td>' + e(r['last_receipt'] or '—') +
                 '</td><td>' + str(r['drafts']) + '</td><td><a class="btn" href="/finance/statement?owner_id=1&counterparty_id=' + str(r['id']) +
                 '&currency=SAR&side=receivable">كشف الحساب</a><details><summary>نص التذكير</summary><pre style="white-space:pre-wrap">' +
                 e(reminder_text(r)) + '</pre></details></td></tr>')
    body += '</table></div>'
    return HTMLResponse(layout(body), headers={'Cache-Control': 'no-store'})
