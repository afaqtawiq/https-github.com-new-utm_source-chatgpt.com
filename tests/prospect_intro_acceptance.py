"""Sara prospect intros: disposable local PostgreSQL, fixture sources and fake mail.

Run explicitly with AFAAQ_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:PORT/afaaq_test.
No production database, real contacts, public HTTP requests or live SMTP are allowed.
"""
import asyncio
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from email.utils import formatdate
import os
from pathlib import Path
import secrets
import socket
import sys
from unittest.mock import MagicMock, patch
from urllib.parse import quote, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run():
    from fastapi.testclient import TestClient
    from app.bootstrap import app
    from app import discovery, outbound, official_sales, official_replies, prospect_outreach as prospects, spacemail as mail
    from app.storage import db, one, rows, execute, utcnow, get_session, create_session, hash_password

    client = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'}, follow_redirects=False)
    login = client.post('/login', data={'email': os.environ['ADMIN_EMAIL'], 'password': os.environ['ADMIN_PASSWORD']})
    assert login.status_code == 303, login.text
    session = get_session(client.cookies.get('gla_session'))
    uid, csrf = session['user_id'], {'csrf': session['csrf']}
    now = utcnow()
    with db() as c:
        c.execute('INSERT INTO spacemail_connections(user_id,password_enc,enabled,updated_at) VALUES(%s,%s,TRUE,%s)',
                  (uid, mail.cipher().encrypt(b'fixture-only-not-a-real-secret').decode(), now))
        c.execute('INSERT INTO user_mfa(user_id,mfa_enabled,updated_at) VALUES(%s,1,%s)', (uid, now))
        c.execute("INSERT INTO stepup_auth(session_id,user_id,verified_at,expires_at) VALUES(%s,%s,NOW(),NOW()+INTERVAL '30 minutes')", (session['id'], uid))

    pages = {}
    def data(slug, **changes):
        name, recipient, url = 'Fixture '+slug+' Trading', slug+'@'+slug+'.example.invalid', 'https://'+slug+'.example.invalid/contact'
        value = {'company_name': name, 'recipient': recipient, 'source_url': url, 'identity_name': name,
                 'confidence': 'exact_legal', 'official_source_confirmed': 'yes',
                 'exclusion_basis': 'owner_confirmed_not_current_customer', 'customer_exclusion_confirmed': 'yes',
                 'subject': 'Introduction: '+name, 'body': 'An introduction only. Reply STOP to opt out.'}
        value.update(changes)
        pages[url] = {'url': url, 'title': name, 'request_text': name+' Official contact: '+recipient,
                      'excerpt': name+' Official contact: '+recipient, 'detail_extracted': False}
        return value

    def source(url):
        assert url in pages, 'Unexpected source fetch: '+str(url)
        return dict(pages[url])

    def count(table):
        assert table in {'sales_prospects', 'outbound_messages', 'accounts', 'opportunities', 'sales_followups', 'approvals', 'official_reply_log'}
        return one('SELECT COUNT(*) n FROM '+table)['n']

    def post(path, values=None, expected=303):
        response = client.post(path, data={**csrf, **(values or {})})
        assert response.status_code == expected, (path, response.status_code, response.text)
        return response

    def create(slug, **changes):
        response = post('/sales-prospects/create', data(slug, **changes))
        mid = int(urlsplit(response.headers['location']).path.rsplit('/', 1)[1])
        m = one('SELECT * FROM outbound_messages WHERE id=?', (mid,))
        assert m['purpose'] == 'intro_prospect' and m['opportunity_id'] is None and m['prospect_id']
        assert m['mail_user_id'] == uid and m['status'] == 'draft' and not m.get('proposal_text')
        p = one('SELECT * FROM sales_prospects WHERE id=?', (m['prospect_id'],))
        assert p['status'] == 'prospect_verified' and p['source_email'] == p['recipient'] == m['recipient']
        return mid, p

    def approve(mid):
        base = '/outbound/'+str(mid)
        post(base+'/request-approval')
        post(base+'/approve')
        message = one('SELECT * FROM outbound_messages WHERE id=?', (mid,))
        assert len(message['approval_digest']) == 64
        assert message['approval_digest'] == prospects.content_digest(message)
        return base

    def suppress(recipient):
        with db() as c:
            c.execute("INSERT INTO marketing_suppressions(channel,recipient,created_at) VALUES('email',%s,%s) ON CONFLICT DO NOTHING", (recipient, now))

    def prior_campaign(recipient, status='sent'):
        campaign = execute('''INSERT INTO customer_campaigns(campaign_key,title,subject,plain_template,html_template,
            brochure_url,unsubscribe_base,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)''',
            ('fixture-'+secrets.token_hex(5), 'Fixture campaign', 'Fixture', 'Fixture', 'Fixture',
             'https://example.invalid/brochure', 'https://example.invalid/unsubscribe/', uid, now))
        return execute('''INSERT INTO customer_campaign_recipients(campaign_id,channel,recipient,company_name,sources,
            unsubscribe_token,status) VALUES(?,?,?,?,?,?,?)''',
            (campaign, 'email', recipient, 'Unrelated campaign fixture', '[]', secrets.token_hex(16), status))

    baseline = {table: count(table) for table in ('accounts', 'opportunities', 'sales_followups')}
    # Fixtures replace only public source fetching; verification itself remains real.
    with patch.object(discovery, 'fetch_public', side_effect=source) as fetched, \
         patch.object(mail, 'smtp_login', side_effect=AssertionError('Unexpected SMTP before approved send')):
        anonymous = TestClient(app, base_url='http://testserver', follow_redirects=False)
        assert anonymous.post('/sales-prospects/create', data=data('anonymous')).status_code in (303, 401)
        assert count('sales_prospects') == 0
        assert client.post('/sales-prospects/create', data={**data('bad-csrf'), 'csrf': 'wrong'}).status_code == 403
        for field, value in [('confidence', 'guess'), ('official_source_confirmed', 'no'),
                             ('customer_exclusion_confirmed', 'no'), ('exclusion_basis', ''),
                             ('identity_name', 'Unrelated Legal Entity')]:
            invalid = data('invalid-'+field, **{field: value})
            response = client.post('/sales-prospects/create', data={**csrf, **invalid})
            assert response.status_code in (400, 409), (field, response.status_code, response.text)
            assert count('sales_prospects') == 0 and count('outbound_messages') == 0

        mid, first = create('first')
        assert fetched.call_count >= 1
        assert {table: count(table) for table in baseline} == baseline
        assert client.get('/outbound/'+str(mid)).status_code == 200
        assert any(m['id'] == mid for m in client.get('/api/v7/outbound').json()['messages'])
        assert first['company_name'] in client.get('/outbound').text
        assert first['company_name'] in client.get('/sales-prospects').text
        post('/sales-prospects/'+str(first['id'])+'/qualification', {'needs': 'No reply exists'}, 409)
        post('/sales-prospects/create', data('first'), 409)
        post('/outbound/'+str(mid)+'/send', expected=409)
        post('/outbound/'+str(mid)+'/update', {'recipient': 'replacement@example.invalid', 'subject': 'Replacement', 'body': 'Replacement'}, 409)
        post('/outbound/'+str(mid)+'/update', {'recipient': first['recipient'], 'subject': 'Fixture approved subject',
                                             'body': 'Exact approved introduction. Reply STOP to opt out.', 'proposal_text': 'NEVER TRANSMIT'})
        assert not one('SELECT proposal_text FROM outbound_messages WHERE id=?', (mid,))['proposal_text']
        base = approve(mid)
        post(base+'/update', {'recipient': first['recipient'], 'subject': 'Changed', 'body': 'Changed'}, 409)
        post(base+'/approve', expected=409)
        assert client.post(base+'/send', data={'csrf': 'wrong'}).status_code == 403

        # Existing contacts are blocked by destination or legal identity, regardless of status.
        for kind in ('account-email', 'account-name', 'directory-email', 'directory-name', 'directory-domain', 'account-domain', 'suppression', 'prior-outbound', 'prior-campaign'):
            value = data(kind)
            if kind.startswith('account'):
                execute('INSERT INTO accounts(name,email,created_at,updated_at) VALUES(?,?,?,?)',
                        (value['company_name'] if kind.endswith('name') else 'Existing account fixture',
                         value['recipient'].upper() if kind.endswith('email') else ('info@'+value['recipient'].split('@')[1] if kind.endswith('domain') else 'other-account@example.invalid'), now, now))
            elif kind.startswith('directory'):
                execute('INSERT INTO customer_directory(company_name,email,created_at,updated_at) VALUES(?,?,?,?)',
                        (value['company_name'] if kind.endswith('name') else 'Existing directory fixture',
                         value['recipient'].upper() if kind.endswith('email') else ('info@'+value['recipient'].split('@')[1] if kind.endswith('domain') else 'other-directory@example.invalid'), now, now))
            elif kind == 'suppression':
                suppress(value['recipient'])
            elif kind == 'prior-outbound':
                execute('INSERT INTO outbound_messages(recipient,subject,body,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                        (value['recipient'].upper(), 'Legacy campaign', 'Fixture', 'sent', uid, now, now))
            else:
                prior_campaign(value['recipient'].upper())
            before = count('sales_prospects'), count('outbound_messages')
            post('/sales-prospects/create', value, 409)
            assert (count('sales_prospects'), count('outbound_messages')) == before

        # Concurrent drafts and normalized recipient casing cannot produce duplicate intro rows.
        race = data('creation-race')
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: client.post('/sales-prospects/create', data={**csrf, **race}), range(4)))
        assert all(r.status_code in (303, 409) for r in responses), [(r.status_code, r.text) for r in responses]
        assert any(r.status_code == 303 for r in responses)
        assert one('SELECT COUNT(*) n FROM sales_prospects WHERE lower(recipient)=?', (race['recipient'],))['n'] == 1
        assert one("SELECT COUNT(*) n FROM outbound_messages WHERE lower(recipient)=? AND purpose='intro_prospect'", (race['recipient'],))['n'] == 1
        post('/sales-prospects/create', {**race, 'recipient': race['recipient'].upper()}, 409)

        # All checks run again immediately before claiming the one allowed send.
        with patch.dict(os.environ, {'ENABLE_EXTERNAL_ACTIONS': '0'}):
            post(base+'/send', expected=409)
        with db() as c:
            c.execute("INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES('admin','send_email',0,%s) ON CONFLICT(role,permission) DO UPDATE SET allowed=0", (now,))
        post(base+'/send', expected=403)
        post('/sales-prospects/create', data('permission-block'), 403)
        execute("UPDATE role_permissions SET allowed=1 WHERE role='admin' AND permission='send_email'")
        with db() as c:
            c.execute("INSERT INTO role_permissions(role,permission,allowed,updated_at) VALUES('admin','manage_gmail',0,%s) ON CONFLICT(role,permission) DO UPDATE SET allowed=0", (now,))
        post('/sales-prospects/create', data('mailbox-permission-block'), 403)
        assert client.get(base).status_code == 403
        execute("UPDATE role_permissions SET allowed=1 WHERE role='admin' AND permission='manage_gmail'")
        execute("UPDATE stepup_auth SET expires_at=NOW()-INTERVAL '1 minute' WHERE session_id=?", (session['id'],))
        post(base+'/send', expected=428)
        execute("UPDATE stepup_auth SET expires_at=NOW()+INTERVAL '30 minutes' WHERE session_id=?", (session['id'],))
        with patch.object(outbound, 'connection', return_value={'provider': 'gmail', 'status': 'connected'}):
            post(base+'/send', expected=409)
        approved = one('SELECT * FROM outbound_messages WHERE id=?', (mid,))
        for field, change in [('subject', 'Post-approval subject'), ('body', 'Post-approval body'), ('proposal_text', 'Injected proposal')]:
            execute('UPDATE outbound_messages SET '+field+'=? WHERE id=?', (change, mid))
            post(base+'/send', expected=409)
            execute('UPDATE outbound_messages SET '+field+'=? WHERE id=?', (approved[field], mid))
        aid = approved['approval_id']
        execute('UPDATE approvals SET entity_id=? WHERE id=?', (mid+100000, aid))
        post(base+'/send', expected=409)
        execute('UPDATE approvals SET entity_id=? WHERE id=?', (mid, aid))
        original_page = dict(pages[first['source_url']])
        pages[first['source_url']]['request_text'] = first['company_name']+' without a contact email'
        pages[first['source_url']]['excerpt'] = pages[first['source_url']]['request_text']
        post(base+'/send', expected=409)
        pages[first['source_url']] = original_page

        # Exclusions added after approval remain terminal blockers without invoking the provider.
        for kind in ('suppression', 'account', 'directory', 'campaign', 'outbound'):
            late_mid, p = create('late-'+kind)
            late_base = approve(late_mid)
            if kind == 'suppression':
                suppress(p['recipient'])
            elif kind == 'account':
                execute('INSERT INTO accounts(name,email,created_at,updated_at) VALUES(?,?,?,?)', ('Late account', p['recipient'], now, now))
            elif kind == 'directory':
                execute('INSERT INTO customer_directory(company_name,email,created_at,updated_at) VALUES(?,?,?,?)', ('Late directory', p['recipient'], now, now))
            elif kind == 'campaign':
                prior_campaign(p['recipient'], 'pending')
            else:
                execute('INSERT INTO outbound_messages(recipient,subject,body,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                        (p['recipient'], 'Other pending outreach', 'Fixture', 'draft', uid, now, now))
            post(late_base+'/send', expected=409)
            assert one('SELECT status FROM outbound_messages WHERE id=?', (late_mid,))['status'] == 'approved'

        # Broader CRM routes must not expose this private mailbox to other admins or sales staff.
        for role in ('sales', 'admin'):
            other = execute('INSERT INTO users(email,name,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                            (role+'-prospect@example.invalid', 'Other fixture user', hash_password('local-only'), role, now))
            sid, token, _ = create_session(other)
            stranger = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'}, follow_redirects=False)
            stranger.cookies.set('gla_session', sid)
            assert stranger.get(base).status_code == 403
            assert all(m['id'] != mid for m in stranger.get('/api/v7/outbound').json()['messages'])
            assert first['recipient'] not in stranger.get('/outbound').text
            assert first['recipient'] not in stranger.get('/sales-prospects').text
            assert stranger.post(base+'/update', data={'csrf': token}).status_code == 403
            assert stranger.post(base+'/approve', data={'csrf': token}).status_code == 403
            assert stranger.post(base+'/send', data={'csrf': token}).status_code in (403, 428, 409)

        # At most one SMTP attempt; accepted is not the same as delivery confirmed.
        smtp = MagicMock(); smtp.send_message.return_value = {}
        with patch.object(mail, 'smtp_login', return_value=smtp), \
             patch.object(outbound, 'verify_public_request', side_effect=AssertionError('Intro incorrectly treated as buyer request')):
            with ThreadPoolExecutor(max_workers=4) as pool:
                statuses = list(pool.map(lambda _: client.post(base+'/send', data=csrf).status_code, range(4)))
        assert statuses.count(303) == 1 and statuses.count(409) == 3, statuses
        assert smtp.send_message.call_count == 1
        wire = smtp.send_message.call_args.args[0]
        assert wire['From'] == mail.ADDRESS and wire['To'] == first['recipient']
        assert wire.get_content().strip() == approved['body']
        assert wire['In-Reply-To'] is None and 'NEVER TRANSMIT' not in wire.as_string()
        sent = one('SELECT * FROM outbound_messages WHERE id=?', (mid,))
        assert sent['status'] == 'sent' and sent['provider'] == 'spacemail'
        assert sent['provider_message_id'] == wire['Message-ID']
        assert one('SELECT status FROM sales_prospects WHERE id=?', (first['id'],))['status'] == 'contacted'
        assert count('opportunities') == baseline['opportunities'] and count('sales_followups') == baseline['sales_followups']
        assert 'delivery unconfirmed' in one("SELECT summary FROM activity WHERE action='send_approved_message' AND entity_id=? ORDER BY id DESC LIMIT 1", (mid,))['summary']

        # A timeout or missing provider receipt cannot be automatically retried.
        for slug, failure in [('timeout', TimeoutError('fixture timeout')), ('missing-receipt', None)]:
            uncertain_mid, _ = create(slug)
            uncertain_base = approve(uncertain_mid)
            kwargs = {'side_effect': failure} if failure else {'return_value': None}
            with patch.object(mail, 'send', **kwargs) as attempted:
                post(uncertain_base+'/send', expected=503)
                post(uncertain_base+'/send', expected=409)
                assert attempted.call_count == 1
            assert one('SELECT status FROM outbound_messages WHERE id=?', (uncertain_mid,))['status'] == 'uncertain'

        # Existing public-request messages still require their original buyer evidence.
        ordinary = execute('INSERT INTO opportunities(company_name,source_url,stage,created_at,updated_at) VALUES(?,?,?,?,?)',
                           ('Ordinary fixture', 'https://ordinary.example.invalid/contact', 'new', now, now))
        public_mid = execute('''INSERT INTO outbound_messages(opportunity_id,recipient,subject,body,status,created_by,
            created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)''', (ordinary, 'buyer@ordinary.example.invalid', 'Public', 'Fixture', 'draft', uid, now, now))
        post('/outbound/'+str(public_mid)+'/request-approval')
        post('/outbound/'+str(public_mid)+'/approve')
        with patch.object(outbound, 'verify_public_request', side_effect=ValueError('No buyer request')) as public_guard:
            post('/outbound/'+str(public_mid)+'/send', expected=409)
            public_guard.assert_called_once()

        def raw(identity, body, parent=sent['provider_message_id'], sender=first['recipient']):
            message = EmailMessage()
            message['From'], message['To'] = sender, mail.ADDRESS
            message['Date'], message['Message-ID'], message['Subject'] = formatdate(usegmt=True), identity, 'Re: Introduction'
            if parent: message['In-Reply-To'] = parent
            message.set_content(body)
            return message.as_bytes()

        messages = {1: raw('<ordinary-reply@example.invalid>', 'Thanks for the freight introduction; no request yet.'),
                    2: raw('<unthreaded@example.invalid>', 'customs question', parent=None),
                    3: raw('<wrong-sender@example.invalid>', 'freight quote', sender='someone-else@example.invalid')}
        imap = MagicMock(); imap.response.return_value = ('UIDVALIDITY', [b'1'])
        def command(operation, *args):
            if operation == 'search': return 'OK', [' '.join(str(i) for i in messages).encode()]
            return 'OK', [(b'fixture-meta', messages[int(args[0])])]
        imap.uid.side_effect = command
        before_reply = {table: count(table) for table in ('accounts', 'opportunities', 'outbound_messages', 'sales_followups')}
        with db() as c:
            c.execute("INSERT INTO official_reply_settings(user_id,enabled,enabled_at) VALUES(%s,TRUE,NOW()-INTERVAL '1 hour')", (uid,))
        with patch.object(mail, 'imap_login', return_value=imap), \
             patch.object(mail, 'send', side_effect=AssertionError('Prospect ingestion/receipt sent an automatic email')):
            mail.sync(uid); mail.sync(uid)
            with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(lambda _: official_sales.ingest(uid), range(4)))
            linked = one("SELECT l.*,i.message_id FROM official_mail_links l JOIN spacemail_inbox i ON i.id=l.inbox_id WHERE i.message_id='<ordinary-reply@example.invalid>'")
            assert linked['status'] == 'linked' and linked['matched_outbound_id'] == mid
            assert linked['prospect_id'] == first['id'] and linked['opportunity_id'] is None and linked['account_id'] is None
            assert one('SELECT status FROM sales_prospects WHERE id=?', (first['id'],))['status'] == 'replied'
            assert {table: count(table) for table in before_reply} == before_reply
            assert one('SELECT reply_address FROM spacemail_inbox WHERE id=?', (linked['inbox_id'],))['reply_address'] == first['recipient']
            for row in rows('SELECT id FROM spacemail_inbox WHERE sender_address=?', (first['recipient'],)):
                official_replies.deliver(row['id'])
            assert count('official_reply_log') == 0
        assert one("SELECT COUNT(*) n FROM official_mail_links WHERE status='review'")['n'] == 2
        post('/sales-prospects/'+str(first['id'])+'/qualification', {'needs': 'Fixture customer shared one route; review only', 'voluntary_rate_notes': 'No voluntary price was shared'})
        qualified = one('SELECT * FROM sales_prospects WHERE id=?', (first['id'],))
        assert qualified['status'] == 'replied' and qualified['needs'] == 'Fixture customer shared one route; review only'
        assert count('opportunities') == before_reply['opportunities']
        reply_mid = official_sales.create_draft(linked['inbox_id'], session)
        reply = one('SELECT * FROM outbound_messages WHERE id=?', (reply_mid,))
        assert reply['prospect_id'] == first['id'] and reply['opportunity_id'] is None
        assert reply['body'] == '' and not reply['proposal_text'] and reply['status'] == 'draft'
        assert official_sales.create_draft(linked['inbox_id'], session) == reply_mid
        post('/outbound/'+str(reply_mid)+'/update', {'recipient': first['recipient'], 'subject': 'Re: Introduction', 'body': 'Approved human reply before opt-out'})
        reply_base = approve(reply_mid)

        # A threaded opt-out records a suppression and blocks an already drafted human reply.
        messages = {4: raw('<stop@example.invalid>', 'STOP\nFixture Procurement\n\n> Original freight introduction: Reply STOP to opt out.')}
        with patch.object(mail, 'imap_login', return_value=imap), patch.object(mail, 'send') as no_ack:
            mail.sync(uid); mail.sync(uid)
            stopped_inbox = one("SELECT id FROM spacemail_inbox WHERE message_id='<stop@example.invalid>'")['id']
            official_replies.deliver(stopped_inbox)
            no_ack.assert_not_called()
        assert one('SELECT status FROM sales_prospects WHERE id=?', (first['id'],))['status'] == 'stopped'
        assert one("SELECT recipient FROM marketing_suppressions WHERE channel='email' AND recipient=?", (first['recipient'],))
        post('/official-inbox/'+str(stopped_inbox)+'/draft', expected=409)
        with patch.object(mail, 'send') as stopped_provider:
            post(reply_base+'/send', expected=409)
            stopped_provider.assert_not_called()
        post('/sales-prospects/'+str(first['id'])+'/qualification', {'needs': 'No state downgrade allowed'}, 409)
        messages = {5: raw('<after-stop@example.invalid>', 'Thanks for the freight information.')}
        with patch.object(mail, 'imap_login', return_value=imap), patch.object(mail, 'send') as later_provider:
            mail.sync(uid)
            after_stop = one("SELECT id FROM spacemail_inbox WHERE message_id='<after-stop@example.invalid>'")['id']
            official_replies.deliver(after_stop)
            later_provider.assert_not_called()
        assert one('SELECT status FROM sales_prospects WHERE id=?', (first['id'],))['status'] == 'stopped'
        post('/official-inbox/'+str(after_stop)+'/draft', expected=409)
        assert count('official_reply_log') == 0

        # Existing customer campaigns reciprocally skip manually registered prospects.
        from app import customer_marketing as campaigns
        reciprocal_mid, reciprocal = create('reciprocal-campaign')
        roster = [
            {'source': 'fixture:prospect', 'name': reciprocal['company_name'], 'email': reciprocal['recipient'], 'phone': '', 'status': 'lead'},
            {'source': 'fixture:control', 'name': 'Ordinary campaign fixture', 'email': 'control@campaign-control.example.invalid', 'phone': '', 'status': 'lead'},
        ]
        with patch.object(campaigns, 'roster', return_value=roster):
            campaign_id = campaigns.prepare(uid, dt.date(2091, 1, 1))
        selected = rows('SELECT recipient FROM customer_campaign_recipients WHERE campaign_id=?', (campaign_id,))
        assert selected == [{'recipient': 'control@campaign-control.example.invalid'}], selected
        queued = prior_campaign(reciprocal['recipient'], 'pending')
        queued_cid = one('SELECT campaign_id FROM customer_campaign_recipients WHERE id=?', (queued,))['campaign_id']
        with db() as c:
            c.execute("INSERT INTO customer_campaign_channels(campaign_id,channel,status,updated_at) VALUES(%s,'email','sending',%s)", (queued_cid, now))
        with patch.object(campaigns, 'official_send') as excluded_provider:
            asyncio.run(campaigns.deliver(queued_cid, 'email', uid))
            excluded_provider.assert_not_called()
        assert one('SELECT status FROM customer_campaign_recipients WHERE id=?', (queued,))['status'] == 'excluded_prospect'
        assert one('SELECT status FROM outbound_messages WHERE id=?', (reciprocal_mid,))['status'] == 'draft'

        # Either a campaign or an intro can win a concurrent registration, never both.
        race_data = data('cross-flow-race')
        race_roster = [{'source': 'fixture:race', 'name': race_data['company_name'], 'email': race_data['recipient'], 'phone': '', 'status': 'lead'}]
        with patch.object(campaigns, 'roster', return_value=race_roster):
            with ThreadPoolExecutor(max_workers=2) as pool:
                intro_future = pool.submit(client.post, '/sales-prospects/create', data={**csrf, **race_data})
                campaign_future = pool.submit(campaigns.prepare, uid, dt.date(2091, 1, 2))
                intro_response, race_campaign = intro_future.result(), campaign_future.result()
        assert intro_response.status_code in (303, 409), intro_response.text
        prospect_count = one('SELECT COUNT(*) n FROM sales_prospects WHERE recipient=?', (race_data['recipient'],))['n']
        campaign_count = one('SELECT COUNT(*) n FROM customer_campaign_recipients WHERE campaign_id=? AND recipient=?', (race_campaign, race_data['recipient']))['n']
        assert prospect_count + campaign_count == 1, (prospect_count, campaign_count)

    print('PASS: isolated prospect storage, exact official evidence, exclusions and cross-campaign dedupe before draft/send, immutable approval, owner/RBAC/CSRF/MFA, single SMTP claim, provider truth, terminal uncertainty, preserved public-request guard, exact prospect reply linkage, opt-out suppression of approved replies, stopped-state persistence, reciprocal campaign exclusion and no automatic acknowledgement. Live mail: 0.')


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    target = urlsplit(url)
    if target.hostname not in {'localhost', '127.0.0.1'} or target.path != '/afaaq_test' or target.query or target.fragment:
        raise RuntimeError('Requires local disposable afaaq_test database without URL parameters')
    schema = 'prospect_intro_test_'+secrets.token_hex(6)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        environment = {
            'DATABASE_URL': url+'?'+urlencode({'options': '-c search_path='+schema+' -c statement_timeout=30000 -c lock_timeout=15000'}, quote_via=quote),
            'ADMIN_EMAIL': 'prospect-ci@example.invalid', 'ADMIN_PASSWORD': secrets.token_urlsafe(24),
            'TOKEN_ENCRYPTION_KEY': 'local-fixture-only', 'DISCOVERY_AUTO_ENABLED': '0',
            'ENABLE_EXTERNAL_ACTIONS': '1', 'BROWSER_COOKIE_SECURE': '0',
        }
        original_connect, original_connect_ex, original_dns = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
        attempts = []
        def check_host(host):
            if host not in {None, 'localhost', '127.0.0.1', '::1', b'localhost', b'127.0.0.1', b'::1'}:
                attempts.append(str(host))
                raise AssertionError('Live network disabled in prospect acceptance: '+str(host))
        def local_connect(sock, destination):
            if isinstance(destination, tuple): check_host(destination[0])
            return original_connect(sock, destination)
        def local_connect_ex(sock, destination):
            if isinstance(destination, tuple): check_host(destination[0])
            return original_connect_ex(sock, destination)
        def local_dns(host, *args, **kwargs):
            check_host(host)
            return original_dns(host, *args, **kwargs)
        with patch.dict(os.environ, environment), patch.object(socket.socket, 'connect', local_connect), \
             patch.object(socket.socket, 'connect_ex', local_connect_ex), patch.object(socket, 'getaddrinfo', local_dns):
            run()
        assert not attempts, attempts
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    main()
