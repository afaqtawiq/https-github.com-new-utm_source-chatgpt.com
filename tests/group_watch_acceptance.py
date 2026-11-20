"""WhatsApp group watch: the 19 Nov case (partner group, two packing lists + «can you pls check the HS CODE whether they
required any approval», no answer for an hour) → alert after 30 minutes with the next step (فيصل), escalation after 2 hours,
nothing when a team member or the business number answered; small talk ignored; polling fallback when group events are
not pushed. Isolated PostgreSQL; provider reads and delivery simulated; nothing is posted anywhere."""
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
T0 = dt.datetime(2026, 11, 19, 10, 0, tzinfo=dt.timezone.utc)   # 13:00 Riyadh
TEAM = '966507150680'                                            # رامي


def event(mid, text='', files=0, at=T0, sender='971501112233', name='عمران ناقل R 2', group='Beswa cargo uae', cid='grp-1'):
    return {'event': 'message.received', 'id': 'ev-' + mid, 'account': {'accountId': 'acc-1', 'platform': 'whatsapp'},
            'conversation': {'id': cid, 'isGroup': True, 'name': group},
            'message': {'id': mid, 'direction': 'incoming', 'text': text, 'createdAt': at.isoformat(),
                        'sender': {'phoneNumber': '+' + sender, 'name': name},
                        'attachments': [{'type': 'document', 'fileName': f'_ PL 32{i} KMC POTATO GRANULES.pdf'} for i in range(files)]}}


def run():
    from app.bootstrap import app  # noqa: F401
    from app import group_watch as gw, no_wait, statement_groups
    from app import zernio_whatsapp as z
    from app.storage import db
    gw.init()
    m = dt.timedelta(minutes=1)
    assert gw.capture(event('m1', files=1, at=T0)) and gw.capture(event('m2', files=1, at=T0 + m))
    assert gw.capture(event('m3', 'This another shipment required 3rd party license charges.\n\ncan you pls check the HS CODE '
                                  'whether they required any approval.', at=T0 + 2 * m))
    assert not gw.capture(event('m3', 'dup', at=T0 + 2 * m)), 'idempotent'
    assert gw.capture(event('m4', 'Thanks', at=T0 + 3 * m, sender='971509998887', name='Ali', cid='grp-2', group='Other'))
    assert not gw.capture({'event': 'message.received', 'conversation': {'id': 'c', 'isGroup': False}, 'message': {}})
    with db() as c:
        flags = {r['message_id']: r['important'] for r in c.execute('SELECT message_id, important FROM whatsapp_group_messages')}
    assert flags == {'m1': True, 'm2': True, 'm3': True, 'm4': False}, flags

    sent = []

    async def deliver(text):
        sent.append(text)

    async def not_answered(*a, **k):
        return False
    with patch.object(no_wait, 'answered_after', side_effect=not_answered):
        assert asyncio.run(gw.check(T0 + 20 * m, deliver)) == []
        out = asyncio.run(gw.check(T0 + 35 * m, deliver))
        assert len(out) == 1, out
        text = out[0]
        assert '📣' in text and 'Beswa cargo uae' in text and 'عمران ناقل R 2' in text and 'HS CODE' in text, text
        assert 'مع 2 ملف' in text and 'فيصل' in text and 'POTATO GRANULES' in text, text
        assert asyncio.run(gw.check(T0 + 40 * m, deliver)) == []
        esc = asyncio.run(gw.check(T0 + 125 * m, deliver))
        assert len(esc) == 1 and esc[0].startswith('🚨 تصعيد') and 'ساعة' in esc[0], esc
        assert asyncio.run(gw.check(T0 + 300 * m, deliver)) == [], 'max two alerts per burst'
    assert 'Beswa cargo uae' in gw.list_text(T0 + 130 * m)

    # Another burst, answered by رامي in the group → no alert.
    with patch.dict(os.environ, {'AFAQ_TEAM': json.dumps([{'phone': '+' + TEAM, 'name': 'رامي'}])}):
        T1 = T0 + dt.timedelta(hours=5)
        gw.capture(event('n1', 'Kindly share the rate for 2x40HC Jebel Ali to Riyadh', at=T1))
        gw.capture(event('n2', 'تمام نشيك ونرد عليك', at=T1 + 5 * m, sender=TEAM, name='رامي'))
        with patch.object(no_wait, 'answered_after', side_effect=not_answered):
            assert asyncio.run(gw.check(T1 + 40 * m, deliver)) == []
        with db() as c:
            assert c.execute("SELECT answered_at FROM whatsapp_group_messages WHERE message_id='n1'").fetchone()['answered_at']

    # Answered from the business number (provider shows an outgoing message) → closed silently.
    T2 = T0 + dt.timedelta(hours=8)
    gw.capture(event('p1', 'When is the ETA for the KMC containers?', at=T2))

    async def answered(*a, **k):
        return True
    with patch.object(no_wait, 'answered_after', side_effect=answered):
        assert asyncio.run(gw.check(T2 + 40 * m, deliver)) == []

    # Polling fallback (no group webhooks): new group messages are read from the provider.
    T3 = T0 + dt.timedelta(hours=10)

    async def groups():
        return [('grp-9', 'Sea Line Partners')]

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def read(client, path, params=None):
        assert path == '/inbox/conversations/grp-9/messages'
        return {'messages': [{'id': 'q1', 'direction': 'incoming', 'message': 'Please confirm the clearance charges for BL MEDU1234567',
                              'createdAt': T3.isoformat(), 'sender': {'phoneNumber': '+201001112223', 'name': 'Hany'}}]}
    with patch.object(statement_groups, 'groups', side_effect=groups), patch.object(z, 'client', lambda: Client()), \
            patch.object(z, 'read', side_effect=read), patch.object(z, 'account_id', lambda: 'acc-1'):
        assert asyncio.run(gw.poll(T3)) == 1 and asyncio.run(gw.poll(T3)) == 0
    with patch.object(no_wait, 'answered_after', side_effect=not_answered):
        out = asyncio.run(gw.check(T3 + 31 * m, deliver))
    assert len(out) == 1 and 'Sea Line Partners' in out[0] and 'Hany' in out[0], out


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'group_watch_' + secrets.token_hex(5)
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
    print('PASS: group watch — important group message alert after 30 min + escalation, team/business answers close it, small talk ignored, polling fallback.')


if __name__ == '__main__':
    main()
