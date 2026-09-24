"""Verify the authorized cleanup in an isolated PostgreSQL schema, without sends."""
import datetime as dt
import importlib.util
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
url = os.environ['AFAAQ_TEST_DATABASE_URL']
assert urlsplit(url).hostname in {'localhost', '127.0.0.1'} and urlsplit(url).path == '/afaaq_test'
import psycopg
schema = 'repair_test_' + secrets.token_hex(5)
with psycopg.connect(url, autocommit=True) as c:
    c.execute('CREATE SCHEMA ' + schema)
os.environ.update(DATABASE_URL=url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
                  DISCOVERY_AUTO_ENABLED='0', ENABLE_EXTERNAL_ACTIONS='0',
                  ADMIN_EMAIL='repair@example.invalid', ADMIN_PASSWORD=secrets.token_urlsafe(24))
from app.bootstrap import app
from app.storage import db, one, execute, utcnow, create_session
from fastapi.testclient import TestClient
spec = importlib.util.spec_from_file_location('repair', ROOT / 'scripts/afaq_repair_20260924.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)
old = repair.CUTOFF - dt.timedelta(days=1)
future = repair.CUTOFF + dt.timedelta(hours=1)
uid = one("SELECT id FROM users WHERE email='repair@example.invalid'")['id']
with db() as c:
    c.execute('INSERT INTO customer_campaign_schedule(id,enabled,approved_by,approved_at,content_digest) VALUES(1,FALSE,%s,%s,%s)', (uid, old, 'fixture'))
    campaign = c.execute('''INSERT INTO customer_campaigns(campaign_key,title,subject,plain_template,html_template,brochure_url,unsubscribe_base,created_by,created_at)
        VALUES('jeddah-port-introduction-20260922-v2-test','fixture','fixture','__UNSUBSCRIBE__','__UNSUBSCRIBE__','https://example.invalid/brochure','https://example.invalid/unsub/',%s,%s) RETURNING id''', (uid, old)).fetchone()['id']
    c.execute("INSERT INTO customer_campaign_channels(campaign_id,channel,status,updated_at) VALUES(%s,'email','paused',%s)", (campaign, old))
    for i, status in enumerate(('pending', 'blocked', 'sending', 'sent')):
        c.execute("INSERT INTO customer_campaign_recipients(campaign_id,channel,recipient,company_name,sources,unsubscribe_token,status) VALUES(%s,'email',%s,'fixture','[]',%s,%s)", (campaign, f'p{i}@example.invalid', secrets.token_urlsafe(12), status))
    for i in range(247):
        c.execute("INSERT INTO opportunities(company_name,created_at,updated_at) VALUES('old opportunity',%s,%s)", (old, old))
    for i in range(13):
        lid = c.execute("INSERT INTO naqliat_loads(fingerprint,origin,destination,captured_at,created_at) VALUES(%s,'A','B',%s,%s) RETURNING id", (str(i), old, old)).fetchone()['id']
        c.execute("INSERT INTO shipments(reference,service_type,created_at,updated_at) VALUES(%s,'transport',%s,%s)", ('NQ-' + str(lid), old, old))
    c.execute("INSERT INTO shipments(reference,service_type,created_at,updated_at) VALUES('PRESERVE','transport',%s,%s)", (old, old))
    c.execute("INSERT INTO drivers(driver_name,whatsapp_phone,vehicle_type,created_at,updated_at) VALUES('preserve','+966500000001','truck',%s,%s)", (old, old))
    c.execute("INSERT INTO accounts(name,created_at,updated_at) VALUES('preserve',%s,%s)", (old, old))
    c.execute("INSERT INTO customer_directory(company_name,created_at,updated_at) VALUES('preserve',%s,%s)", (old, old))
    c.execute("INSERT INTO opportunities(company_name,created_at,updated_at) VALUES('future opportunity',%s,%s)", (future, future))
    c.execute("INSERT INTO naqliat_loads(fingerprint,origin,destination,captured_at,created_at) VALUES('future','A','B',%s,%s)", (future, future))
result = repair.cleanup()
assert result['deleted_opportunities'] == 247 and result['deleted_naqliat'] == 13
assert result['after'] == {'opportunities': 1, 'naqliat_loads': 1, 'shipments': 1, 'drivers': 1, 'accounts': 1, 'customer_directory': 1}
assert result['brochure_pending_after'] == 0 and result['brochure_sending_channels_after'] == 0
assert one("SELECT COUNT(*) n FROM customer_campaign_recipients WHERE status='sent'")['n'] == 1
assert repair.cleanup()['already_applied']
draft = repair.prepare_mail_test()
assert repair.prepare_mail_test()['test_campaign_id'] == draft['test_campaign_id']
row = one('SELECT recipient,status FROM customer_campaign_recipients WHERE campaign_id=?', (draft['test_campaign_id'],))
assert row == {'recipient': repair.RECIPIENT, 'status': 'pending'}
assert one('SELECT COUNT(*) n FROM customer_campaign_recipients WHERE campaign_id=?', (draft['test_campaign_id'],))['n'] == 1
assert not one('SELECT enabled FROM customer_campaign_schedule WHERE id=1')['enabled']

# Real schema and dict-row semantics reproduce both historical /communications failures.
sid, _, _ = create_session(uid)
client = TestClient(app)
client.cookies.set('gla_session', sid)
assert client.get('/communications').status_code == 200
op = one('SELECT id FROM opportunities')['id']
execute("INSERT INTO retell_calls(call_id,opportunity_id,status,summary,created_at,updated_at) VALUES(?,?,?,?,?,?)", ('acceptance-call', op, 'ended', 'schema verification', old, old))
page = client.get('/communications')
assert page.status_code == 200 and 'future opportunity' in page.text and 'schema verification' in page.text
data = client.get('/api/v7/communications')
assert data.status_code == 200 and data.json()['items'][0]['call_id'] == 'acceptance-call'
client.cookies.clear()
assert client.get('/api/v7/communications').status_code == 401

# A changed scope must fail atomically without deleting any remaining records.
execute('DELETE FROM system_migrations WHERE key=?', (repair.KEY,))
try:
    repair.cleanup()
except RuntimeError as exc:
    assert 'scope changed' in str(exc)
else:
    raise AssertionError('cleanup scope guard failed')
assert one('SELECT COUNT(*) n FROM opportunities')['n'] == 1
print('PASS: scoped deletion, protected rosters, future records preserved, idempotency, queue cancellation, one-recipient unsent draft, communications HTML/API and authentication.')
with psycopg.connect(url, autocommit=True) as c:
    c.execute('DROP SCHEMA ' + schema + ' CASCADE')
