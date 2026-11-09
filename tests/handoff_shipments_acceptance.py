"""Stages 5-6 on isolated PostgreSQL (MOCK level: no provider, no model, nothing sent).
5) Automatic hand-off: OFF by default (shadow summary only), ON pauses ONLY that conversation, staff intervention,
   repeated messages, unverified answers, manual pause/resume untouched.
6) Customer → shipments projection for the follow-up dashboard."""
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
url = os.environ['AFAAQ_TEST_DATABASE_URL']
assert urlsplit(url).hostname in {'localhost', '127.0.0.1'} and urlsplit(url).path == '/afaaq_test'
import psycopg
schema = 'handoff_' + secrets.token_hex(5)
with psycopg.connect(url, autocommit=True) as connection:
    connection.execute('CREATE SCHEMA ' + schema)
os.environ.update(DATABASE_URL=url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
                  DISCOVERY_AUTO_ENABLED='0', ENABLE_EXTERNAL_ACTIONS='0', ANTHROPIC_API_KEY='',
                  ADMIN_EMAIL='handoff@example.invalid', ADMIN_PASSWORD=secrets.token_urlsafe(24))
os.environ.pop('AUTO_HANDOFF_ENABLED', None)
ACC = 'acc-test'
try:
    from app.bootstrap import app  # noqa: F401
    from app import auto_handoff, whatsapp_natural as natural, whatsapp_takeover as takeover
    from app.storage import db, utcnow, one
    now = utcnow()
    n = [0]

    def job(cid, sender, question, reply, status='sent', minutes_ago=0):
        n[0] += 1
        with db() as c:
            return dict(c.execute('''INSERT INTO whatsapp_agent_jobs(account_id,message_id,event_id,sender,conversation_id,payload,status,
                reply_text,idempotency_key,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                (ACC, f'm{n[0]}', f'e{n[0]}', sender, cid, json.dumps({'question': question}), status, reply,
                 f'k{n[0]}', now - dt.timedelta(minutes=minutes_ago), now)).fetchone())

    # Shipments for the customer (stage 6 data; also shown inside the hand-off summary).
    uid = one("SELECT id FROM users WHERE email='handoff@example.invalid'")['id']
    from app import declarations, container_returns
    declarations.init(); container_returns.init()
    with db() as c:
        c.execute('''INSERT INTO customs_declarations(customer_name,customer_phone,declaration_number,port,stage,created_by,created_at,updated_at)
            VALUES('مؤسسة النخبة','0551112233','418777','ميناء جدة الإسلامي','duties_due',%s,%s,%s)''', (uid, now, now))
        c.execute('''INSERT INTO customs_declarations(customer_name,customer_phone,declaration_number,port,stage,created_by,created_at,updated_at)
            VALUES('مؤسسة أخرى','+966559990000','418778','الدمام','closed',%s,%s,%s)''', (uid, now, now))
        c.execute('''INSERT INTO container_returns(container,customer,customer_phone,free_until,status,created_by,created_at,updated_at)
            VALUES('MSCU1234567','مؤسسة النخبة','966551112233',%s,'open','ناصر',%s,%s)''', (dt.date(2026, 11, 14), now, now))
        c.execute('''INSERT INTO container_returns(container,customer,customer_phone,free_until,status,created_by,created_at,updated_at)
            VALUES('TGHU7654321','مؤسسة النخبة','0551112234',NULL,'open','ناصر',%s,%s)''', (now, now))

    # 5a) Default OFF: an unverified answer only records a suggestion; the conversation is NOT paused.
    j = job('conv-A', '966551112233', 'هل الكراسي عليها سابر؟', natural.SABER_UNVERIFIED_REPLY)
    assert auto_handoff.after_send(j) == 'unverified'
    assert takeover.read_state(ACC, 'conv-A')['paused'] is False
    rows = auto_handoff.latest(ACC, 'conv-A')
    assert len(rows) == 1 and rows[0]['mode'] == 'suggested' and 'لم يُوقف' in rows[0]['summary']
    assert 'بيان 418777' in rows[0]['summary'] and 'هل الكراسي عليها سابر' in rows[0]['summary'], rows[0]['summary']
    # Duplicate suggestions within the cooldown are not repeated.
    assert auto_handoff.after_send(job('conv-A', '966551112233', 'وكم الجمارك؟', natural.TARIFF_UNVERIFIED_REPLY)) == 'unverified'
    assert len(auto_handoff.latest(ACC, 'conv-A')) == 1
    # Normal answers trigger nothing.
    assert auto_handoff.after_send(job('conv-A', '966551112233', 'شكرا', 'العفو')) is None

    # 5b) Enabled: repeated identical message (3 in 30 min) pauses ONLY this conversation and blocks its pending job.
    with patch.dict(os.environ, {'AUTO_HANDOFF_ENABLED': '1'}):
        for m in (20, 10):
            job('conv-B', '966552223344', 'وين شحنتي؟', 'جاري التحقق', minutes_ago=m)
        pending = job('conv-B', '966552223344', 'سؤال آخر', None, status='pending')
        other = job('conv-C', '966553334455', 'مرحبا', None, status='pending')
        last = job('conv-B', '966552223344', 'وين  شحنتي ؟', 'جاري التحقق')
        assert auto_handoff.after_send(last) == 'repeat'
        assert takeover.read_state(ACC, 'conv-B')['paused'] is True
        assert takeover.read_state(ACC, 'conv-C')['paused'] is False
        with db() as c:
            assert c.execute('SELECT status FROM whatsapp_agent_jobs WHERE id=%s', (pending['id'],)).fetchone()['status'] == 'blocked'
            assert c.execute('SELECT status FROM whatsapp_agent_jobs WHERE id=%s', (other['id'],)).fetchone()['status'] == 'pending'
        row = auto_handoff.latest(ACC, 'conv-B')[0]
        assert row['mode'] == 'paused' and 'موقوف لهذه المحادثة فقط' in row['summary']
        # A second trigger on an already-paused conversation does not change the generation.
        gen = takeover.read_state(ACC, 'conv-B')['generation']
        auto_handoff.handoff(ACC, 'conv-B', '966552223344', 'unverified')
        assert takeover.read_state(ACC, 'conv-B')['generation'] == gen and auto_handoff.latest(ACC, 'conv-B')[0]['mode'] == 'already_paused'
        # Manual resume is unchanged and explicit.
        takeover.set_paused(ACC, 'conv-B', False, 'manager-1', gen, sender='966552223344')
        assert takeover.read_state(ACC, 'conv-B')['paused'] is False
        # Staff intervention pauses that conversation.
        auto_handoff.staff_sent(ACC, 'conv-D', '966554445566', 7)
        assert takeover.read_state(ACC, 'conv-D')['paused'] is True
        # Disabled trigger list → suggestion only.
        with patch.dict(os.environ, {'AUTO_HANDOFF_TRIGGERS': 'staff'}):
            auto_handoff.handoff(ACC, 'conv-E', '966555556677', 'repeat')
            assert takeover.read_state(ACC, 'conv-E')['paused'] is False
    # Default OFF again: staff intervention only suggests.
    auto_handoff.staff_sent(ACC, 'conv-F', '966556667788', 7)
    assert takeover.read_state(ACC, 'conv-F')['paused'] is False and auto_handoff.latest(ACC, 'conv-F')[0]['mode'] == 'suggested'

    # 6) Customer → shipments (exact phone only; closed declarations excluded; container date is the next date).
    from app import customer_shipments as cs
    with db() as c:
        groups = cs.grouped(c)
        mine = [g for g in groups if g['phone'] == '966551112233']
        assert len(mine) == 1 and {s['ref'] for s in mine[0]['shipments']} == {'بيان 418777', 'حاوية MSCU1234567'}
        assert mine[0]['next_date'] == dt.date(2026, 11, 14)
        decl = next(s for s in mine[0]['shipments'] if s['ref'] == 'بيان 418777')
        assert decl['next_step'].startswith('سداد الرسوم') and decl['responsible'] and decl['status'] == 'بانتظار سداد الرسوم'
        assert not any('418778' in s['ref'] for g in groups for s in g['shipments'])
        # A different number (one digit off) is NOT merged into this customer.
        assert any(g['phone'] == '966551112234' for g in groups)
        assert cs.for_phone(c, '+966 55 111 2233') and not cs.for_phone(c, '2233')
        html = cs.section_html(c)
    assert 'الشحنات حسب العميل' in html and 'MSCU1234567' in html and '2026-11-14' in html
    # Inbox rendering shows the summary next to the existing manual control.
    import asyncio
    from app import whatsapp_inbox as inbox
    rendered = asyncio.run(inbox.takeover_render(ACC, 'conv-A', '966551112233', 'csrf'))
    assert 'إيقاف الرد الآلي لهذه المحادثة' in rendered and 'يُقترح التسليم للموظف' in rendered
    print('PASS: hand-off off by default (shadow), per-conversation pause when enabled, repeats/staff/unverified; customer shipments.')
finally:
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute('DROP SCHEMA ' + schema + ' CASCADE')
