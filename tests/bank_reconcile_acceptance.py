"""Bank statement reconciliation on local PostgreSQL. No AI key, nothing posted: matching proposes, «نفذ» records drafts once."""
import json
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    from app import bank_reconcile as br, statement_import as si
    from app.storage import db
    br.init(); si.init_payments()
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ, consumed BOOLEAN NOT NULL DEFAULT FALSE)''')
    parties = [{'id': 1, 'name': 'مؤسسة الياسمين التجارية', 'receivable_minor': 500000},
               {'id': 2, 'name': 'شركة النخبة للاستيراد', 'receivable_minor': 1234550},
               {'id': 3, 'name': 'مؤسسة الفجر', 'receivable_minor': 990000}]
    recorded = []
    with patch('app.collections_desk.balances', return_value=parties), \
         patch('app.transport_desk.manager_chat', return_value=('966500000001', 'conv-manager')), \
         patch('app.collections_desk.record_payment', side_effect=lambda n, a, actor, date=None, ref='': recorded.append((n, a)) or 'ok'):
        assert br.is_bank('كشف حساب البنك اكتوبر') and br.is_bank('statement.xlsx الراجحي') and not br.is_bank('كشف عمران')
        lines = [{'date': '2026-11-02', 'amount': '20,000', 'description': 'حوالة واردة من مؤسسة الياسمين', 'ref': 'TRX1'},
                 {'date': '2026-11-03', 'amount': 12345.5, 'description': 'IBAN SA00 transfer', 'ref': 'TRX2'},
                 {'date': '03/11/2026', 'amount': 777, 'description': 'إيداع نقدي', 'ref': ''},
                 {'date': '2026-11-04', 'amount': 3000, 'description': 'تحويل من النخبة', 'ref': 'TRX4'},
                 {'date': '2026-11-04', 'amount': 0, 'description': 'رسوم', 'ref': ''}]
        with db() as c:
            reply, batch = br.prepare(c, lines, 'المدير')
        assert 'طابقت 3 حوالة' in reply and '35,345.50' in reply, reply
        assert 'بالمبلغ = الرصيد المستحق' in reply and 'بدون مطابقة 1' in reply and 'نفذ ' in reply
        with db() as c:
            action = json.loads(c.execute('SELECT command FROM whatsapp_voice_pending').fetchone()['command'].partition(':')[2])
        assert action == {'tool': 'record_bank_payments', 'batch': batch}
        assert not recorded  # nothing recorded before «نفذ»
        out = br.record(batch)
        assert len(recorded) == 3 and 'مسودات' in out, (recorded, out)
        assert 'سُجلت مسبقًا' in br.record(batch) and len(recorded) == 3
        # Same statement again → all three are duplicates now.
        with db() as c:
            reply2, _ = br.prepare(c, lines, 'المدير')
        assert 'مسجلة مسبقًا وتجاهلتها: 3' in reply2 and 'لا توجد حوالات مطابقة' in reply2, reply2


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'bank_rec_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: bank statement matched by name/amount; recorded once only after «نفذ»; duplicates skipped.')


if __name__ == '__main__':
    main()
