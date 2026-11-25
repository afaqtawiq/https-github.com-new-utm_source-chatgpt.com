"""Finance desk upgrade on isolated PostgreSQL with synthetic ledger data (finance_service, the real posting path).
Aging (FIFO), monthly overview, control checks, playbooks (read-only); posting only through the manager-approved preview."""
import datetime as dt
import os
import secrets
import sys
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    from app import finance_desk as fd, finance_schema, finance_service as ledger
    from app.storage import db, utcnow
    finance_schema.init_storage()
    with db() as c:
        actor = c.execute("INSERT INTO users(email,name,password_hash,role,created_at) VALUES('fin@fixture.invalid','fin','x','admin',%s) RETURNING id",
                          (utcnow(),)).fetchone()['id']
    owner = ledger.create_party(dict(name='آفاق تجريبي', kind='owner', identity_ref='OWN-1', confirmed='1'), actor)
    a = ledger.create_party(dict(name='عميل منتظم', kind='counterparty', identity_ref='C-A', confirmed='1'), actor)
    b = ledger.create_party(dict(name='عميل متأخر', kind='counterparty', identity_ref='C-B', confirmed='1'), actor)
    seq = [0]

    def form(**extra):
        return dict(idempotency_key=str(uuid.uuid4()), **extra)

    def doc(party, kind, amount, day, posted=True, refs=True, inv=None):
        seq[0] += 1
        did = ledger.create_document(form(owner_id=owner, counterparty_id=party, kind=kind, currency='SAR', amount=amount, document_date=day,
                                          source_ref='SRC', source_locator='LOC-' + str(seq[0]), economic_ref='EV-' + str(seq[0]),
                                          source_role='detail', amount_basis='gross', notes='',
                                          invoice_ref=inv if inv is not None else (('INV-' + str(seq[0])) if refs else ''), customs_ref=('C-' + str(seq[0])) if refs else ''), actor)
        if posted:
            ledger.review_document(did, actor, form(confirmation='1'))
            ledger.post_document(did, actor, form(confirmation='1', reason='test'))
        return did

    # Customer B: claims 10/07 (140 days), 15/09 (71 days), 05/11 (20 days); paid 6,000 → settles the oldest first.
    doc(b, 'claim', '5000', '2026-07-08')
    doc(b, 'claim', '4000', '2026-09-15')
    doc(b, 'claim', '3000', '2026-11-05')
    doc(b, 'receipt', '6000', '2026-11-10')
    # Customer A: claim 10,000 (01/11) paid 4,000 (12/11); a claim without references.
    doc(a, 'claim', '10000', '2026-11-01')
    doc(a, 'receipt', '4000', '2026-11-12')
    doc(a, 'claim', '1500', '2026-11-03', refs=False)
    # Drafts: two identical expenses (possible duplicate), one old draft.
    doc(a, 'expense', '700', '2026-11-20', posted=False)
    doc(a, 'expense', '700', '2026-11-20', posted=False)
    doc(b, 'receipt', '900', '2026-11-02', posted=False)
    with db() as c:
        before = c.execute('SELECT COUNT(*) n, COALESCE(SUM(signed_minor),0) s FROM finance_entries').fetchone()

    as_of = dt.date(2026, 11, 25)
    ag = fd.aging(as_of)
    # B: 12,000 billed − 6,000 paid → the 10/07 claim (5,000) and 1,000 of the 15/09 claim are settled.
    assert ag['عميل متأخر']['total'] == 600000 and ag['عميل متأخر']['buckets'] == [300000, 0, 300000, 0], ag['عميل متأخر']
    assert ag['عميل متأخر']['oldest_open'] == dt.date(2026, 9, 15)
    assert ag['عميل منتظم']['total'] == 750000 and ag['عميل منتظم']['buckets'] == [750000, 0, 0, 0]
    text = fd.aging_text(as_of)
    assert 'الإجمالي: 13,500.00 ريال' in text and '61–90 يوم: 3,000.00' in text and 'أقدم مطالبة مفتوحة منذ 71 يوم' in text

    ov = fd.overview('2026-11')
    assert 'المفوتر (مطالبات مرحّلة): 14,500.00 ريال' in ov and 'المحصّل (سندات قبض مرحّلة): 10,000.00 ريال' in ov
    assert 'نسبة التحصيل للشهر: 68%' in ov and 'المصروفات المسجلة: 1,400.00 ريال (2 مصروف' in ov
    assert 'الذمم المدينة الآن: 13,500.00 ريال' in ov and 'بانتظار اعتمادك وترحيلك' in ov

    ck = fd.checks(as_of)  # (before posting)
    assert 'قد تكون مكررة' in ck and 'مصروفات 700.00' in ck and 'مسودات عمرها أكثر من 7 أيام' not in ck
    later = fd.checks(dt.date(2026, 12, 5))  # the same drafts, 10 days on: now unposted for more than 7 days
    assert 'مسودات عمرها أكثر من 7 أيام' in later and 'سندات قبض: 1 بقيمة 900.00' in later
    assert '1 مطالبة مرحّلة بدون رقم فاتورة ولا رقم بيان' in ck

    # Over 90 days appears in checks once a claim ages past 90 (same data, 30 days later).
    assert 'ذمم فوق 90 يوم' in fd.checks(dt.date(2026, 12, 25))

    # Read-only: the desk posted / changed nothing.
    with db() as c:
        assert c.execute('SELECT COUNT(*) n, COALESCE(SUM(signed_minor),0) s FROM finance_entries').fetchone() == before

    # Playbooks: Arabic questions open the right guide; the answer carries the guide and the caution.
    assert fd.choose('هل نحط ضريبة القيمة المضافة على الرسوم الجمركية المدفوعة نيابة عن العميل؟')[0] == 'saudi-vat-logistics'
    assert fd.choose('متى لازم نربط الفاتورة الالكترونية مع زاتكا')[0] == 'e-invoicing-fatoora'
    assert fd.choose('سوي لي قائمة اقفال الشهر')[0] == 'month-end-close'
    assert fd.choose('كيف نحسب ربحية الشحنة')[0] == 'shipment-profitability'
    assert fd.choose('مين متأخر في التحصيل وايش سياسة الذمم')[0] == 'receivables-collections'
    pb = fd.playbook('ضريبة النقل الدولي')
    assert pb.startswith('📘 دليل «saudi-vat-logistics»') and '0%' in pb and 'المحاسب القانوني' in pb
    assert len(fd.index()) == 11

    # ---------- Posting: full preview, all-or-nothing gate ----------
    def entries():
        with db() as c:
            return c.execute('SELECT COUNT(*) n, COALESCE(SUM(signed_minor),0) s FROM finance_entries').fetchone()
    chosen, held, missing = fd.post_preview()
    assert [r['amount_minor'] for r in chosen] == [90000] and len(held) == 2 and all('تكرار محتمل' in w for _, w in held)
    receipt = chosen[0]
    assert receipt['source_ref'] == 'SRC' and receipt['currency'] == 'SAR'
    snap = [(receipt['id'], fd.fingerprint(receipt), False)]
    pdf_bytes = fd.preview_pdf(chosen, held, missing, 'ABC123', dt.datetime(2026, 11, 25, 15, 0))
    assert pdf_bytes.startswith(b'%PDF')
    # A duplicate appears after the preview → nothing posted, new review required.
    twin = doc(b, 'receipt', '900', '2026-11-02', posted=False)
    stop = fd.post_execute(snap, 'المدير')
    assert stop.startswith('⛔ أوقفت الترحيل كاملًا') and 'تكرار محتمل' in stop and entries() == before, stop
    ledger.void_document(twin, actor, form(confirmation='1', reason='duplicate'))
    # A changed entry (fingerprint differs) → nothing posted.
    assert 'تغيّر بعد المعاينة' in fd.post_execute([(receipt['id'], 'x' * 20, False)], 'المدير') and entries() == before
    res = fd.post_execute(snap, 'المدير')
    assert res.startswith('✅ رُحّل 1 قيد.') and 'SAR: سندات قبض 1 = 900.00 SAR' in res, res
    # Replaying the code never posts twice (the whole batch stops).
    assert 'لم يعد مسودة' in fd.post_execute(snap, 'المدير')
    # Manager picks one held duplicate by number; the other stays a draft.
    with db() as c:
        dup = [r['id'] for r in c.execute("SELECT id FROM finance_documents WHERE status='draft' ORDER BY id").fetchall()]
    chosen, held, missing = fd.post_preview([dup[0], 99999])
    assert [r['id'] for r in chosen] == [dup[0]] and missing == [99999]
    assert fd.post_execute([(dup[0], fd.fingerprint(chosen[0]), True)], 'المدير').startswith('✅ رُحّل 1')
    with db() as c:
        assert c.execute("SELECT status FROM finance_documents WHERE id=%s", (dup[1],)).fetchone()['status'] == 'draft'
    assert fd.aging(as_of)['عميل متأخر']['total'] == 510000

    # The WhatsApp tool: the «نفذ» code is only inside the PDF; if the PDF cannot be sent, no code exists.
    from app import command_agent, virtual_office, advance_reconcile
    sent = []

    async def ok_send(chat, content, name, caption):
        sent.append(content)
        return True

    async def bad_send(chat, content, name, caption):
        return False
    from app import whatsapp_admin
    with db() as c:
        whatsapp_admin.ensure_admin(c)
    doc(a, 'expense', '250', '2026-11-21', posted=False)  # one clean draft to preview
    tok = command_agent.CHAT.set(('966500000001', 'conv-1'))
    try:
        with patch.object(command_agent, '_member', return_value={'name': 'المدير', 'manager': True}):
            with patch.object(advance_reconcile, 'send_pdf', ok_send), db() as c:
                out = command_agent.tool_finance_post(c, {})
                codes = [r['token'] for r in c.execute('SELECT token FROM whatsapp_voice_pending').fetchall()]
            assert len(codes) == 1 and codes[0] not in out and 'في آخر الملف' in out and sent[0].startswith(b'%PDF'), out
            with patch.object(advance_reconcile, 'send_pdf', bad_send), db() as c:
                out = command_agent.tool_finance_post(c, {})
                assert len(c.execute('SELECT token FROM whatsapp_voice_pending').fetchall()) == 1  # the failed one was removed
            assert 'لم أجهز رمز' in out
    finally:
        command_agent.CHAT.reset(tok)
    with patch.object(command_agent, '_member', return_value={'name': 'موظف'}):
        assert 'المدير فقط' in command_agent.tool_finance_post(None, {})

    # ---------- Customer statement with allocation (October), as of 25 Nov ----------
    from app import finance_customer_statement as fcs
    cc = ledger.create_party(dict(name='عميل الكشف', kind='counterparty', identity_ref='C-C', confirmed='1'), actor)
    a_ = doc(cc, 'claim', '10000', '2026-10-05', inv='F-100')
    doc(cc, 'claim', '6000', '2026-10-20', inv='F-101')
    doc(cc, 'receipt', '4000', '2026-10-25', inv='F-101')            # proven by the invoice number on the receipt
    r3 = doc(cc, 'receipt', '3000', '2026-10-28', inv='')            # proven by a ledger allocation below
    nov = doc(cc, 'receipt', '5000', '2026-11-10', inv='')           # November, no proof → unallocated, after close
    doc(cc, 'claim', '2000', '2026-10-30', posted=False, inv='F-102')  # draft
    doc(cc, 'receipt', '1000', '2026-11-12', posted=False, inv='F-102')
    ledger.create_allocation(form(credit_id=str(r3), document_id=str(a_), amount='3000'), actor)
    with db() as c:
        before_stmt = c.execute('SELECT COUNT(*) n FROM finance_entries').fetchone()['n']
    st = fcs.build(owner, cc, 'SAR', '2026-10-01', '2026-10-31', today=dt.date(2026, 11, 25))
    assert st['official']['closing_minor'] == 900000          # the November payment does not change October's closing
    assert [x['id'] for x in st['later']] == [nov] and st['posted_today'] == 400000
    assert st['closing_incl'] == 1100000 and st['today_incl'] == 500000
    left = {d['invoice_ref']: d['left'] for d in st['debits']}
    assert left == {'F-100': 700000, 'F-101': 200000, 'F-102': 100000}, left
    how = {d['invoice_ref']: [h for _, _, h in d['paid']] for d in st['debits']}
    assert how['F-100'] == ['تخصيص مسجل'] and how['F-101'] == ['رقم الفاتورة في سند القبض']
    assert [(x['id'], x['left']) for x in st['unallocated']] == [(nov, 500000)] and st['balanced']
    text = fcs.summary_text(st)
    assert 'رصيد الإقفال في 2026-10-31 (مرحّل): 9000.00 SAR' in text and 'المتبقي للتحصيل اليوم (مرحّل): 4000.00 SAR' in text, text
    assert 'دفعات بدون تخصيص مثبت: 1 بمبلغ 5000.00 SAR' in text and '✅ المطابقة' in text
    statement_pdf = fcs.pdf(st)
    assert statement_pdf.startswith(b'%PDF')
    if os.environ.get('FINANCE_PDF_DUMP'):  # local visual check only
        open(os.path.join(os.environ['FINANCE_PDF_DUMP'], 'statement.pdf'), 'wb').write(statement_pdf)
        open(os.path.join(os.environ['FINANCE_PDF_DUMP'], 'preview.pdf'), 'wb').write(sent[0])
    with db() as c:
        assert c.execute('SELECT COUNT(*) n FROM finance_entries').fetchone()['n'] == before_stmt  # read-only
    found, msg = fcs.find('عميل الكشف')
    assert found == (owner, cc, 'عميل الكشف'), msg
    assert 'أي عميل تقصد' in fcs.find('عميل')[1]

    for name in ('advance_settlement', 'customer_statement', 'finance_post', 'finance_overview', 'receivables_aging', 'finance_checks', 'finance_playbook'):
        assert name in command_agent.HANDLERS and name in virtual_office.DEPARTMENTS['finance']['tools']


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'finance_desk_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env):
            import app.main  # noqa: F401
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: finance desk — FIFO aging, monthly overview, control checks, 11 accounting playbooks; posting only after a full PDF preview (all-or-nothing), customer statement with proven allocation.')


if __name__ == '__main__':
    main()
