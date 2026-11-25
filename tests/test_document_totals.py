"""«جمع لي المبالغ في الإيصالات والفواتير واخصمها من 41 ألف» (owner, 25 Nov 2026) — on the test database, model replies
cached on each file (no network). Nothing is recorded in finance."""
import json
import os
from unittest.mock import patch

import pytest

if not os.environ.get('DATABASE_URL'):
    pytest.skip('needs the disposable test database', allow_module_level=True)

from app import document_totals as dt_, staff_documents
from app.storage import db

OWNER = '966507665873'


def add(name, data, check, sender=OWNER):
    staff_documents.init()
    with db() as c:
        return c.execute('''INSERT INTO staff_documents(sender,filename,mime,data,fields,created_at)
            VALUES(%s,%s,'application/pdf',%s,%s,NOW()) RETURNING id''',
                         (sender, name, data, json.dumps({'amount_check': check}, ensure_ascii=False))).fetchone()['id']


@pytest.fixture(autouse=True)
def clean():
    staff_documents.init()
    with db() as c:
        c.execute('DELETE FROM staff_documents')
    yield


def chk(kind, issuer, ref, amount, currency='SAR'):
    return {'kind': kind, 'issuer': issuer, 'reference': ref, 'date': '25/11/2026', 'amount': amount, 'currency': currency, 'note': ''}


def test_parse_amount():
    assert dt_.parse_amount('41 الف') == 41000 and dt_.parse_amount('٤١ألف') == 41000
    assert dt_.parse_amount('41,000') == 41000 and dt_.parse_amount('41000') == 41000 and dt_.parse_amount('') is None


def test_total_and_remainder_with_everything_doubtful_listed_apart():
    add('nct.pdf', b'%PDF-1', chk('service_invoice', 'NATIONAL CONTAINER TERMINALS', '478529', 1891.0))
    add('msc.pdf', b'%PDF-2', chk('service_invoice', 'MSC', '9001', 12650.5))
    add('sadad.jpg', b'\xff\xd8\xff-3', chk('payment_receipt', 'سداد', '77001', 18000))
    add('sadad-again.jpg', b'\xff\xd8\xff-3', chk('payment_receipt', 'سداد', '77001', 18000))      # same file twice
    add('supplier.pdf', b'%PDF-5', chk('goods_invoice', 'Ningbo Supplier', 'PI-1', 54000))           # goods value
    add('blur.jpg', b'\xff\xd8\xff-6', chk('payment_receipt', '', '', None))                       # unreadable
    add('aed.pdf', b'%PDF-7', chk('service_invoice', 'Dubai Transport', 'D-9', 4200, 'AED'))         # other currency
    add('other-person.pdf', b'%PDF-8', chk('service_invoice', 'X', '1', 999999), sender='966500000001')
    out = dt_.run(OWNER, 41000)
    assert 'الإجمالي: 32,541.5 ريال' in out and 'المستلم: 41,000 ريال' in out and '✅ الباقي: 8,458.5 ريال' in out
    assert '(3 محسوب من 7 ملف)' in out and 'NATIONAL CONTAINER TERMINALS — رقم 478529' in out
    assert 'مكرر' in out and 'فاتورة بضاعة من المورد' in out and 'ما قدرت أقرأ المبلغ' in out and 'AED' in out
    assert '999,999' not in out and 'لم يُسجَّل شيء في الحسابات' in out


def test_over_spend_and_last_n_files():
    add('a.pdf', b'%PDF-a', chk('service_invoice', 'A', '1', 30000))
    add('b.pdf', b'%PDF-b', chk('service_invoice', 'B', '2', 15000))
    out = dt_.run(OWNER, 41000)
    assert '⚠️ تجاوز المستلم بـ: 4,000 ريال' in out
    assert 'الإجمالي: 15,000 ريال' in dt_.run(OWNER, None, count=1)


def test_reads_each_file_alone_and_caches():
    add('x.pdf', b'%PDF-x', None)
    with db() as c:
        c.execute("UPDATE staff_documents SET fields='{}'")
    calls = []

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {'content': [{'type': 'text', 'text': '{"kind":"payment_receipt","issuer":"بنك","reference":"55","amount":"1,250.75","currency":"SAR"}'}]}

    class Client:
        def __init__(self, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append(json)
            return R()
    with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k'}), patch.object(dt_.httpx, 'AsyncClient', Client):
        first = dt_.run(OWNER, 41000)
        second = dt_.run(OWNER, 41000)
    assert 'الإجمالي: 1,250.75 ريال' in first and first == second and len(calls) == 1   # cached on the file
    assert len([b for b in calls[0]['messages'][0]['content'] if b.get('type') == 'document']) <= 1


def test_tool_is_wired_for_the_gm_and_finance():
    from app import command_agent, virtual_office
    assert 'documents_total' in command_agent.HANDLERS and 'documents_total' in virtual_office.DEPARTMENTS['finance']['tools']
    tok = command_agent.CHAT.set((OWNER, 'conv'))
    try:
        add('nct.pdf', b'%PDF-1', chk('service_invoice', 'NCT', '478529', 1891.0))
        assert '✅ الباقي: 39,109 ريال' in command_agent.tool_documents_total(None, {'received': '41 الف'})
    finally:
        command_agent.CHAT.reset(tok)
