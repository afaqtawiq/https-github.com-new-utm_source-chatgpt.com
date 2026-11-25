"""Finance desk upgrade on isolated PostgreSQL with synthetic ledger data (finance_service, the real posting path).
Read-only analysis: aging (FIFO), monthly overview, control checks, accounting playbooks. Nothing posted by the desk."""
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

    def doc(party, kind, amount, day, posted=True, refs=True):
        seq[0] += 1
        did = ledger.create_document(form(owner_id=owner, counterparty_id=party, kind=kind, currency='SAR', amount=amount, document_date=day,
                                          source_ref='SRC', source_locator='LOC-' + str(seq[0]), economic_ref='EV-' + str(seq[0]),
                                          source_role='detail', amount_basis='gross', notes='',
                                          invoice_ref=('INV-' + str(seq[0])) if refs else '', customs_ref=('C-' + str(seq[0])) if refs else ''), actor)
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

    ck = fd.checks(as_of)
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

    from app import command_agent, virtual_office
    for name in ('finance_overview', 'receivables_aging', 'finance_checks', 'finance_playbook'):
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
    print('PASS: finance desk — FIFO aging, monthly overview, control checks, 11 accounting playbooks; nothing posted.')


if __name__ == '__main__':
    main()
