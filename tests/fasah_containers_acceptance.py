"""FASAH → containers: list read → details reads → bill, containers (check-digit validated), agent, arrival →
container desk, with an ESTIMATED last free day from the agent free days; one summary; quiet auto sweeps.
Isolated PostgreSQL; model and work computer simulated; nothing sent."""
import datetime as dt
import json
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def valid(prefix, digits):
    from app.fasah_containers import check_digit_ok
    for d in range(10):
        if check_digit_ok(f'{prefix}{digits}{d}'):
            return f'{prefix}{digits}{d}'


def run():
    from app.bootstrap import app  # noqa: F401
    from app import agent_runner, command_agent, container_returns, fasah_containers, line_desk
    from app.storage import db
    from app.team import ROLE
    agent_runner.init(); fasah_containers.init()
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ, consumed BOOLEAN NOT NULL DEFAULT FALSE)''')
    chat = patch('app.transport_desk.manager_chat', return_value=('966500000001', 'conv-m'))
    chat.start()
    assert fasah_containers.check_digit_ok('CSQU3054383') and not fasah_containers.check_digit_ok('CSQU3054384')
    a, b, x = valid('MSCU', '123456'), valid('MSCU', '654321'), valid('HLXU', '111222')
    assert '✅ أيام السماح' in line_desk.set_tariff({'agent': 'MSC', 'free_days': '١٤'})

    # 1) Manager command → read-only list task with purpose=containers.
    token = ROLE.set({'name': 'محمد', 'manager': True})
    out = command_agent.tool_fasah_containers(None, {})
    ROLE.reset(token)
    with db() as c:
        task = c.execute("SELECT * FROM runner_tasks WHERE kind='fasah_declarations' ORDER BY id DESC LIMIT 1").fetchone()
    params = json.loads(task['params_json'])
    assert params['purpose'] == 'containers' and params['which'] == 'import' and 'قراءة فقط' in out

    # 2) List read: 3 import declarations (one cancelled) → 2 details reads queued; nothing per-task to the manager.
    rows = [{'رقم البيان': '418801', 'التاريخ': '01/11/2026', 'التفاصيل': 'شركة الحياة تحت المعالجة'},
            {'رقم البيان': '418802', 'التاريخ': '02/11/2026', 'التفاصيل': 'مؤسسة النور جاهز لطباعة اشعار الفسح'},
            {'رقم البيان': '418803', 'التاريخ': '03/11/2026', 'التفاصيل': 'ملغي'}]
    msg = fasah_containers.after_list(task, rows)
    with db() as c:
        details = [json.loads(r['params_json']) for r in c.execute("SELECT params_json FROM runner_tasks WHERE kind='fasah_details' ORDER BY id").fetchall()]
        actors = {r['created_by'] for r in c.execute("SELECT created_by FROM runner_tasks WHERE kind='fasah_details'").fetchall()}
    assert [d['number'] for d in details] == ['418801', '418802'] and all(d['purpose'] == 'containers' for d in details), details
    assert all(x_.startswith('متابعة تلقائية') for x_ in actors) and '2 بيان' in msg
    assert fasah_containers.queue(['418801'])[1] == []  # queued already → not read twice

    # 3) Details: first has 2 containers (MSC named in FASAH, arrival → estimated free day); a fake number is ignored.
    text1 = f'رقم البيان 418801\nرقم بوليصة الشحن MEDU7788990\nالحاويات: {a} 40 قدم، {b} 20 قدم، ABCU1234561\nمنفذ الوصول: ميناء جدة الإسلامي'
    model1 = {'bill_of_lading': 'MEDU7788990', 'containers': [{'number': a, 'size': '40'}, {'number': b, 'size': '20'},
              {'number': 'ABCU1234569'}], 'port': 'ميناء جدة الإسلامي', 'shipping_agent': 'MSC', 'arrival_date': '2026-11-05',
              'importer': 'شركة الحياة', 'vessel': 'MSC ANNA'}
    with patch.object(fasah_containers, 'extract', return_value=model1):
        assert fasah_containers.after_details({}, details[0], text1) is None  # waits for the second
    with db() as c:
        ra = c.execute('SELECT * FROM container_returns WHERE container=%s', (a,)).fetchone()
        msc = c.execute("SELECT id FROM shipping_agents WHERE name='MSC'").fetchone()['id']
        fake = c.execute("SELECT 1 FROM container_returns WHERE container LIKE 'ABCU%%'").fetchone()
    assert ra['bill'] == 'MEDU7788990' and ra['customer'] == 'شركة الحياة' and ra['agent_id'] == msc and ra['size'] == '40'
    assert ra['free_until'] == dt.date(2026, 11, 18) and ra['free_until_estimated'] and ra['fasah_number'] == '418801' and not fake
    assert 'تقديري' in container_returns.card(ra)

    # 4) Second details: Hapag container in Jeddah, unknown free days; then ONE summary for the sweep.
    model2 = {'bill_of_lading': 'HLCUJED123456', 'containers': [x], 'port': 'Jeddah Islamic Port', 'shipping_agent': None,
              'arrival_date': None, 'importer': 'مؤسسة النور'}
    with patch.object(fasah_containers, 'extract', return_value=model2):
        summary = fasah_containers.after_details({}, details[1], f'B/L HLCUJED123456 container {x}')
    assert summary and '3 حاوية جديدة' in summary and 'MEDU7788990' in summary and 'Hapag-Lloyd' in summary, summary
    assert 'بدون آخر يوم مجاني' in summary and x in summary and 'أيام السماح' in summary and 'تقديري' in summary

    # 5) The team confirms the real date → no longer estimated; the team's customer is never overwritten by FASAH.
    container_returns.track({'container': a, 'free_until': '2026-11-20', 'customer': 'الحياة (عميل)'}, 'محمد')
    with db() as c:
        c.execute("UPDATE fasah_container_reads SET status='failed' WHERE number='418801'")
    with patch.object(fasah_containers, 'extract', return_value=model1):
        fasah_containers.queue(['418801'])
        fasah_containers.after_details({}, {'number': '418801'}, text1)
    with db() as c:
        ra = c.execute('SELECT * FROM container_returns WHERE container=%s', (a,)).fetchone()
    assert ra['free_until'] == dt.date(2026, 11, 20) and not ra['free_until_estimated'] and ra['customer'] == 'الحياة (عميل)'

    # 6) Outside Jeddah → recorded, no container; automatic sweeps stay quiet without new containers.
    with patch.object(agent_runner, 'create_task', return_value=(999, '')):
        sid, todo = fasah_containers.queue(['500001'], auto=True)
    with patch.object(fasah_containers, 'extract', return_value={'containers': [{'number': valid('MSCU', '999888')}], 'port': 'ميناء الملك عبدالعزيز بالدمام'}):
        assert fasah_containers.after_details({}, {'number': '500001', 'sweep': sid}, 'x') is None
    with db() as c:
        assert 'خارج ميناء جدة' in c.execute("SELECT message FROM fasah_container_reads WHERE number='500001'").fetchone()['message']

    # 7) A failed details read still completes the sweep summary.
    with patch.object(agent_runner, 'create_task', return_value=(1000, '')):
        sid, _ = fasah_containers.queue(['600001'])
    assert fasah_containers.details_failed({'number': '600001', 'sweep': sid}) is not None
    chat.stop()


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'fasah_cont_' + secrets.token_hex(5)
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
    print('PASS: FASAH containers — bills/containers/agent/arrival into the container desk, estimated free day, one summary, nothing sent.')


if __name__ == '__main__':
    main()
