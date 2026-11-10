"""«سجل حسابات سلة من فسح»: list read → one detail read per unbilled import (no 10 cap) → ONE statement split
الياسمين / عمران / سلة الرحائب with ONE «نفذ». Isolated PostgreSQL; model and runner simulated; nothing recorded or sent."""
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
    from app.bootstrap import app  # noqa: F401
    from app import agent_runner, billing_rules, command_agent
    from app.team import ROLE
    from app.storage import db
    agent_runner.init(); billing_rules.init()
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ, consumed BOOLEAN NOT NULL DEFAULT FALSE)''')
    chat = patch('app.transport_desk.manager_chat', return_value=('966500000001', 'conv-m'))
    chat.start()
    # 1) The command reads import + export lists from a default «since», 20 pages, party سلة.
    token = ROLE.set({'name': 'محمد', 'manager': True})
    out = command_agent.tool_fasah_billing(None, {})
    ROLE.reset(token)
    with db() as c:
        tasks = [(r['kind'], json.loads(r['params_json'])) for r in c.execute('SELECT * FROM runner_tasks ORDER BY id').fetchall()]
    assert [t[1]['which'] for t in tasks] == ['import', 'export'] and all(t[1]['pages'] == 20 and t[1]['party'] == 'سلة' for t in tasks)
    assert 'الياسمين / عمران' in out and 'نفذ' in out
    # 2) A list with 12 unbilled سلة imports → 12 detail reads in one batch (the old cap was 10).
    rows = ''.join(f'2026110000{i:04d},4189{i:02d},0{1 + i % 9}/11/2026,سلة الرحائب تحت المعالجة\n' for i in range(12))
    with db() as c:
        c.execute("UPDATE runner_tasks SET status='done'")
        tid = c.execute("""INSERT INTO runner_tasks(kind,params_json,status,created_by,created_at)
            VALUES('fasah_declarations',%s,'done','محمد',NOW()) RETURNING id""", (json.dumps({'which': 'import', 'party': 'سلة'}),)).fetchone()['id']
        c.execute("INSERT INTO runner_files(task_id,name,mime,size,sha256,verified,data,created_at) VALUES(%s,'f.csv','text/csv',1,'x',TRUE,%s,NOW())",
                  (tid, ('﻿رقم المرجع,رقم البيان,التاريخ,التفاصيل\n' + rows).encode()))
    sent = []
    with patch.object(agent_runner, 'notify', side_effect=sent.append), patch('app.fasah_tracking.after_read', return_value=[]):
        agent_runner.after_fasah(tid)
    with db() as c:
        details = [json.loads(r['params_json']) for r in c.execute("SELECT params_json FROM runner_tasks WHERE kind='fasah_details'").fetchall()]
        batch = c.execute('SELECT * FROM fasah_billing_batches').fetchone()
    assert len(details) == 12 and batch['expected'] == 12 and all(d['batch'] == batch['id'] for d in details), (len(details), sent)
    assert 'كشفًا واحدًا' in sent[0]
    # 3) Detail results: Yasmen invoice, other supplier, one unreadable → nothing until the last; then ONE summary + ONE code.
    with patch.object(agent_runner, 'notify', side_effect=sent.append):
        for i, d in enumerate(details):
            n = d['number']
            if i == 11:
                assert 'الياسمين' in agent_runner.batch_add(batch['id'], n, None, 'تعذرت قراءة البيان على فسح')
            else:
                supplier = 'مؤسسة الياسمين' if i % 2 == 0 else 'Guangzhou Trading Co'
                res = agent_runner.batch_add(batch['id'], n, {'number': n, 'kind': 'import', 'party': 'سلة الرحائب', 'supplier': supplier,
                                                               'invoice_no': f'INV{i}', 'invoice_value': '10000', 'duty': '500', 'other': '0', 'date': '2026-11-02'}, '')
                assert res is None
        assert agent_runner.batch_add(batch['id'], details[0]['number'], None, 'x') is None  # already notified once
    summary = sent[-1]
    assert 'كشف الياسمين (مطالبة): 6 بيان' in summary and 'كشف عمران (مطالبة): 5 بيان' in summary, summary
    assert 'نصيب سلة الرحائب' in summary and 'لم تُقرأ' in summary and summary.count('نفذ ') == 1
    with db() as c:
        action = json.loads(c.execute('SELECT command FROM whatsapp_voice_pending ORDER BY expires_at DESC LIMIT 1').fetchone()['command'].partition(':')[2])
        recorded = c.execute('SELECT COUNT(*) n FROM billing_declarations').fetchone()['n']
    assert action['tool'] == 'record_billing' and len(action['items']) == 11 and recorded == 0
    # 3b) «نفذ» records the drafts AND returns the three statements; سلة الرحائب statement is its share, month defaults to now.
    from app import statement_import
    with patch.object(billing_rules, 'create_documents', return_value=[1]):
        token = ROLE.set({'name': 'محمد', 'manager': True})
        done = command_agent.execute_confirmed(None, json.dumps(action, ensure_ascii=False))
        ROLE.reset(token)
    assert 'كشوفات الحسابات بعد التسجيل' in done and 'كشف الياسمين — 2026-11' in done and 'كشف عمران — 2026-11' in done, done
    assert 'نصيب سلة الرحائب المستحق' in done, done
    salla = statement_import.statement('سلة الرحايب', '2026-11')
    assert salla['payable'] and len(salla['lines']) == 11 and abs(salla['total'] - 11 * 1050.0) < 0.01, salla['total']
    assert 'لا توجد بيانات مسجلة' in statement_import.statement_text('سلة', '2025-01')
    with patch('app.statement_import.all_statements', return_value='ALL') as every:
        assert command_agent.tool_party_statement(None, {}) == 'ALL' and every.call_args[0][0][0].count('-') == 1
    # 4) Owner rule: every successful FASAH status read prepares سلة accounts by itself — no command, no question.
    import datetime as dt
    with db() as c:
        c.execute("UPDATE runner_tasks SET status='done'")
        c.execute("DELETE FROM fasah_tracking_state WHERE key='auto_billing_at'")
        before = c.execute('SELECT COUNT(*) n FROM runner_tasks').fetchone()['n']
    listing = [{'رقم البيان': '777001', 'التاريخ': '05/11/2026', 'التفاصيل': 'سلة الرحائب تحت المعالجة'}]
    now = dt.datetime.now(dt.timezone.utc)
    text = agent_runner.auto_billing(listing, now)
    with db() as c:
        auto = [(r['created_by'], json.loads(r['params_json'])) for r in c.execute('SELECT * FROM runner_tasks WHERE id>%s ORDER BY id',
                (c.execute('SELECT MAX(id) m FROM runner_tasks').fetchone()['m'] - 2,)).fetchall()]
        after = c.execute('SELECT COUNT(*) n FROM runner_tasks').fetchone()['n']
    assert text and 'تلقائيًا' in text and after == before + 2, (text, before, after)
    assert [a[1]['which'] for a in auto] == ['import', 'export'] and all(a[1]['party'] == 'سلة' and a[1]['auto'] and a[1]['pages'] == 20 for a in auto)
    assert all(a[0].startswith('متابعة تلقائية') for a in auto)
    assert agent_runner.auto_billing(listing, now + dt.timedelta(hours=1)) is None      # still running / too soon
    with db() as c:
        c.execute("UPDATE runner_tasks SET status='done'")
    assert agent_runner.auto_billing(listing, now + dt.timedelta(hours=3)) is None      # under 6 hours
    assert agent_runner.auto_billing([], now + dt.timedelta(hours=7)) is None           # nothing unbilled, under a day
    with db() as c:
        assert c.execute('SELECT COUNT(*) n FROM runner_tasks').fetchone()['n'] == after
    assert agent_runner.auto_billing(listing, now + dt.timedelta(hours=7))              # unbilled seen again after 6h
    with db() as c:
        c.execute("UPDATE runner_tasks SET status='done'")
        n = c.execute('SELECT COUNT(*) n FROM runner_tasks').fetchone()['n']
    assert agent_runner.auto_billing([], now + dt.timedelta(hours=32)) is None          # daily sweep runs quietly
    with db() as c:
        assert c.execute('SELECT COUNT(*) n FROM runner_tasks').fetchone()['n'] == n + 2
    chat.stop()


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'fasah_bill_' + secrets.token_hex(5)
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
    print('PASS: سلة الرحائب billing from FASAH — all imports read, one statement الياسمين/عمران/سلة, one «نفذ», nothing recorded before it.')


if __name__ == '__main__':
    main()
