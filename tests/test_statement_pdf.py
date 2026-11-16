import asyncio
import os
import pathlib

import pytest

os.environ.setdefault('DATABASE_URL', 'postgresql://unused@localhost/unused')
pytest.importorskip('reportlab')
if not pathlib.Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf').is_file():
    pytest.skip('Arabic PDF font is not installed', allow_module_level=True)

from app import statement_pdf  # noqa: E402

STATEMENT = {'party': 'الياسمين', 'month': '2026-11', 'payable': False, 'total': 8299.53, 'paid': 1000.0,
             'payments': [{'pay_date': '2026-11-05', 'amount': 1000, 'ref': 'x'}],
             'lines': [{'number': '417967', 'date': '2026-11-01', 'type': 'استيراد', 'invoice_no': 'AB-584', 'invoice': '7000',
                        'fees': 449.53, 'clearance': '300.00', 'saber': '1450.00', 'zakat': '175.00', 'registry': '700.00',
                        'tax': '1050.00', 'amount': 4124.53}] + [
                       {'number': str(408951 + i), 'date': '2026-11-02', 'type': 'استيراد', 'invoice_no': f'AB-{583 + i}', 'invoice': '6500',
                        'fees': 587, 'clearance': '300', 'saber': '1450', 'zakat': '163', 'registry': '700', 'tax': '975', 'amount': 4175.0}
                       for i in range(40)]}


def test_pdf_is_valid_multi_page_and_named():
    data = statement_pdf.build(STATEMENT)
    assert data.startswith(b'%PDF-') and b'%%EOF' in data[-1024:] and data.count(b'/Type /Page') >= 2 and len(data) < 2_000_000
    assert statement_pdf.filename(STATEMENT) == 'Afaq-Statement-Yasmen-2026-11.pdf'
    share = dict(STATEMENT, party='سلة الرحائب', payable=True, lines=[{'number': '206826', 'date': '2026-11-02',
                 'type': 'تصدير / إعادة تصدير', 'amount': 100.0}], total=100.0, paid=0, payments=[])
    assert statement_pdf.build(share).startswith(b'%PDF-') and statement_pdf.filename(share).endswith('Salla-2026-11.pdf')


def test_sent_only_to_the_requesters_chat(monkeypatch):
    from app import zernio_whatsapp as z
    calls = []

    async def fake(recipient, content, filename, caption='', *, expected_account, expected_conversation, idempotency_key):
        assert z._dispatch_guard.get() is not None
        calls.append((recipient, filename, expected_conversation, idempotency_key, content[:5], caption))
        return {'status': 'sent', 'provider_ids': ['1']}
    monkeypatch.setattr(z, 'send_document', fake)
    monkeypatch.setattr(z, 'account_id', lambda: 'acc')
    sent, failed = statement_pdf.send_to_requester(('966500000001', 'conv-1'), [STATEMENT, dict(STATEMENT, lines=[])])
    assert sent == ['الياسمين'] and failed == [] and len(calls) == 1
    recipient, name, conv, key, head, caption = calls[0]
    assert recipient == '966500000001' and conv == 'conv-1' and name.endswith('.pdf') and head == b'%PDF-'
    assert key.startswith('wa-document-') and len(key) == 12 + 64 and '8,299.53' in caption

    async def boom(*a, **k):
        raise z.WhatsAppBlocked('نافذة الرد مغلقة')
    monkeypatch.setattr(z, 'send_document', boom)
    assert statement_pdf.send_to_requester(('966500000001', 'conv-1'), [STATEMENT]) == ([], ['الياسمين'])
