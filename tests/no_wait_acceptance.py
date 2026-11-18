"""«لا أحد ينتظر»: promises → reminder / late alert (or closed when a person answered), customer waiting after
hand-off → alert then escalation (none when answered), upset customer → alert + hand-off record + offers paused.
Isolated PostgreSQL; provider reads and delivery simulated; nothing is sent to anyone."""
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

ACC = 'acc-1'
# 10:00 Riyadh — inside working hours
T0 = dt.datetime(2026, 11, 18, 7, 0, tzinfo=dt.timezone.utc)


def job(c, mid, cid, sender, question, at, status='sent', reply=None):
    c.execute('''INSERT INTO whatsapp_agent_jobs(account_id,message_id,event_id,sender,conversation_id,payload,status,
        reply_text,idempotency_key,created_at,updated_at,completed_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
              (ACC, mid, 'ev-' + mid, sender, cid, json.dumps({'question': question}, ensure_ascii=False), status, reply,
               'key-' + mid, at, at, at + dt.timedelta(seconds=20) if status == 'sent' else None))


def run():
    from app.bootstrap import app  # noqa: F401
    from app import auto_handoff, customer_care, no_wait, whatsapp_agent_store as store, whatsapp_takeover as takeover
    from app.command_agent import tool_customer_waiting
    from app.storage import db
    from app.team import ROLE
    store.init_storage(); takeover.init_storage(); auto_handoff.init()
    with db() as c:
        from app.whatsapp_inbox import ensure
        ensure(c)
        c.execute('''CREATE TABLE IF NOT EXISTS marketing_suppressions(channel TEXT, recipient TEXT, created_at TIMESTAMPTZ,
            PRIMARY KEY(channel, recipient))''')
    no_wait.init()

    # 0) Pure parsing.
    assert no_wait.promise_due('تمام، أرجع لك بالسعر خلال ساعة', T0) == T0 + dt.timedelta(hours=1)
    assert no_wait.promise_due('سيتواصل معك فريقنا بعد 15 دقيقة', T0) == T0 + dt.timedelta(minutes=15)
    assert no_wait.promise_due('بنرسل لك العرض بكرة', T0).astimezone(no_wait.RIYADH).hour == 11
    assert no_wait.promise_due('شكرا لتواصلك، الرسوم 449 ريال', T0) is None
    assert no_wait.upset_reasons('هذي مهزلة، بشتكي عليكم')[0] == 'strong'
    assert no_wait.upset_reasons('كم سعر النقل للرياض؟') == (None, [])

    delivered, reads = [], []

    async def deliver(text):
        delivered.append(text)
        return 'whatsapp'

    def answered(result):
        async def fake(account, cid, since, agent_texts=(), skip_texts=()):
            reads.append((cid, since, list(agent_texts) + list(skip_texts)))
            return result(cid) if callable(result) else result
        return fake

    def tick(at, result=False):
        delivered.clear()
        with patch.object(no_wait, 'answered_after', side_effect=answered(result)):
            return asyncio.run(no_wait.tick(now=at, deliver=deliver))

    # 1) Promise by the agent (conv A) and by an employee from the inbox (conv B).
    with db() as c:
        job(c, 'm1', 'conv-A', '966500000011', 'كم سعر التخليص لحاوية 40؟', T0, reply='تمام، أرجع لك بالسعر خلال ساعة')
        c.execute('''INSERT INTO whatsapp_inbox_drafts(token,account_id,conversation_id,recipient,body,created_by,state,created_at,updated_at)
            VALUES('tok-1',%s,'conv-B','966500000022','بنرسل لك عرض النقل اليوم',1,'accepted',%s,%s)''', (ACC, T0, T0))
    assert tick(T0 + dt.timedelta(minutes=1)) == []
    with db() as c:
        rows = {r['conversation_id']: r for r in c.execute('SELECT * FROM customer_promises').fetchall()}
    assert set(rows) == {'conv-A', 'conv-B'} and rows['conv-A']['said_by'] == 'الوكيل الآلي'
    assert rows['conv-A']['due_at'] == T0 + dt.timedelta(seconds=20, hours=1)
    pa, pb = rows['conv-A'], rows['conv-B']

    # 2) 10 minutes before due → reminder; nobody answered.
    out = tick(pa['due_at'] - dt.timedelta(minutes=9))
    assert len(out) == 1 and '⏰' in out[0] and '966500000011' in out[0] and f"تم الوعد {pa['id']}" in out[0], out
    assert reads[-1][2] == ['تمام، أرجع لك بالسعر خلال ساعة']  # the agent's own reply never counts as an answer
    assert tick(pa['due_at'] - dt.timedelta(minutes=5)) == []  # not twice
    # 30 minutes late → late alert, once.
    out = tick(pa['due_at'] + dt.timedelta(minutes=31))
    assert len(out) == 1 and '🔴' in out[0] and 'فات موعده' in out[0], out
    assert tick(pa['due_at'] + dt.timedelta(minutes=40)) == []

    # 3) Conv B: someone already answered (provider shows a human message) → closed as kept, no alert.
    end_of_day = pb['due_at']
    assert tick(end_of_day - dt.timedelta(minutes=5), result=True) == []
    with db() as c:
        assert c.execute('SELECT status FROM customer_promises WHERE id=%s', (pb['id'],)).fetchone()['status'] == 'kept'

    # 4) Manager commands: list and close.
    token = ROLE.set({'name': 'محمد', 'manager': True})
    with patch.object(no_wait, 'utcnow', return_value=T0 + dt.timedelta(hours=3)):
        listing = tool_customer_waiting(None, {})
    assert 'الوعود المفتوحة: 1' in listing and str(pa['id']) in listing, listing
    assert '✅' in tool_customer_waiting(None, {'action': 'close', 'id': str(pa['id'])})
    assert 'لا يوجد' in tool_customer_waiting(None, {'action': 'close', 'id': str(pa['id'])})
    ROLE.reset(token)

    # 5) Waiting: conversation paused for staff and the customer writes; nobody answers.
    t1 = T0 + dt.timedelta(hours=4)
    with db() as c:
        c.execute('''INSERT INTO whatsapp_conversation_takeovers(account_id,conversation_id,sender,paused,generation,updated_by,updated_at)
            VALUES(%s,'conv-C','966500000033',TRUE,1,'staff',%s)''', (ACC, t1))
        c.execute('''INSERT INTO whatsapp_takeover_receipts(account_id,conversation_id,message_id,sender,body,attachment_count,generation,received_at)
            VALUES(%s,'conv-C','h1','966500000033','متى توصل الشحنة؟',0,1,%s)''', (ACC, t1))
    assert tick(t1 + dt.timedelta(minutes=10)) == []
    out = tick(t1 + dt.timedelta(minutes=21))
    assert len(out) == 1 and '⏳' in out[0] and '966500000033' in out[0], out
    assert tick(t1 + dt.timedelta(minutes=30)) == []
    out = tick(t1 + dt.timedelta(minutes=61))
    assert len(out) == 1 and 'تصعيد' in out[0], out
    assert tick(t1 + dt.timedelta(minutes=90)) == []
    # A hand-off with an answer on the provider → recorded as answered, never alerted.
    with db() as c:
        c.execute('''INSERT INTO whatsapp_handoff_summaries(account_id,conversation_id,sender,reason,mode,summary,created_at)
            VALUES(%s,'conv-D','966500000044','unverified','suggested','x',%s)''', (ACC, t1))
    assert tick(t1 + dt.timedelta(minutes=25), result=lambda cid: cid == 'conv-D') == []
    assert tick(t1 + dt.timedelta(minutes=70), result=False) == []
    # A staff reply from the platform inbox after the customer wrote → no alert, no provider read.
    with db() as c:
        c.execute('''INSERT INTO whatsapp_takeover_receipts(account_id,conversation_id,message_id,sender,body,attachment_count,generation,received_at)
            VALUES(%s,'conv-C','h2','966500000033','طيب',0,1,%s)''', (ACC, t1 + dt.timedelta(hours=2)))
        c.execute('''INSERT INTO whatsapp_inbox_drafts(token,account_id,conversation_id,recipient,body,created_by,state,created_at,updated_at)
            VALUES('tok-2',%s,'conv-C','966500000033','الشحنة تصل الخميس',1,'accepted',%s,%s)''',
                  (ACC, t1 + dt.timedelta(hours=2, minutes=5), t1 + dt.timedelta(hours=2, minutes=5)))
    assert tick(t1 + dt.timedelta(hours=2, minutes=30)) == []

    # 6) Upset customer → one alert with summary, hand-off record, offers paused; then the cooldown.
    t2 = T0 + dt.timedelta(hours=8)
    with db() as c:
        job(c, 'm9', 'conv-E', '966500000055', 'ثالث مرة أسأل وين الرد!!! هذي مهزلة وبشتكي عليكم', t2, reply='نعتذر')
        job(c, 'm10', 'conv-E', '966500000055', 'مهزلة', t2 + dt.timedelta(minutes=1), reply='نعتذر')
    out = tick(t2 + dt.timedelta(minutes=2))
    upset = [t for t in out if '😠' in t]
    assert len(upset) == 1 and '966500000055' in upset[0] and 'مهزله' in upset[0] and 'تسليم المحادثة' in upset[0], out
    with db() as c:
        assert c.execute("SELECT reason FROM whatsapp_handoff_summaries WHERE conversation_id='conv-E'").fetchone()['reason'] == 'upset'
        assert '966500000055' in customer_care.blocked(c)
    assert not [t for t in tick(t2 + dt.timedelta(minutes=4)) if '😠' in t]

    # 7) Night: nothing delivered; held upset alert goes out in the morning.
    night = dt.datetime(2026, 11, 18, 21, 0, tzinfo=dt.timezone.utc)  # 00:00 Riyadh
    with db() as c:
        job(c, 'm20', 'conv-F', '966500000066', 'أسوأ تعامل، رجعوا فلوسي', night, reply='نعتذر')
    assert tick(night + dt.timedelta(minutes=2)) == []
    out = tick(night + dt.timedelta(hours=7, minutes=30))
    assert any('966500000066' in t and '😠' in t for t in out), out

    # 8) Team numbers are never watched.
    with patch.dict(os.environ, {'WHATSAPP_COMMAND_OWNER': '966500000077'}):
        with db() as c:
            job(c, 'm30', 'conv-G', '966500000077', 'مهزلة بشتكي', night + dt.timedelta(hours=8), reply='أرجع لك خلال ساعة')
        out = tick(night + dt.timedelta(hours=8, minutes=2))
    assert not [t for t in out if '966500000077' in t]


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'no_wait_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0', 'WHATSAPP_COMMAND_OWNER': ''}
        with patch.dict(os.environ, env):
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: no-wait — promise reminder/late/kept, waiting alert/escalation/answered, upset alert + hand-off + offer hold, quiet night, team ignored.')


if __name__ == '__main__':
    main()
