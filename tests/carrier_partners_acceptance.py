"""Carrier partner invitations on isolated PostgreSQL. MOCK level: WhatsApp sending is replaced; the real
carrier_companies, daily_prospects, carrier_invites and «نفذ» code tables are used. Nothing is sent."""
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
    from app import carrier_directory, carrier_partners as cp, daily_prospects
    from app.storage import db
    carrier_directory.init_storage(); daily_prospects.init(); cp.init()
    with db() as c:
        assert c.execute("SELECT to_regclass('daily_prospects') t").fetchone()['t']
    with db() as c:
        def carrier(name, phone, country, notes=''):
            return c.execute('''INSERT INTO carrier_companies(company_name,normalized_name,country,phone,notes,capacity,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,'',NOW(),NOW()) RETURNING id''', (name, name.lower(), country, phone, notes)).fetchone()['id']
        uae = carrier('UAE Cargo', '+971501111111', 'AE')
        sa = carrier('نقليات الرياض', '+966511111111', 'SA')
        shams = carrier('شمس الخليج', '+966522222222', 'SA', 'تواصلت معنا عبر واتساب تعرض التعاون')
        recent = carrier('شركة تواصلنا معها', '+966533333333', 'SA')
        declined = carrier('رافضة', '+966544444444', 'SA')
        carrier('بلا رقم', '', 'SA')
        c.execute("UPDATE carrier_companies SET contact_consent='declined' WHERE id=%s", (declined,))
        c.execute('''INSERT INTO daily_prospects(source_key,company_name,phone,score,segment,reason,message,message_source,status,batch_date,created_at,updated_at)
            VALUES('carrier:x','x','966533333333',1,'s','r','m','template','contacted',CURRENT_DATE,NOW(),NOW())''')

    # 1) Candidates: phone, not declined, not reached by daily outreach in 14 days; who contacted us first, then Saudi, then UAE.
    rows = cp.candidates()
    assert [r['id'] for r in rows] == [shams, sa, uae], rows
    # Template not approved yet → no code, clear reason.
    ids, text = cp.preview()
    assert not ids and 'بانتظار اعتماد ميتا' in text and 'شمس الخليج' in text
    with db() as c:
        c.execute("INSERT INTO carrier_partner_settings(id,template_status,checked_at) VALUES(1,'APPROVED',NOW())")
    ids, text = cp.preview()
    assert ids == [shams, sa, uae] and 'Afaq Tuwaiq' in text and 'للإيقاف' in text

    # 2) «نفذ»: each company once, the exact template text with its name; never invited twice.
    sent = []
    from app import zernio_whatsapp
    async def fake_send(to, message, **kw):
        sent.append((to, message))
        return {}
    class Now:
        def __init__(self, target, daemon=True):
            self.target = target
        def start(self):
            self.target()
    with patch.dict(os.environ, {'ENABLE_EXTERNAL_ACTIONS': '1', 'LOAD_BROADCAST_DELAY': '0'}), \
         patch.object(zernio_whatsapp, 'send', fake_send), patch.object(cp.threading, 'Thread', Now):
        out = cp.start({'ids': ids}, 'المدير')
        again = cp.start({'ids': ids}, 'المدير')
    assert out.startswith('✅ بدأ إرسال دعوة الشراكة لـ 3') and 'دُعيت مسبقًا' in again and len(sent) == 3
    assert sent[0] == ('+966522222222', cp.body('شمس الخليج'))
    tmpl = cp.template_spec()
    assert zernio_whatsapp.template_parameters({'components': [{'type': 'BODY', 'text': tmpl['components'][0]['text']}]}, sent[0][1]) == ['شمس الخليج']
    assert cp.candidates() == []

    # 3) Replies: saved on the company, manager told once; «إيقاف» declines; strangers are not partners.
    notice = cp.on_reply('+966522222222', 'عندنا 100 تريلا سطحة، جدة الرياض 3200 والدمام الرياض 1800')
    assert notice.startswith('🤝 رد شريك نقل: شمس الخليج') and '3200' in notice
    assert cp.on_reply('966522222222', 'وكمان عندنا براد') is None
    assert cp.on_reply('+966599999999', 'السلام عليكم') == ''
    assert 'أوقفتها' in cp.on_reply('+966511111111', 'إيقاف')
    with db() as c:
        k = c.execute('SELECT quote_notes FROM carrier_companies WHERE id=%s', (shams,)).fetchone()
        consent = c.execute('SELECT contact_consent FROM carrier_companies WHERE id=%s', (sa,)).fetchone()['contact_consent']
    assert '3200' in k['quote_notes'] and 'براد' in k['quote_notes'] and consent == 'declined'
    status = cp.status_text()
    assert 'دُعيت 3 — ردت 1 — أوقفت 1' in status and 'شمس الخليج' in status

    # 4) GM tools: manager-only, the code carries the batch.
    from app import command_agent, virtual_office
    for name in ('carrier_invite', 'carrier_partners'):
        assert name in command_agent.HANDLERS and name in virtual_office.DEPARTMENTS['transport']['tools']
    with patch.object(command_agent, '_member', lambda: {'name': 'موظف', 'manager': False}):
        assert 'المدير فقط' in command_agent.tool_carrier_invite(None, {})
    with db() as c0:
        new = c0.execute('''INSERT INTO carrier_companies(company_name,normalized_name,country,phone,created_at,updated_at)
            VALUES('جديدة','جديدة','SA','+966555555555',NOW(),NOW()) RETURNING id''').fetchone()['id']
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ, consumed BOOLEAN NOT NULL DEFAULT FALSE)''')
        token = command_agent.CHAT.set(('966500000001', 'conv-m'))
        try:
            with patch.object(command_agent, '_member', lambda: {'name': 'المدير', 'manager': True}):
                msg = command_agent.tool_carrier_invite(c, {})
        finally:
            command_agent.CHAT.reset(token)
        action = json.loads(c.execute('SELECT command FROM whatsapp_voice_pending').fetchone()['command'].partition(':')[2])
    assert 'نفذ ' in msg and action == {'tool': 'carrier_invite', 'ids': [new]}


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'carrier_partners_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env):
            import app.main  # noqa: F401  full schema (users, carrier tables)
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: carrier partners — one-code batch invite in the approved template, replies saved on the company, stop honoured.')


if __name__ == '__main__':
    main()
