"""Virtual office: WhatsApp «مدير X: …» routes to that department manager with ONLY its tools and its role, signs the
reply and keeps its memory; ordinary messages are not routed; «تقرير الأقسام» returns live numbers; the /office pages
need an admin session and the chat posts through the department manager. Isolated PostgreSQL; model simulated."""
import datetime as dt
import os
import re
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app import command_agent, container_returns, line_desk, virtual_office as vo
    from app.storage import db, utcnow
    from app.team import ROLE
    line_desk.init(); vo.init()
    container_returns.track({'container': 'MSCU1234565', 'free_until': (dt.date.today() - dt.timedelta(days=2)).isoformat()}, 'محمد')

    # 1) Routing: prefixes route, ordinary text does not.
    assert vo.route('مدير المالية: كشف عمران لهذا الشهر') == ('finance', 'كشف عمران لهذا الشهر')
    assert vo.route('قسم النقل، كم حمولة اليوم؟') == ('transport', 'كم حمولة اليوم؟')
    assert vo.route('الحاويات: وش المتأخر') == ('containers', 'وش المتأخر')
    assert vo.route('مدير خدمة العملاء')[0] == 'service'
    assert vo.route('نورة: كشف عمران') == ('finance', 'كشف عمران') and vo.route('يا سلطان وش المتأخر')[0] == 'containers'
    assert vo.route('نورة كلمت العميل') is None
    for text in ('الحاويات المتأخرة كم', 'كشف عمران لشهر اكتوبر', 'فسح مفتوح الان', 'سجل حسابات سلة من فسح'):
        assert vo.route(text) is None, text

    calls = []

    def model(messages, system):
        calls.append({'tools': [t['name'] for t in command_agent.scoped_tools()],
                      'system': system, 'messages': messages})
        if len(calls) % 2 == 1:
            return {'content': [{'type': 'tool_use', 'id': 't1', 'name': 'containers_status', 'input': {}}]}
        return {'content': [{'type': 'text', 'text': 'عندك حاوية متأخرة واحدة: MSCU1234565.'}]}

    with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fixture'}), patch.object(command_agent, 'call_model', side_effect=model):
        token = ROLE.set({'name': 'محمد', 'manager': True})
        with db() as c:
            reply = command_agent.run_agent(c, 'مدير الحاويات: وش المتأخر عندك؟')
        ROLE.reset(token)
    assert reply.startswith('🚢 سلطان — مدير الحاويات والملاحة:') and 'MSCU1234565' in reply, reply
    first = calls[0]
    assert 'containers_status' in first['tools'] and 'record_payment' not in first['tools'] and 'broadcast_load' not in first['tools']
    assert 'مدير الحاويات والملاحة' in first['system'] and 'سلطان' in first['system'] and 'متأخرة عن آخر يوم مجاني: 1' in first['system'], first['system'][-600:]
    assert first['messages'][0]['content'] == 'وش المتأخر عندك؟'
    with db() as c:
        row = c.execute("SELECT * FROM office_messages WHERE department='containers'").fetchone()
    assert row['channel'] == 'واتساب' and row['author'] == 'محمد' and 'MSCU1234565' in row['reply']

    # 2) Memory: the next message to the same manager carries the previous exchange; unrouted messages use all tools.
    calls.clear()
    with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fixture'}), patch.object(command_agent, 'call_model', side_effect=model):
        token = ROLE.set({'name': 'محمد', 'manager': True})
        with db() as c:
            command_agent.run_agent(c, 'مدير الحاويات: وبكرة؟')
            calls.clear()
            command_agent.run_agent(c, 'كم الحاويات المفتوحة')
        ROLE.reset(token)
    assert 'record_payment' in calls[0]['tools'] and 'مدير الحاويات' not in calls[0]['system']
    hist = vo.history('containers')
    assert len(hist) == 2 and hist[-1]['command'] == 'وبكرة؟'

    # 3) Report of all departments with live numbers.
    with db() as c:
        report = command_agent.tool_office_report(c, {})
        one = command_agent.tool_office_report(c, {'department': 'الحاويات'})
    assert all(d['name'] in report for d in vo.DEPARTMENTS.values()) and 'مدير المالية' in report
    assert 'متأخرة عن آخر يوم مجاني: 1' in one and 'المالية' not in one

    # 4) Web office: admin only; posting goes through the department manager.
    client = TestClient(app)
    assert client.get('/office', follow_redirects=False).status_code == 401
    with db() as c:
        uid = c.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()['id']
        sid, csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(16)
        cols = {r['column_name'] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='sessions'").fetchall()}
        values = {'id': sid, 'user_id': uid, 'csrf': csrf, 'expires_at': utcnow() + dt.timedelta(hours=1), 'created_at': utcnow()}
        values = {k: v for k, v in values.items() if k in cols}
        c.execute('INSERT INTO sessions(' + ','.join(values) + ') VALUES(' + ','.join(['%s'] * len(values)) + ')', tuple(values.values()))
    client.cookies.set('gla_session', sid)
    page = client.get('/office').text
    assert 'المكتب الافتراضي' in page and all(d['manager'] in page for d in vo.DEPARTMENTS.values())
    assert client.get('/office/nope').status_code == 404
    calls.clear()
    with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fixture'}), patch.object(command_agent, 'call_model', side_effect=model):
        r = client.post('/office/finance', data={'csrf': csrf, 'text': 'كم البيانات المسجلة هذا الشهر؟'},
                        headers={'origin': 'http://testserver'}, follow_redirects=False)
    assert r.status_code == 303, r.status_code
    assert 'record_payment' in calls[0]['tools'] and 'broadcast_load' not in calls[0]['tools']
    page = client.get('/office/finance').text
    assert 'كم البيانات المسجلة هذا الشهر؟' in page and 'المنصة' in page
    bad = client.post('/office/finance', data={'csrf': 'wrong', 'text': 'x'}, headers={'origin': 'http://testserver'}, follow_redirects=False)
    assert bad.status_code == 403

    # 5) 3D office: page with config, local assets, JSON API (state, report, history, ask with CSRF header).
    page = client.get('/office').text
    assert '"key": "containers"' in page and '/office/assets/three.module.min.js' in page and csrf in page
    assert 'مدير المالية' in client.get('/office/cards').text
    for path, kind in (('three.module.min.js', 'javascript'), ('models/people/suit_male.glb', 'gltf'), ('models/people/classy_female.glb', 'gltf'), ('jsm/libs/meshopt_decoder.module.js', 'javascript'), ('jsm/loaders/GLTFLoader.js', 'javascript')):
        r = client.get('/office/assets/' + path)
        assert r.status_code == 200 and kind in r.headers['content-type'], path
    assert client.get('/office/assets/THREE_LICENSE').status_code == 404
    assert client.get('/office/assets/%2e%2e/virtual_office.py').status_code == 404
    state = client.get('/office/api/state').json()
    cont = next(d for d in state['departments'] if d['key'] == 'containers')
    assert cont['person'] == 'سلطان' and cont['model'] == 'classy_male' and cont['alert'] and ['متأخرة عن آخر يوم مجاني', 1] in cont['kpis'] and 'csrf' not in state
    assert 'تقرير الأقسام' in client.get('/office/api/report').json()['text']
    assert client.get('/office/api/finance/history').json()['messages'][-1]['command'] == 'كم البيانات المسجلة هذا الشهر؟'
    assert client.post('/office/api/finance/ask', json={'text': 'x'}, headers={'origin': 'http://testserver'}).status_code == 403
    calls.clear()
    with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fixture'}), patch.object(command_agent, 'call_model', side_effect=model):
        r = client.post('/office/api/containers/ask', json={'text': 'وش المتأخر؟'},
                        headers={'origin': 'http://testserver', 'X-CSRF-Token': csrf})
    assert r.status_code == 200 and 'MSCU1234565' in r.json()['reply'], r.text

    # 6) Uploads: PDF, Excel, Word and images reach the manager; the manager reads the file with ask_document.
    import io, zipfile
    from app import staff_documents
    import openpyxl
    from PIL import Image
    book = openpyxl.Workbook(); book.active.append(['البيان', 'القيمة']); book.active.append(['418801', '20500'])
    xbuf = io.BytesIO(); book.save(xbuf)
    dbuf = io.BytesIO()
    with zipfile.ZipFile(dbuf, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', '<w:document><w:body><w:p><w:r><w:t>عقد نقل مع شركة النخبة</w:t></w:r></w:p>'
                   '<w:p><w:r><w:t>المبلغ 4500 ريال</w:t></w:r></w:p></w:body></w:document>')
    ibuf = io.BytesIO(); Image.new('RGB', (2400, 1200), 'white').save(ibuf, 'PNG')
    files = {'a.pdf': (b'%PDF-1.4 fixture', 'document'), 'b.xlsx': (xbuf.getvalue(), 'text'), 'c.docx': (dbuf.getvalue(), 'text'),
             'd.png': (ibuf.getvalue(), 'image')}
    seen = []

    async def fake_model(row, prompt, max_tokens=900):
        content = staff_documents._content(row)
        seen.append((row['filename'], row['sender'], content[0]['type'], content))
        return 'قرأت الملف ' + row['filename']

    def reading_model(messages, system):
        if len(messages) == 1:
            return {'content': [{'type': 'tool_use', 'id': 't1', 'name': 'ask_document', 'input': {'question': 'لخص'}}]}
        result = messages[-1]['content'][0]['content']
        return {'content': [{'type': 'text', 'text': 'تمام: ' + result}]}

    headers = {'origin': 'http://testserver', 'X-CSRF-Token': csrf}
    with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fixture'}), patch.object(command_agent, 'call_model', side_effect=reading_model), \
            patch.object(staff_documents, '_ask_model', side_effect=fake_model):
        for name, (data, kind) in files.items():
            r = client.post('/office/api/finance/upload', files={'file': (name, data)}, data={'text': 'وش في الملف؟'}, headers=headers)
            assert r.status_code == 200 and name in r.json()['reply'], (name, r.text)
            assert seen[-1][0] == name and seen[-1][1].startswith('office:') and seen[-1][2] == kind, seen[-1][:3]
        r = client.post('/office/api/finance/upload', files={'file': ('e.xlsx', xbuf.getvalue())}, headers=headers)
        assert r.status_code == 200, r.text   # a file with no message is summarised
    word = next(c for n, _, _, c in seen if n == 'c.docx')[0]['text']
    assert 'عقد نقل مع شركة النخبة' in word and '4500' in word
    excel = next(c for n, _, _, c in seen if n == 'b.xlsx')[0]['text']
    assert '418801' in excel
    img = next(c for n, _, _, c in seen if n == 'd.png')[0]['source']
    assert img['media_type'] == 'image/jpeg'                        # 2400 px resized for the model
    page = client.get('/office/api/finance/history').json()['messages']
    assert page[-1]['command'].startswith('📎 e.xlsx')
    for name, data, code in (('old.xls', b'\xd0\xcf\x11\xe0' + b'0' * 50, 415), ('x.exe', b'MZ' + b'0' * 50, 415),
                             ('a.pdf', b'%PDF', 403)):
        h = headers if code != 403 else {'origin': 'http://testserver'}
        r = client.post('/office/api/finance/upload', files={'file': (name, data)}, headers=h)
        assert r.status_code == code, (name, r.status_code, r.text)
    assert 'xlsx' in client.post('/office/api/finance/upload', files={'file': ('old.xls', b'\xd0\xcf\x11\xe0' + b'0' * 50)},
                                  headers=headers).json()['detail']
    # WhatsApp files stay separate from the office uploads.
    assert staff_documents.latest('966500000001') is None


    # 7) Finance and clearance run the work computer and the FASAH billing; finance sends a statement to a group.
    fin, clr = vo.scope('finance')['tools'], vo.scope('clearance')['tools']
    assert {'open_fasah', 'fasah_billing', 'statement_to_group', 'runner_status'} <= fin and {'open_fasah', 'fasah_billing'} <= clr
    state = client.get('/office/api/state').json()
    assert any('جهاز آفاق طويق' in a[0] for a in next(d for d in state['departments'] if d['key'] == 'finance')['actions'])
    from app import statement_groups, statement_import
    found = [('g1', 'قروب الياسمين للتخليص'), ('g2', 'عمران — الحسابات'), ('g3', 'عائلة')]
    assert statement_groups.match(found, 'الياسمين') == ('g1', 'قروب الياسمين للتخليص')
    assert statement_groups.match(found, 'سلة الرحائب') is None and statement_groups.match(found, 'الياسمين', 'عائلة')[0] == 'g3'
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_admin_audit(id BIGSERIAL PRIMARY KEY, event_id TEXT, sender TEXT,
            conversation_id TEXT, command TEXT, reply TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ, consumed BOOLEAN NOT NULL DEFAULT FALSE)''')
        c.execute("INSERT INTO whatsapp_admin_audit(event_id,sender,conversation_id,command,reply) VALUES('e','966500000001','conv-owner','x','y')")
    fake_statement = {'party': 'الياسمين', 'month': '2026-11', 'lines': [{'number': '418801'}], 'total': 1250.5}
    posted = []

    async def fake_groups():
        return found

    async def fake_send(cid, content, filename, caption):
        posted.append((cid, content[:5], filename, caption))
        return 'wamid.1'

    def group_model(messages, system):
        if len(messages) == 1:
            return {'content': [{'type': 'tool_use', 'id': 't1', 'name': 'statement_to_group', 'input': {'party': 'الياسمين'}}]}
        return {'content': [{'type': 'text', 'text': messages[-1]['content'][0]['content']}]}

    with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fixture', 'WHATSAPP_COMMAND_OWNER': '+966500000001'}), \
            patch.object(command_agent, 'call_model', side_effect=group_model), \
            patch.object(statement_import, 'statement', return_value=fake_statement), \
            patch.object(statement_groups, 'groups', side_effect=fake_groups), patch.object(statement_groups, 'send_pdf', side_effect=fake_send), \
            patch('app.statement_pdf.build', return_value=b'%PDF-1.4 statement'):
        r = client.post('/office/api/finance/ask', json={'text': 'أرسل كشف الياسمين لقروب الياسمين'}, headers=headers)
        reply = r.json()['reply']
        assert 'قروب الياسمين للتخليص' in reply and '1,250.50' in reply and 'نفذ ' in reply and not posted, reply
        code = re.search(r'نفذ ([0-9A-F]{6})', reply).group(1)
        with db() as c:
            row = c.execute('SELECT sender, conversation_id FROM whatsapp_voice_pending WHERE token=%s', (code,)).fetchone()
        assert row['sender'] == '966500000001' and row['conversation_id'] == 'conv-owner'   # confirmable on WhatsApp too
        done = client.post('/office/api/finance/ask', json={'text': 'نفذ ' + code}, headers=headers).json()['reply']
        assert '✅' in done and posted and posted[0][0] == 'g1' and posted[0][1] == b'%PDF-' and 'الياسمين' in posted[0][3], done
        again = client.post('/office/api/finance/ask', json={'text': 'نفذ ' + code}, headers=headers).json()['reply']
        assert 'نُفذ من قبل' in again and len(posted) == 1
    # No group → clear explanation, nothing prepared.
    async def fake_groups_empty():
        return []
    with patch.dict(os.environ, {'WHATSAPP_COMMAND_OWNER': '+966500000001'}), \
            patch.object(statement_import, 'statement', return_value=fake_statement), \
            patch.object(statement_groups, 'groups', side_effect=fake_groups_empty):
        out = statement_groups.prepare('الياسمين', '', '', lambda a: 'XXXXXX')
    assert 'لم أجد قروب' in out and 'عضوًا' in out and 'نفذ' not in out

    client.cookies.clear()
    assert client.get('/office/api/state').status_code == 401


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'office_' + secrets.token_hex(5)
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
    print('PASS: virtual office — department routing with scoped tools, role and memory; report; admin-only web office and chat.')


if __name__ == '__main__':
    main()
