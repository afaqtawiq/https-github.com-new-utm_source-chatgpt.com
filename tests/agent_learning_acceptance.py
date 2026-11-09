"""Learning loop on isolated PostgreSQL (MOCK model): yesterday's weak questions → morning report → «جواب N» after «نفذ»
→ the customer agent prompt and grounding carry the approved answer; revoke removes it. Nothing is sent."""
import asyncio
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


def run():
    import httpx
    from app.bootstrap import app  # noqa: F401
    from app import agent_learning as al, command_agent, whatsapp_natural as natural
    from app.storage import db
    al.init()
    day = dt.datetime.now(al.RIYADH).date() - dt.timedelta(days=1)
    noon = dt.datetime.combine(day, dt.time(12), al.RIYADH)
    n = [0]

    def job(sender, q, reply, status='sent', when=noon):
        n[0] += 1
        with db() as c:
            c.execute('''INSERT INTO whatsapp_agent_jobs(account_id,message_id,event_id,sender,conversation_id,payload,status,
                reply_text,idempotency_key,created_at,updated_at) VALUES('acc',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                      (f'm{n[0]}', f'e{n[0]}', sender, 'c-' + sender, json.dumps({'question': q}), status, reply, f'k{n[0]}', when, when))
    job('966500000001', 'كم رسوم التخليص للحاوية 40 قدم في الدمام؟', natural.FEE_TOTAL_UNVERIFIED_REPLY)
    job('966500000002', 'كم رسوم التخليص لحاوية 40 قدم بالدمام', natural.FEE_TOTAL_UNVERIFIED_REPLY)
    job('966500000003', 'هل الكراسي عليها سابر؟', natural.SABER_UNVERIFIED_REPLY)
    job('966500000004', 'شكرا', 'العفو')
    job('966500000005', 'وين شحنتي', None, status='failed')
    job('966500000006', 'سؤال قديم', natural.SABER_UNVERIFIED_REPLY, when=noon - dt.timedelta(days=3))

    # 1) Morning report: scorecard + grouped gaps (the two Dammam fee questions are one gap from 2 customers).
    text = al.report(day)
    assert 'رسائل: 5 من 5 عميل' in text and 'أسئلة ضعيفة: 4' in text, text
    assert "1. «كم رسوم التخليص" in text and 'من 2 عميل' in text and 'سؤال قديم' not in text
    assert al.gap_question(1).startswith('كم رسوم التخليص') and al.gap_question(9) is None
    assert al.due(dt.datetime.combine(day + dt.timedelta(days=1), dt.time(9), al.RIYADH)) is False  # already sent today

    # 2) «جواب 1: …» → «نفذ» code; nothing learned before confirmation.
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ, consumed BOOLEAN NOT NULL DEFAULT FALSE)''')
        token = command_agent.CHAT.set(('966500000099', 'conv-m'))
        out = command_agent.tool_teach_answer(c, {'gap_number': '1', 'answer': 'أتعاب تخليص آفاق للحاوية في الدمام 700 ريال، ولا تشمل رسوم الجمارك والميناء.'})
        command_agent.CHAT.reset(token)
        action = json.loads(c.execute('SELECT command FROM whatsapp_voice_pending').fetchone()['command'].partition(':')[2])
    assert 'نفذ ' in out and action['tool'] == 'teach_answer' and not al.approved()
    assert 'روابط خارجية' in command_agent.tool_teach_answer(None, {'question': 'سؤال', 'answer': 'شوف https://evil.example.com الآن'})
    print(al.save(action['question'], action['answer'], 'المدير'))
    assert len(al.approved()) == 1 and '700 ريال' in al.block()
    # The taught gap no longer appears in the next report.
    assert 'كم رسوم التخليص' not in al.report(day)

    # 3) The customer agent now receives the approved answer, and its number passes the grounding check.
    calls = []
    original = httpx.AsyncClient

    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': 'أتعاب التخليص للحاوية في الدمام 700 ريال، ولا تشمل رسوم الجمارك والميناء.'}]})
    with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'synthetic', 'WHATSAPP_NATURAL_MODEL': 'claude-test', 'WHATSAPP_NATURAL_REPLIES': '1'}), \
         patch.object(natural.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw)):
        answer = asyncio.run(natural.reply('كم أتعاب التخليص في الدمام؟'))
    assert 'APPROVED TEAM ANSWERS' in calls[0]['system'] and '700 ريال' in calls[0]['system']
    assert answer and '700' in answer, answer

    # 4) Revoke → gone from the prompt.
    rid = al.approved()[0]['id']
    assert 'أُلغي' in al.revoke(rid) and al.block() == '' and 'لا توجد أجوبة' in al.list_text()


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'learning_' + secrets.token_hex(5)
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
    print('PASS: daily learning loop — weak questions reported, taught after «نفذ», used by the agent, revocable.')


if __name__ == '__main__':
    main()
