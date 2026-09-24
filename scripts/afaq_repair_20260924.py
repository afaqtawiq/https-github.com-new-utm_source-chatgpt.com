"""One-time, owner-authorized cleanup and single-recipient acceptance draft.

Run explicitly as a maintenance command. Never sends email or enables schedules.
"""
import datetime as dt
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.storage import db, utcnow

KEY = 'afaq_owner_cleanup_20260924_v1'
CUTOFF = dt.datetime(2026, 9, 24, 8, tzinfo=dt.timezone.utc)
TEST_KEY = 'afaq-single-mail-acceptance-20260924'
RECIPIENT = 'shawahidalhadaf@gmail.com'


def counts(c):
    return {table: c.execute('SELECT COUNT(*) n FROM ' + table).fetchone()['n']
            for table in ('opportunities', 'naqliat_loads', 'shipments', 'drivers',
                          'accounts', 'customer_directory')}


def cleanup():
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(73002409)')
        if c.execute('SELECT 1 FROM system_migrations WHERE key=%s', (KEY,)).fetchone():
            return {'result': 'PASS', 'already_applied': True, 'after': counts(c)}
        schedule = c.execute('SELECT enabled,approved_by FROM customer_campaign_schedule WHERE id=1 FOR UPDATE').fetchone()
        if not schedule or schedule['enabled']:
            raise RuntimeError('FAIL: brochure schedule must already be disabled by administrator')
        c.execute('LOCK TABLE opportunities,naqliat_loads,shipments,drivers,accounts,customer_directory IN SHARE ROW EXCLUSIVE MODE')
        before = counts(c)
        opp_ids = [r['id'] for r in c.execute('SELECT id FROM opportunities WHERE created_at<=%s FOR UPDATE', (CUTOFF,))]
        load_ids = [r['id'] for r in c.execute('SELECT id FROM naqliat_loads WHERE created_at<=%s FOR UPDATE', (CUTOFF,))]
        if len(opp_ids) != 247 or len(load_ids) != 13:
            raise RuntimeError(f'FAIL: cleanup scope changed: opportunities={len(opp_ids)}, naqliat={len(load_ids)}; no deletion committed')
        shipment_ids = [r['id'] for r in c.execute('SELECT id FROM shipments WHERE reference=ANY(%s) AND created_at<=%s FOR UPDATE',
                                                 (['NQ-' + str(i) for i in load_ids], CUTOFF))]
        campaign_ids = [r['id'] for r in c.execute("SELECT id FROM customer_campaigns WHERE campaign_key LIKE 'jeddah-port-introduction-20260922-v2%%' AND created_at<=%s", (CUTOFF,))]
        queue_before = [dict(r) for r in c.execute('SELECT channel,status,COUNT(*) n FROM customer_campaign_recipients WHERE campaign_id=ANY(%s) GROUP BY channel,status', (campaign_ids,))]
        c.execute("UPDATE customer_campaign_channels SET status='paused',last_error='Owner stopped brochure campaign 2026-09-24',updated_at=%s WHERE campaign_id=ANY(%s) AND status IN ('draft','sending','waiting_template','paused')", (utcnow(), campaign_ids))
        c.execute("UPDATE customer_campaign_recipients SET status='cancelled',last_error='Owner cancelled pending brochure delivery 2026-09-24' WHERE campaign_id=ANY(%s) AND status IN ('pending','blocked')", (campaign_ids,))
        # A transport already claimed before the stop must not be retried.
        c.execute("UPDATE customer_campaign_recipients SET status='uncertain',last_error='Stopped after prior claim; do not retry without delivery proof' WHERE campaign_id=ANY(%s) AND status='sending'", (campaign_ids,))
        c.execute("UPDATE driver_broadcasts SET status='cancelled',updated_at=%s WHERE shipment_id=ANY(%s) AND status IN ('draft','pending_approval','approved','sending')", (utcnow(), shipment_ids))
        c.execute("UPDATE driver_broadcast_recipients SET status='cancelled' WHERE status='pending' AND broadcast_id IN (SELECT id FROM driver_broadcasts WHERE shipment_id=ANY(%s))", (shipment_ids,))
        c.execute('DELETE FROM opportunities WHERE id=ANY(%s)', (opp_ids,))
        c.execute('DELETE FROM shipments WHERE id=ANY(%s)', (shipment_ids,))
        c.execute('DELETE FROM naqliat_loads WHERE id=ANY(%s)', (load_ids,))
        after = counts(c)
        for table in ('drivers', 'accounts', 'customer_directory'):
            if before[table] != after[table]:
                raise RuntimeError('FAIL: protected roster changed; rolling back')
        if after['shipments'] != before['shipments'] - len(shipment_ids):
            raise RuntimeError('FAIL: shipment deletion scope mismatch; rolling back')
        active = c.execute("SELECT COUNT(*) n FROM customer_campaign_recipients WHERE campaign_id=ANY(%s) AND status IN ('pending','sending','blocked')", (campaign_ids,)).fetchone()['n']
        channels = c.execute("SELECT COUNT(*) n FROM customer_campaign_channels WHERE campaign_id=ANY(%s) AND status='sending'", (campaign_ids,)).fetchone()['n']
        result = {'result': 'PASS', 'before': before, 'after': after,
                  'deleted_opportunities': len(opp_ids), 'deleted_naqliat': len(load_ids),
                  'deleted_linked_shipments': len(shipment_ids), 'schedule_enabled': 0,
                  'brochure_queue_before': queue_before, 'brochure_pending_after': active,
                  'brochure_sending_channels_after': channels}
        if active or channels:
            raise RuntimeError('FAIL: active brochure jobs remain; rolling back')
        c.execute('INSERT INTO system_migrations(key,applied_at) VALUES(%s,%s)', (KEY, utcnow()))
        c.execute('INSERT INTO activity(user_id,action,entity_type,summary,created_at) VALUES(%s,%s,%s,%s,%s)',
                  (schedule['approved_by'], KEY, 'maintenance', json.dumps(result), utcnow()))
    return result


