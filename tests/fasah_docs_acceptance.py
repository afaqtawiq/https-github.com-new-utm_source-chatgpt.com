"""Release notice PDF + SADAD payment details from FASAH on local PostgreSQL. No AI key (text fallback), nothing sent:
customer messages are only «نفذ» codes; the PDF is served only by its private token."""
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
PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'


def run():
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app import agent_runner, fasah_docs, fasah_tracking as ft
    from app.storage import db, utcnow
    ft.init(); agent_runner.init(); fasah_docs.init()
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ, consumed BOOLEAN NOT NULL DEFAULT FALSE)''')
    chat = patch('app.transport_desk.manager_chat', return_value=('966500000001', 'conv-manager'))
    chat.start()
    t0 = utcnow() - dt.timedelta(hours=3)
    row = lambda n, d: {'رقم المرجع': '1', 'رقم البيان': n, 'التاريخ': '01/11/2026', 'التفاصيل': d}
    ft.ingest([row('418900', 'سلة الرحائب تحت المعالجة'), row('418901', 'مؤسسة الياسمين تحت المعالجة')], 'import', now=t0)
    ft.save_contact('سلة الرحائب', '0551234567', 'المدير')

    # 1) Status changes queue read-only document tasks once.
    changes = ft.ingest([row('418900', 'سلة الرحائب جاهز لطباعة إشعار الفسح الجمركي'),
                         row('418901', 'مؤسسة الياسمين مرحلة إنتظار تحصيل الرسوم الجمركيه')], 'import', now=t0 + dt.timedelta(hours=2))
    ids = fasah_docs.request_for(changes)
    assert len(ids) == 2 and fasah_docs.request_for(changes) == []
    with db() as c:
        tasks = {r['kind']: (r['id'], json.loads(r['params_json']), r['created_by'])
                 for r in c.execute('SELECT * FROM runner_tasks ORDER BY id').fetchall()}
    assert tasks['fasah_release_notice'][1]['number'] == '418900' and tasks['fasah_release_notice'][2] == fasah_docs.DOC_ACTOR
    assert tasks['fasah_details'][1] == {'which': 'import', 'number': '418901', 'pages': 5, 'purpose': 'duties'}

    def finish(tid, name, mime, data):
        with db() as c:
            c.execute("UPDATE runner_tasks SET status='done' WHERE id=%s", (tid,))
            c.execute('''INSERT INTO runner_files(task_id,name,mime,size,sha256,verified,data,created_at)
                VALUES(%s,%s,%s,%s,%s,TRUE,%s,NOW())''', (tid, name, mime, len(data), secrets.token_hex(8), data))
    sent = []
    finish(tasks['fasah_release_notice'][0], 'release-418900.pdf', 'application/pdf', PDF)
    finish(tasks['fasah_details'][0], 'fasah-418901.txt', 'text/plain',
           'تفاصيل الطلب\nرقم فاتورة سداد: 1234567890123\nالمبلغ الإجمالي: 15,230.50 ريال\n'.encode())
    with patch.object(agent_runner, 'notify', side_effect=sent.append):
        agent_runner.after_fasah(tasks['fasah_release_notice'][0])
        agent_runner.after_fasah(tasks['fasah_details'][0])
    assert len(sent) == 2, sent
    release, duties = sent
    assert '418900' in release and '/fasah/notice/' in release and 'نفذ ' in release and '+966551234567' in release
    assert 'سداد 1234567890123' in duties and '15,230.50 ريال' in duties and 'رقم العميل غير معروف' in duties

    # 2) The customer message for the release carries the private PDF link; the link serves the PDF only by token.
    with db() as c:
        action = json.loads(c.execute('SELECT command FROM whatsapp_voice_pending').fetchone()['command'].partition(':')[2])
        token = c.execute("SELECT token FROM fasah_documents WHERE doc='release_notice'").fetchone()['token']
    assert action['to'] == '+966551234567' and 'تم فسح بيانكم الجمركي رقم 418900' in action['text'] and token in action['text']
    client = TestClient(app, base_url='http://testserver')
    r = client.get('/fasah/notice/' + token + '.pdf')
    assert r.status_code == 200 and r.content.startswith(b'%PDF') and r.headers['content-type'] == 'application/pdf'
    assert client.get('/fasah/notice/' + 'x' * 24 + '.pdf').status_code == 404
    with db() as c:
        c.execute("UPDATE fasah_documents SET expires_at=NOW()-INTERVAL '1 day' WHERE token=%s", (token,))
    assert client.get('/fasah/notice/' + token + '.pdf').status_code == 404

    # 3) Duties text without numbers → honest warning, nothing prepared.
    assert fasah_docs.extract_sadad('لا يوجد شيء') == {'sadad_number': '', 'amount': ''}
    assert 'عميلنا العزيز' in fasah_docs.duties_text('1', 'import', '123456', '10')
    # 4) Runner accepts the new read-only kind with a valid number only.
    assert agent_runner.create_task('fasah_release_notice', {'number': 'abc'})[0] is None
    chat.stop()


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'fasah_docs_' + secrets.token_hex(5)
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
    print('PASS: release notice PDF link + SADAD details; nothing sent; private token only.')


if __name__ == '__main__':
    main()
