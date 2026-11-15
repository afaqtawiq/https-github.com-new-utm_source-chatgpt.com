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
    # 3c) The printable الياسمين statement shows every component of the claim; the WhatsApp link survives the space in «سلة الرحائب».
    with patch.object(billing_rules, 'admin_session', return_value={}):
        page = billing_rules.statement_page(None, 'الياسمين', '2026-11').body.decode()
    for head in ('نوع البيان', 'استيراد', 'رسوم جمركية', 'تخليص', 'سابر', 'زكاة', 'سجل تجاري', 'ضريبة القيمة المضافة', 'رقم الفاتورة'):
        assert head in page, head
    assert '1,450.00' in page and '300.00' in page and '250.00' in page and '500.00' in page and 'INV0' in page, page[:600]
    link = statement_import.statement_link('سلة الرحائب', '2026-11')
    assert ' ' not in link and link.index('month=2026-11') < link.index('party=')
    # 3d) A failed details read is retried twice before it is reported in the batch; the reason reaches the summary.
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    client = TestClient(app)
    with db() as c:
        c.execute("UPDATE runner_tasks SET status='done'")
        did = c.execute("INSERT INTO runner_devices(name,token_hash,created_at) VALUES('pc',%s,NOW()) RETURNING id",
                        (agent_runner.token_hash('tok'),)).fetchone()['id']
        bid = c.execute('INSERT INTO fasah_billing_batches(expected,created_at) VALUES(1,NOW()) RETURNING id').fetchone()['id']
        tid = c.execute("""INSERT INTO runner_tasks(kind,params_json,status,device_id,created_by,created_at,started_at)
            VALUES('fasah_details',%s,'running',%s,'تلقائي',NOW(),NOW()) RETURNING id""",
                        (json.dumps({'which': 'import', 'number': '555001', 'batch': bid}), did)).fetchone()['id']
    seen = []
    with patch.object(agent_runner, 'notify', side_effect=seen.append):
        for attempt in range(3):
            r = client.post(f'/api/runner/tasks/{tid}/finish', json={'status': 'failed', 'result': {'error': 'لم أجد البيان 555001 في القائمة'}},
                            headers={'X-Runner-Token': 'tok'})
            assert r.status_code == 200, r.text
            with db() as c:
                nxt = c.execute("SELECT id,params_json FROM runner_tasks WHERE status='queued' AND kind='fasah_details' ORDER BY id DESC LIMIT 1").fetchone()
            if attempt < 2:
                assert nxt and json.loads(nxt['params_json'])['retry'] == attempt + 1, (attempt, nxt)
                with db() as c:
                    c.execute("UPDATE runner_tasks SET status='running',device_id=%s,started_at=NOW() WHERE id=%s", (did, nxt['id']))
                tid = nxt['id']
            else:
                assert not nxt
        import time
        for _ in range(40):
            if seen:
                break
            time.sleep(0.1)
    assert seen and 'لم أجد البيان 555001' in seen[-1], seen
    assert any('555001' in line and 'لم أجد البيان' in line for line in agent_runner.recent_failures())
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
    # FASAH export dates must survive both list entry points and confirmation.
    export_rows = [
        ('910001', '31/10/2026'), ('910002', '02/11/2026'),
        ('910003', ''), ('910004', '31/11/2026'),
        ('910005', '02/11/2026'), ('910005', '03/11/2026'),
        ('910001', '31/10/2026'),
    ]
    export_csv = ('رقم المرجع,رقم البيان,التاريخ,التفاصيل\n' + ''.join(
        f'2026121000{i:04d},{number},{day},إعادة تصدير سلة الرحائب\n'
        for i, (number, day) in enumerate(export_rows))).encode()
    for auto in (False, True):
        with db() as c:
            export_tid = c.execute("""INSERT INTO runner_tasks(kind,params_json,status,created_by,created_at)
                VALUES('fasah_declarations',%s,'done','محمد',NOW()) RETURNING id""",
                (json.dumps({'which': 'export', 'party': 'سلة', 'auto': auto}),)).fetchone()['id']
            c.execute("""INSERT INTO runner_files(task_id,name,mime,size,sha256,verified,data,created_at)
                VALUES(%s,'export.csv','text/csv',1,'test-export',TRUE,%s,NOW())""", (export_tid, export_csv))
        with patch.object(agent_runner, 'notify') as export_notice, patch('app.fasah_tracking.after_read', return_value=[]):
            agent_runner.after_fasah(export_tid)
        preview = export_notice.call_args.args[0]
        assert preview.count('نفذ ') == 1 and 'لم يُجهّز للتسجيل' in preview, preview
        assert all(number in preview for number in ('910003', '910004', '910005')), preview
        pending_token = preview.split('نفذ ', 1)[1].splitlines()[0].strip()
        with db() as c:
            pending = c.execute('SELECT command FROM whatsapp_voice_pending WHERE token=%s', (pending_token,)).fetchone()
            assert c.execute("SELECT COUNT(*) n FROM billing_declarations WHERE kind='export'").fetchone()['n'] == 0
        export_action = json.loads(pending['command'].partition(':')[2])
        assert [(d['number'], d['date']) for d in export_action['items']] == [
            ('910001', '2026-10-31'), ('910002', '2026-11-02')], export_action
    token = ROLE.set({'name': 'محمد', 'manager': True})
    try:
        # A code prepared by the old version without a valid export date must not book.
        stale_action = {'tool': 'record_billing', 'items': [
            {'kind': 'export', 'party': 'سلة الرحائب', 'number': '910006'},
            {'kind': 'export', 'party': 'سلة الرحائب', 'number': '910007', 'date': '30/02/2026'},
        ]}
        with patch.object(billing_rules, 'create_documents', return_value=[1]) as drafts:
            rejected = command_agent.execute_confirmed(None, json.dumps(stale_action, ensure_ascii=False))
            drafts.assert_not_called()
            assert 'لم تُنشأ مسودات جديدة' in rejected, rejected
            done = command_agent.execute_confirmed(None, json.dumps(export_action, ensure_ascii=False))
            assert 'كشف سلة الرحائب — 2026-10' in done and 'كشف سلة الرحائب — 2026-11' in done, done
            assert [call.args[0]['date'] for call in drafts.call_args_list] == [
                dt.date(2026, 10, 31), dt.date(2026, 11, 2)]
            repeated = command_agent.execute_confirmed(None, json.dumps(export_action, ensure_ascii=False))
            assert drafts.call_count == 2 and 'لم تُنشأ مسودات جديدة' in repeated, repeated
    finally:
        ROLE.reset(token)
    with db() as c:
        exports = c.execute("SELECT number,decl_date FROM billing_declarations WHERE kind='export' ORDER BY number").fetchall()
    assert [(r['number'], r['decl_date']) for r in exports] == [
        ('910001', dt.date(2026, 10, 31)), ('910002', dt.date(2026, 11, 2))]
    assert '910001' in {r['number'] for r in statement_import.statement(billing_rules.SALLA, '2026-10')['lines']}
    nov_numbers = {r['number'] for r in statement_import.statement(billing_rules.SALLA, '2026-11')['lines']}
    assert '910002' in nov_numbers and '910001' not in nov_numbers
    # A real first draft must remain linked if the second finance write fails.
    from app import finance_service
    from app.prospect_autopilot import system_user
    actor = system_user()
    finance_service.create_party({'name': 'Fixture owner', 'identity_ref': 'fixture-billing-owner',
                                  'kind': 'owner', 'confirmed': '1'}, actor)
    real_create = finance_service.create_document
    action = {'tool': 'record_billing', 'label': 'اختبار إنشاء المسودات', 'items': [
        {'number': '910010', 'kind': 'import', 'party': billing_rules.SALLA,
         'date': '2026-11-14', 'supplier': 'Fixture manufacturer', 'invoice_value': '10000'}
    ]}

    def fail_second(form, actor):
        if form['kind'] == 'payable':
            raise RuntimeError('fixture raw provider error')
        return real_create(form, actor)

    token = ROLE.set({'name': 'محمد', 'manager': True})
    try:
        payload = json.dumps(action, ensure_ascii=False)
        with patch.object(finance_service, 'create_document', side_effect=fail_second) as creator:
            failed = command_agent.execute_confirmed(None, payload)
            assert 'لم يكتمل تسجيل أي بيان' in failed and 'المسودات التي أُنشئت: 1' in failed, failed
            assert 'fixture raw provider error' not in failed and 'كشوفات الحسابات بعد التسجيل' not in failed
            assert creator.call_count == 2
            repeated = command_agent.execute_confirmed(None, payload)
            assert 'لم يكتمل تسجيل أي بيان' in repeated and creator.call_count == 2, repeated
        uploaded = statement_import.record_all(action['items'], actor)
        assert 'فوترة غير مكتملة: 1' in uploaded and 'مسجل مسبقًا ولم يتكرر' not in uploaded, uploaded
    finally:
        ROLE.reset(token)
    with db() as c:
        billing = c.execute("SELECT * FROM billing_declarations WHERE number='910010'").fetchone()
        finance = c.execute("SELECT id,kind,status FROM finance_documents WHERE customs_ref='910010'").fetchall()
        assert [(r['kind'], r['status']) for r in finance] == [('claim', 'draft')]
        assert billing['status'] == 'incomplete' and json.loads(billing['finance_ids']) == [finance[0]['id']]
        assert 'fixture raw provider error' not in billing['error']
        assert not c.execute('SELECT 1 FROM finance_entries WHERE document_id=%s', (finance[0]['id'],)).fetchone()
    try:
        billing_rules.void(billing['id'], actor)
        raise AssertionError('Incomplete declaration unexpectedly cleared for replay')
    except ValueError as exc:
        assert 'غير المكتمل' in str(exc)
    with patch.object(billing_rules, 'admin_session'):
        page = billing_rules.page(None).body.decode()
        printable = billing_rules.statement_page(None, billing_rules.SALLA, '2026-11').body.decode()
    assert 'مبالغ محسوبة لم يكتمل تسجيلها' in page and 'fixture raw provider error' not in page
    assert f'/finance/documents/{finance[0]["id"]}' in page and f'/billing/{billing["id"]}/void' not in page
    assert 'لم يدخل في حساب القاعدة' in printable
    for party in (billing_rules.SALLA, billing_rules.OMRAN):
        statement = statement_import.statement(party, '2026-11')
        assert statement['incomplete_count'] == 1 and '910010' not in {l['number'] for l in statement['lines']}
    assert statement_import.statement(billing_rules.YASMEN, '2026-11')['incomplete_count'] == 0

    # An unhandled interruption before the final status leaves a visible, non-replayed drafting row.
    interrupted = {**action['items'][0], 'number': '910011', 'date': dt.date(2026, 11, 14)}
    class SimulatedInterruption(BaseException):
        pass
    def interrupt_second(form, actor):
        if form['kind'] == 'payable':
            raise SimulatedInterruption()
        return real_create(form, actor)
    try:
        with patch.object(finance_service, 'create_document', side_effect=interrupt_second):
            billing_rules.record(interrupted, actor)
        raise AssertionError('Interruption was not simulated')
    except SimulatedInterruption:
        pass
    with db() as c:
        stale = c.execute("SELECT status,finance_ids FROM billing_declarations WHERE number='910011'").fetchone()
        assert stale['status'] == 'drafting' and len(json.loads(stale['finance_ids'])) == 1
        tid = c.execute("""INSERT INTO runner_tasks(kind,params_json,status,created_by,created_at)
            VALUES('fasah_declarations',%s,'done','Fixture',NOW()) RETURNING id""",
            (json.dumps({'which': 'import', 'party': 'سلة'}),)).fetchone()['id']
        review_csv = ('رقم المرجع,رقم البيان,التاريخ,التفاصيل\n'
                      '202612120001,910010,14/11/2026,سلة الرحائب تحت المعالجة\n'
                      '202612120002,910011,14/11/2026,سلة الرحائب تحت المعالجة\n').encode()
        c.execute("""INSERT INTO runner_files(task_id,name,mime,size,sha256,verified,data,created_at)
            VALUES(%s,'review.csv','text/csv',1,'test-incomplete',TRUE,%s,NOW())""", (tid, review_csv))
    with patch.object(agent_runner, 'notify') as notice, patch('app.fasah_tracking.after_read', return_value=[]):
        with patch.object(agent_runner, 'prepare_billing') as prepare, patch.object(agent_runner, 'create_task') as enqueue:
            agent_runner.after_fasah(tid)
            prepare.assert_not_called()
            enqueue.assert_not_called()
        preview = notice.call_args.args[0]
    assert '910010' in preview and '910011' in preview and 'لم تُعد المحاولة تلقائيًا' in preview, preview
    assert 'كل بيانات' not in preview and 'نفذ' not in preview, preview
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
