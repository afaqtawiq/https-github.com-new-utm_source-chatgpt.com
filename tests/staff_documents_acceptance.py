"""A team member's file is kept and questions about it are answered from the file: a forwarded shipping PDF whose
extraction returns no JSON gets a summary (not «لم أستخرج بيانات»), a question in the caption is answered, and a later
«شوف لي تاريخ وصول الشحنة» goes to ask_document. Isolated PostgreSQL; model and media simulated; nothing sent."""
import asyncio
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PDF = b'%PDF-1.4 fixture shipping document WHS260723J-1'
OWNER = '966500000001'


def payload(caption='', pid='e1'):
    return {'id': pid, 'conversation': {'id': 'conv-m'},
            'message': {'text': caption, 'attachments': [{'type': 'document', 'mimeType': 'application/pdf',
                                                          'fileName': 'WHS260723J-1 .pdf', 'url': '/api/v1/whatsapp/media/x'}]}}


def run():
    from app.bootstrap import app  # noqa: F401
    from app import command_agent, load_vision, staff_documents
    from app.storage import db
    from app.team import ROLE
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_admin_audit(id BIGSERIAL PRIMARY KEY, event_id TEXT, sender TEXT,
            conversation_id TEXT, command TEXT, reply TEXT)''')
    asked = []

    async def model(row, prompt, max_tokens=900):
        asked.append((row['filename'], prompt))
        if 'Question:' in prompt:
            return 'تاريخ الوصول المتوقع (ETA): 02/12/2026 — ميناء جدة الإسلامي.'
        return 'إشعار شحن من مستودع في الصين إلى آفاق طويق.'

    async def media(*a, **k):
        return PDF, 'application/pdf'

    async def no_json(data):
        return {'document_kind': 'other'}

    with patch('app.manager_actions.media_bytes', side_effect=media), patch.object(staff_documents, '_ask_model', side_effect=model):
        # 1) Forwarded with no caption, extraction found nothing structured → summary + invitation, not an error.
        with patch.object(load_vision, 'extract_pdf', side_effect=no_json), db() as c:
            reply = asyncio.run(load_vision.handle_pdf(c, payload(), OWNER, 0))['message']
        assert 'لم أستخرج' not in reply and 'إشعار شحن' in reply and 'اسألني' in reply, reply
        row = staff_documents.latest(OWNER)
        assert row and row['filename'] == 'WHS260723J-1 .pdf' and bytes(row['data']) == PDF

        # 2) A later text question → the command tool reads the same file.
        token = ROLE.set({'name': 'محمد', 'manager': True})
        chat = command_agent.CHAT.set((OWNER, 'conv-m'))
        out = command_agent.tool_ask_document(None, {'question': 'شوف لي تاريخ وصول الشحنة'})
        command_agent.CHAT.reset(chat)
        ROLE.reset(token)
        assert '02/12/2026' in out and 'WHS260723J-1' in out and 'تاريخ وصول الشحنة' in asked[-1][1], out

        # 3) Question in the caption → answered from the file directly, nothing recorded.
        with patch.object(load_vision, 'extract_pdf', side_effect=AssertionError('not needed')), db() as c:
            reply = asyncio.run(load_vision.handle_pdf(c, payload('شوف لي تاريخ وصول الشحنة', 'e2'), OWNER, 0))['message']
        assert '02/12/2026' in reply, reply

        # 4) Another member has no file → clear answer; old files expire.
        chat = command_agent.CHAT.set(('966500000099', 'conv-x'))
        assert 'لا يوجد ملف' in command_agent.tool_ask_document(None, {'question': 'متى الوصول'})
        command_agent.CHAT.reset(chat)
        with db() as c:
            c.execute("UPDATE staff_documents SET created_at = NOW() - INTERVAL '4 days'")
        assert staff_documents.latest(OWNER) is None

    # 5) Extraction returning prose instead of JSON no longer raises.
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {'content': [{'type': 'text', 'text': 'This looks like a warehouse receipt.'}]}

    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return R()
    with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fixture'}), patch('httpx.AsyncClient', C):
        assert asyncio.run(load_vision.extract_pdf(PDF)) == {'document_kind': 'other'}

    assert staff_documents.is_question('شوف لي تاريخ وصول الشحنة') and staff_documents.is_question('كم الوزن؟')
    assert not staff_documents.is_question('بيان الياسمين')


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'staff_docs_' + secrets.token_hex(5)
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
    print('PASS: staff documents — file kept, summary instead of error, caption and follow-up questions answered from the file.')


if __name__ == '__main__':
    main()
