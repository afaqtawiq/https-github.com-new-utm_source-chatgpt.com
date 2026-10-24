"""Command agent tools on local PostgreSQL with a scripted model. No network, no real sends."""
import json
import os
import secrets
import socket
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def scripted(*turns):
    """Each turn: list of (tool, input) or a final text."""
    calls = []
    def fake(messages, system):
        calls.append(messages)
        turn = turns[len(calls) - 1]
        if isinstance(turn, str):
            return {'content': [{'type': 'text', 'text': turn}]}
        return {'content': [{'type': 'tool_use', 'id': f't{len(calls)}{i}', 'name': n, 'input': a} for i, (n, a) in enumerate(turn)]}
    return fake, calls


def run():
    import app.afaq_only  # noqa: F401  production wiring
    from app import command_agent as ca, whatsapp_admin as admin
    from app.team import ROLE
    from app.storage import db, one, rows, utcnow
    with db() as c:
        admin.ensure_admin(c)
        c.execute("INSERT INTO users(email,name,password_hash,role,created_at) VALUES('cmd@fixture.invalid','a','x','admin',%s)", (utcnow(),))
        c.execute("""INSERT INTO customs_declarations(customer_name,bill_number,stage,created_by,created_at,updated_at)
            VALUES('Fixture Foods','MSKU7654321','submitted',1,NOW(),NOW())""")
    manager, staff = {'name': 'محمد', 'manager': True}, {'name': 'ناصر', 'manager': False}

    def run_as(member, text, model):
        r, t = ROLE.set(member), ca.CHAT.set(('966500000001', 'private-1'))
        try:
            with db() as c, patch.object(ca, 'call_model', model):
                return ca.run_agent(c, text)
        finally:
            ROLE.reset(r); ca.CHAT.reset(t)

    model, calls = scripted([('add_customer', {'name': 'شركة الاختبار', 'phone': '0500000999', 'city': 'جدة'}),
                             ('update_declaration', {'find': 'MSKU7654321', 'stage': 'released', 'declaration_number': '2026-555'})],
                            'تمت إضافة العميل وتحديث البيان.')
    reply = run_as(staff, 'ضيف عميل شركة الاختبار جواله 0500000999 من جدة وحدث بيان MSKU7654321 تم الفسح رقم 2026-555', model)
    assert reply == 'تمت إضافة العميل وتحديث البيان.'
    results = {r['tool_use_id']: r['content'] for r in calls[1][-1]['content']}
    assert any('تمت إضافة العميل' in v for v in results.values()) and any('تم الفسح' in v for v in results.values()), results
    assert one("SELECT phone FROM accounts WHERE name='شركة الاختبار'")['phone'] == '+966500000999'
    d = one("SELECT * FROM customs_declarations WHERE bill_number='MSKU7654321'")
    assert d['stage'] == 'released' and d['declaration_number'] == '2026-555'
    assert one('SELECT customer_message FROM customs_declaration_events WHERE declaration_id=? ORDER BY id DESC LIMIT 1', (d['id'],))['customer_message']
    print('PASS: internal writes run directly through tools.')

    model, calls = scripted([('add_customer', {'name': 'شركة الاختبار', 'phone': '0500000999'})], 'موجود مسبقًا.')
    run_as(staff, 'ضيف شركة الاختبار 0500000999', model)
    assert one("SELECT COUNT(*) n FROM accounts WHERE name='شركة الاختبار'")['n'] == 1
    print('PASS: duplicates refused.')

    sent = []
    model, calls = scripted([('send_whatsapp', {'to': '0500000123', 'text': 'شحنتك وصلت ميناء جدة'})], 'جاهزة، اكتب نفذ مع الرمز.')
    with patch('app.manager_actions.deliver', side_effect=lambda n, t: sent.append((n, t)) or {'ok': True}):
        run_as(manager, 'ارسل للعميل 0500000123 ان شحنته وصلت', model)
        assert not sent
        pending = one("SELECT * FROM whatsapp_voice_pending WHERE command LIKE '__agent_action__:%%' ORDER BY expires_at DESC LIMIT 1")
        assert pending and pending['conversation_id'] == 'private-1'
        r, t = ROLE.set(staff), ca.CHAT.set(('966500000001', 'private-1'))
        try:
            with db() as c:
                assert 'المدير' in admin.run_command(c, pending['command'], 'e1') and not sent
        finally:
            ROLE.reset(r); ca.CHAT.reset(t)
        r = ROLE.set(manager)
        try:
            with db() as c:
                out = admin.run_command(c, pending['command'], 'e2')
        finally:
            ROLE.reset(r)
    assert sent and sent[0][0].endswith('966500000123') and 'شحنتك وصلت' in sent[0][1], (out, sent)
    print('PASS: external sends wait for the manager confirmation code.')

    model, calls = scripted([('send_whatsapp', {'to': '0500000123', 'text': 'كلمة السر 1234'})], 'لا يمكن.')
    run_as(manager, 'ارسل كلمة السر', model)
    assert 'لا أرسل كلمات مرور' in calls[1][-1]['content'][0]['content']
    print('PASS: secrets are never sent.')

    model, calls = scripted([('list_recent', {'kind': 'declarations'})], 'هذه البيانات.')
    run_as(staff, 'وريني البيانات المفتوحة', model)
    assert 'Fixture Foods' in calls[1][-1]['content'][0]['content']
    print('PASS: read tools.')

    from app.team import team
    model, calls = scripted([('add_employee', {'name': 'ابو تميم فارس', 'phone': '0509666097', 'title': 'مندوب'})], 'جاهز.')
    run_as(staff, 'ضيف موظف ابو تميم فارس 0509666097', model)
    assert 'للمدير فقط' in calls[1][-1]['content'][0]['content'] and '966509666097' not in team()
    model, calls = scripted([('add_employee', {'name': 'ابو تميم فارس', 'phone': '0509666097', 'title': 'مندوب'})], 'جاهز.')
    run_as(manager, 'ضيف موظف ابو تميم فارس 0509666097', model)
    assert '966509666097' not in team()
    pending = one("SELECT * FROM whatsapp_voice_pending WHERE command LIKE '%%add_employee%%' ORDER BY expires_at DESC LIMIT 1")
    r = ROLE.set(manager)
    try:
        with db() as c:
            out = admin.run_command(c, pending['command'], 'e5')
    finally:
        ROLE.reset(r)
    assert 'أُضيف' in out, out
    member = team()['966509666097']
    assert member['name'] == 'ابو تميم فارس' and member['short'] == 'ابو تميم' and member['manager'] is False
    model, calls = scripted([('list_employees', {})], 'القائمة.')
    run_as(staff, 'وريني الموظفين', model)
    assert '966509666097' in calls[1][-1]['content'][0]['content']
    print('PASS: employees added by the manager with confirmation, never as managers.')


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    target = urlsplit(url)
    if target.scheme not in ('postgres', 'postgresql') or target.hostname not in ('localhost', '127.0.0.1') or target.path != '/afaaq_test' or target.query:
        raise RuntimeError('Requires local disposable afaaq_test without URL parameters')
    schema = 'cmdagent_test_' + secrets.token_hex(6)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    connect = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ('localhost', '127.0.0.1', '::1'):
            raise AssertionError('External network blocked')
        return connect(sock, address)
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema + ' -c statement_timeout=30000'}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': 'test-key', 'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32),
               'ADMIN_EMAIL': 'bootstrap@fixture.invalid', 'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env), patch.object(socket.socket, 'connect', local_only):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: command agent PostgreSQL acceptance; real sends 0.')


if __name__ == '__main__':
    main()
