"""Real app/SQL acceptance in a disposable local PostgreSQL schema only.

Run: AFAAQ_TEST_DATABASE_URL=postgresql://...@localhost/afaaq_test python tests/customer_followup_postgres_acceptance.py
No provider inbox reads, customer sends, or production data are used.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import sys
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run():
    import httpx
    from psycopg import sql
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app.storage import db, get_session, create_session, hash_password
    from app.whatsapp_agent_store import init_storage
    from app.whatsapp_takeover import init_storage as init_takeovers
    from app.whatsapp_inbox import ensure

    # Optional local stores are initialized using their actual application DDL.
    init_storage()
    init_takeovers()
    with db() as c:
        ensure(c)
    at = datetime(2026, 11, 6, 22, tzinfo=timezone.utc)  # Nov 7 Riyadh.
    secret_body = 'PRIVATE_BODY_MUST_NOT_APPEAR'
    manual_token = 'PRIVATE_MANUAL_TOKEN_MUST_NOT_APPEAR'
    account = 'fixture-wa-own'
    phone, foreign_phone = '+12025550101', '+12025550102'
    own, foreign = 'buyer@example.invalid', 'foreign@example.invalid'
    paths = ('/customer-followup', '/api/v7/customer-followup',
             '/api/v7/customer-followup/digest?day=2026-11-07')
    client = TestClient(app, base_url='http://testserver',
                        headers={'origin': 'http://testserver'}, follow_redirects=False)
    status_path = '/api/v7/customer-followup/digest-status'
    for path in (*paths, status_path):
        r = client.get(path)
        assert r.status_code in (401, 303), (path, r.status_code)
        assert own not in r.text
    r = client.post('/login', data={'email': os.environ['ADMIN_EMAIL'],
                                  'password': os.environ['ADMIN_PASSWORD']})
    assert r.status_code == 303, r.text
    session = get_session(client.cookies.get('gla_session'))
    uid = session['user_id']

    def insert(c, table, **values):
        query = sql.SQL('INSERT INTO {} ({}) VALUES ({}) RETURNING *').format(
            sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, values)),
            sql.SQL(',').join(sql.Placeholder() for _ in values))
        return dict(c.execute(query, tuple(values.values())).fetchone())

    with db() as c:
        other = insert(c, 'users', email='other@example.invalid', name='Fixture other',
                       role='admin', password_hash=hash_password(secrets.token_urlsafe(24)), created_at=at)['id']
        viewer = insert(c, 'users', email='viewer@example.invalid', name='Fixture viewer',
                        role='viewer', password_hash=hash_password(secrets.token_urlsafe(24)), created_at=at)['id']
        aid = insert(c, 'accounts', name='Fixture <script>bad()</script>', phone=phone,
                     email=own, created_at=at, updated_at=at)['id']
        insert(c, 'customer_directory', company_name='Fixture directory', phone=phone,
               email=own, created_at=at, updated_at=at)
        insert(c, 'daily_prospects', source_key='fixture-prospect', company_name='Fixture prospect',
               phone=phone, email=own, score=0, segment='fixture', reason='fixture',
               message=secret_body, message_source='fixture', batch_date=at.date(), created_at=at, updated_at=at)
        campaign = insert(c, 'customer_campaigns', campaign_key='fixture-campaign', title='Fixture',
                          subject='Fixture', plain_template=secret_body, html_template=secret_body,
                          brochure_url='https://example.invalid/fixture', unsubscribe_base='https://example.invalid',
                          created_by=uid, created_at=at)['id']
        for owner, address in ((uid, own), (other, foreign)):
            insert(c, 'sales_prospects', company_name='Fixture prospect', recipient=address, mail_user_id=owner,
                   source_url='https://example.invalid', source_email=address, identity_name='Fixture',
                   confidence='fixture', verified_at=at, exclusion_basis='fixture', created_by=owner,
                   created_at=at, updated_at=at)
            insert(c, 'outbound_messages', recipient=address, channel='email', status='sent',
                   body=secret_body, mail_user_id=owner, provider_message_id='email-' + str(owner),
                   sent_at=at, created_at=at, updated_at=at)
            insert(c, 'spacemail_inbox', user_id=owner, uidvalidity='fixture', uid=1,
                   message_id='in-' + str(owner), sender_address=address, body=secret_body, imported_at=at)
            insert(c, 'customer_campaign_recipients', campaign_id=campaign, channel='email', recipient=address,
                   company_name='Fixture', sources='fixture', unsubscribe_token='unsubscribe-' + str(owner),
                   sender_user_id=owner, status='sent', provider_message_id='email-' + str(owner), sent_at=at)
        # An unowned legacy email must not be attributed to the signed-in mailbox.
        insert(c, 'customer_campaign_recipients', campaign_id=campaign, channel='email',
               recipient='unowned@example.invalid', company_name='Fixture', sources='fixture',
               unsubscribe_token='unsubscribe-unowned', status='sent', sent_at=at)
        insert(c, 'customer_campaign_recipients', campaign_id=campaign, channel='whatsapp', recipient=phone,
               company_name='Fixture', sources='fixture', unsubscribe_token='unsubscribe-wa',
               status='sent', provider_message_id='wa-out', sent_at=at)
        for scope, sender in ((account, phone), ('fixture-wa-other', foreign_phone)):
            job = insert(c, 'whatsapp_agent_jobs', account_id=scope, sender=sender, message_id='wa-in',
                         event_id='event', conversation_id='conversation', payload=secret_body,
                         status='sent', idempotency_key=scope, created_at=at, updated_at=at)['id']
            insert(c, 'whatsapp_agent_outbox', job_id=job, idempotency_key=scope,
                   status='sent', provider_message_id='wa-out', updated_at=at)
            insert(c, 'whatsapp_takeover_receipts', account_id=scope, sender=sender, message_id='wa-in',
                   conversation_id='conversation', body=secret_body, attachment_count=0, generation=0, received_at=at)
            insert(c, 'whatsapp_inbox_drafts', token=manual_token + scope, account_id=scope,
                   conversation_id='conversation', recipient=sender, body=secret_body, created_by=uid,
                   state='sent', provider_message_id='wa-manual', created_at=at, updated_at=at)
            insert(c, 'whatsapp_conversation_takeovers', account_id=scope, conversation_id='conversation',
                   sender=sender, paused=True, updated_at=at)
        insert(c, 'marketing_suppressions', channel='email', recipient=own, created_at=at)
        oid = insert(c, 'opportunities', account_id=aid, company_name='Fixture opportunity',
                     stage='qualified', created_at=at, updated_at=at)['id']
        insert(c, 'sales_outcomes', opportunity_id=oid, outcome='won', recorded_at=at)
        insert(c, 'sales_followups', opportunity_id=oid, due_at=at, created_at=at)

    tables = ('accounts', 'customer_directory', 'daily_prospects', 'sales_prospects',
              'customer_campaigns', 'customer_campaign_recipients', 'outbound_messages', 'spacemail_inbox',
              'whatsapp_agent_jobs', 'whatsapp_agent_outbox', 'whatsapp_takeover_receipts',
              'whatsapp_inbox_drafts', 'whatsapp_conversation_takeovers', 'marketing_suppressions',
              'sales_followups', 'opportunities', 'sales_outcomes')

    def fingerprints():
        with db() as c:
            # Full rows, including bodies/status/timestamps: detect any GET mutation.
            result = {}
            for table in tables:
                rows = c.execute(sql.SQL('SELECT row_to_json(t)::text AS value FROM {} t').format(sql.Identifier(table))).fetchall()
                content = json.dumps(sorted(r['value'] for r in rows)).encode()
                result[table] = hashlib.sha256(content).hexdigest()
            return result

    before = fingerprints()
    # Block provider HTTP even if a future regression swallows transport errors.
    with patch.object(httpx.HTTPTransport, 'handle_request', side_effect=AssertionError('External HTTP forbidden')) as sync_http, \
         patch.object(httpx.AsyncHTTPTransport, 'handle_async_request', side_effect=AssertionError('External HTTP forbidden')) as async_http:
        responses = [client.get(path) for path in paths]
        for response in responses:
            assert response.status_code == 200, response.text
            assert response.headers['cache-control'] == 'no-store'
            assert response.headers['referrer-policy'] == 'no-referrer'
            assert secret_body not in response.text and manual_token not in response.text
            assert foreign not in response.text and foreign_phone not in response.text
            assert 'unowned@example.invalid' not in response.text
        page, api, summary = responses
        assert '<script>bad()</script>' not in page.text
        assert '&lt;script&gt;bad()&lt;/script&gt;' in page.text
        data = api.json()
        coverage = {r['source']: r for r in data['coverage']}
        expected = set(tables) - {'customer_campaigns', 'sales_outcomes', 'whatsapp_agent_outbox'}
        assert set(coverage) == expected, coverage
        assert all(r['status'] == 'read' and r['rows'] > 0 for r in coverage.values()), coverage
        assert data['external_actions'] is False and data['complete'] is False
        contacts = {(r['channel'], r['scope'], r['recipient']): r for r in data['contacts']}
        email = contacts['email', str(uid), own]
        assert email['attempts'] == 1 and email['inbound_observations'] == 1
        assert email['suppressed'] is True and email['next_action'] == 'suppressed'
        wa = contacts['whatsapp', account, phone]
        assert wa['attempts'] == 2 and wa['inbound_observations'] == 1
        assert wa['paused'] is True and wa['next_action'] == 'paused'
        assert wa['delivery'] == wa['human_reply'] == 'not_verified'
        legacy = contacts['whatsapp', 'legacy_campaign_unscoped', phone]
        assert legacy['attempts'] == 1 and legacy['paused'] is None
        assert data['crm_followups'][0]['recorded_outcome'] == 'won'
        assert data['crm_opportunities'][0]['id'] == oid
        digest = summary.json()
        assert digest['timezone'] == 'Asia/Riyadh' and digest['counts_are_partial'] is True
        assert digest['attempted_endpoints'] == 2 and digest['inbound_endpoints'] == 2
        assert digest['currently_open_crm_due_by_day_end'] == 1
        assert client.get('/api/v7/customer-followup/digest?day=not-a-date').status_code == 422
        assert client.post('/api/v7/customer-followup', data={'csrf': session['csrf']}).status_code == 405

        restricted = TestClient(app, base_url='http://testserver', follow_redirects=False)
        restricted.cookies.set('gla_session', create_session(viewer)[0])
        for path in (*paths, status_path):
            assert restricted.get(path).status_code == 403
        restricted.close()
        # Real stored permission override, not a mocked authority function.
        with db() as c:
            insert(c, 'role_permissions', role='admin', permission='manage_gmail', allowed=0, updated_at=at)
        try:
            denied = client.get('/api/v7/customer-followup')
            assert denied.status_code == 200
            assert not any(r['channel'] == 'email' for r in denied.json()['contacts'])
            assert own not in denied.text and foreign not in denied.text
            denied_coverage = {r['source']: r['status'] for r in denied.json()['coverage']}
            for source in ('sales_prospects', 'outbound_messages', 'spacemail_inbox'):
                assert denied_coverage[source] == 'not_authorized_or_configured'
            for path in (paths[0], paths[2]):
                redacted = client.get(path)
                assert redacted.status_code == 200
                assert own not in redacted.text and foreign not in redacted.text
            assert client.get(paths[2]).json()['attempted_endpoints'] == 1
        finally:
            with db() as c:
                c.execute("DELETE FROM role_permissions WHERE role='admin' AND permission='manage_gmail'")

        # Isolated disposable schema only. Rename optional tables reversibly to
        # exercise actual PostgreSQL undefined-table errors and savepoint recovery.
        missing = ('marketing_suppressions', 'whatsapp_conversation_takeovers', 'whatsapp_inbox_drafts')
        with db() as c:
            for table in missing:
                c.execute(sql.SQL('ALTER TABLE {} RENAME TO {}').format(sql.Identifier(table), sql.Identifier(table + '_hidden')))
        try:
            partial = client.get('/api/v7/customer-followup')
            assert partial.status_code == 200, partial.text
            reduced = partial.json()
            statuses = {r['source']: r['status'] for r in reduced['coverage']}
            assert all(statuses[name] == 'unavailable' for name in missing)
            assert statuses['sales_followups'] == statuses['opportunities'] == 'read'
            scoped = next(r for r in reduced['contacts'] if r['channel'] == 'whatsapp' and r['scope'] == account)
            assert scoped['suppressed'] is None and scoped['paused'] is None
            assert scoped['next_action'] == 'safety_review' and scoped['safety_state_complete'] is False
            assert 'UndefinedTable' not in partial.text and '_hidden' not in partial.text
        finally:
            with db() as c:
                for table in missing:
                    c.execute(sql.SQL('ALTER TABLE {} RENAME TO {}').format(sql.Identifier(table + '_hidden'), sql.Identifier(table)))
        # The real database unique-day key must serialize competing workers.
        # Test the ledger directly; never enable or call a sending worker.
        from app import customer_followup_digest as owner_digest
        owner_phone = '+12025550199'
        owner_hash = hashlib.sha256(owner_phone.encode()).hexdigest()
        day = at.date()
        with patch.dict(os.environ, {'CUSTOMER_FOLLOWUP_DIGEST_ENABLED': '0',
                                     'ENABLE_EXTERNAL_ACTIONS': '0',
                                     'WHATSAPP_COMMAND_OWNER': owner_phone,
                                     'CUSTOMER_FOLLOWUP_OWNER_SHA256': owner_hash}):
            initial = client.get(status_path)
            assert initial.status_code == 200, initial.text
            assert initial.json()['latest_attempt'] is None
            with ThreadPoolExecutor(max_workers=8) as pool:
                claims = list(pool.map(lambda _: owner_digest.claim(day, owner_hash), range(8)))
            assert sum(claims) == 1, claims
            with db() as c:
                ledger = c.execute('SELECT * FROM owner_followup_delivery').fetchall()
            assert len(ledger) == 1 and ledger[0]['status'] == 'prepared'
            assert ledger[0]['recipient_sha256'] == owner_hash
            for state, message_id, detail in (
                ('prepared', None, ''),
                ('accepted', 'fixture-provider-private-id', 'provider_acceptance_not_delivery'),
                ('uncertain', None, 'send_outcome_uncertain'),
            ):
                owner_digest.record(day, state, message_id, detail)
                with db() as c:
                    expected_ledger = c.execute('SELECT * FROM owner_followup_delivery').fetchall()
                response = client.get(status_path)
                assert response.status_code == 200, response.text
                assert response.headers['cache-control'] == 'no-store'
                assert response.headers['referrer-policy'] == 'no-referrer'
                status = response.json()
                assert status['enabled'] is False and status['configuration_state'] == 'disabled'
                assert status['existing_owner_worker_enabled'] is False
                assert status['owner_suffix'] == '199' and status['owner_matches_verified_recipient'] is True
                assert status['latest_attempt']['status'] == state
                assert status['latest_attempt']['day'] == day.isoformat()
                assert status['latest_attempt']['detail_code'] == detail
                assert owner_phone not in response.text and owner_hash not in response.text
                assert 'fixture-provider-private-id' not in response.text
                assert 'recipient_sha256' not in response.text and 'provider_message_id' not in response.text
                with db() as c:
                    assert c.execute('SELECT * FROM owner_followup_delivery').fetchall() == expected_ledger
                assert not owner_digest.claim(day, owner_hash), 'A recorded day must never become claimable again'
        sync_http.assert_not_called()
        async_http.assert_not_called()
    assert fingerprints() == before, 'Read-only GET changed source records'
    client.close()
    print('PASS: real app/PostgreSQL source SQL, scoped evidence, auth/mail permissions, read-only GET, missing-source safety, concurrent owner claims and private status, no external calls.')


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    target = urlsplit(url)
    if (target.scheme not in ('postgres', 'postgresql') or target.hostname not in ('localhost', '127.0.0.1')
            or target.path != '/afaaq_test' or target.query or target.fragment):
        raise RuntimeError('Requires local disposable afaaq_test without URL parameters')
    schema = 'customer_followup_test_' + secrets.token_hex(6)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    connect = socket.socket.connect
    attempts = []

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ('localhost', '127.0.0.1', '::1'):
            attempts.append(address)
            raise AssertionError('External network forbidden')
        return connect(sock, address)

    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema + ' -c statement_timeout=30000 -c lock_timeout=15000'}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0',
               'CUSTOMER_FOLLOWUP_DIGEST_ENABLED': '0', 'AFAQ_OWNER_ALERTS': '0',
               'ADMIN_EMAIL': 'followup-admin@example.invalid', 'ADMIN_PASSWORD': secrets.token_urlsafe(32),
               'BROWSER_COOKIE_SECURE': '0', 'ZERNIO_WHATSAPP_ACCOUNT_ID': 'fixture-wa-own',
               'WHATSAPP_COMMAND_ACCOUNT_ID': 'fixture-wa-own'}
        with patch.dict(os.environ, env), patch.object(socket.socket, 'connect', local_only):
            run()
        assert not attempts, 'Application attempted external network access'
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    main()