def prepare_mail_test():
    """Create an isolated draft for the existing UI/MFA/approval/email worker."""
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(73002409)')
        existing = c.execute('SELECT id FROM customer_campaigns WHERE campaign_key=%s', (TEST_KEY,)).fetchone()
        if existing:
            return {'result': 'PASS', 'test_campaign_id': existing['id'], 'already_exists': True, 'sent_by_script': False}
        schedule = c.execute('SELECT enabled,approved_by FROM customer_campaign_schedule WHERE id=1 FOR UPDATE').fetchone()
        if not schedule or schedule['enabled']:
            raise RuntimeError('FAIL: acceptance draft requires stopped brochure schedule')
        source = c.execute("SELECT * FROM customer_campaigns WHERE campaign_key LIKE 'jeddah-port-introduction-20260922-v2%' ORDER BY id DESC LIMIT 1").fetchone()
        if not source:
            raise RuntimeError('FAIL: approved brochure source missing')
        cid = c.execute('''INSERT INTO customer_campaigns(campaign_key,title,subject,plain_template,html_template,brochure_url,unsubscribe_base,created_by,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
            (TEST_KEY, 'اختبار قبول البريد — مستلم واحد فقط — 2026-09-24',
             source['subject'] + ' [AFAQ-ACCEPT-20260924]', source['plain_template'], source['html_template'],
             source['brochure_url'], source['unsubscribe_base'], schedule['approved_by'], utcnow())).fetchone()['id']
        c.execute("INSERT INTO customer_campaign_channels(campaign_id,channel,status,updated_at) VALUES(%s,'email','draft',%s)", (cid, utcnow()))
        c.execute('''INSERT INTO customer_campaign_recipients(campaign_id,channel,recipient,company_name,sources,unsubscribe_token)
            VALUES(%s,'email',%s,%s,%s,%s)''', (cid, RECIPIENT, 'SHOD AI — owner-authorized acceptance test', '["owner-request-20260924"]', secrets.token_urlsafe(24)))
    return {'result': 'PASS', 'test_campaign_id': cid, 'recipient': RECIPIENT, 'recipient_count': 1, 'sent_by_script': False}


if __name__ == '__main__':
    print('AFAQ_REPAIR ' + json.dumps(cleanup(), ensure_ascii=False), flush=True)
    print('AFAQ_REPAIR ' + json.dumps(prepare_mail_test(), ensure_ascii=False), flush=True)
