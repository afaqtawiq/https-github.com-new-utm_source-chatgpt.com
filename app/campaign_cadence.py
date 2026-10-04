"""One initial brochure and at most one follow-up >=168h after acceptance.

Both preparation and execution use the same DB lock/invariant. Preparation alone
is never authorization to send, including for queues created by older releases.
"""
import json
import os
import secrets
from datetime import datetime, timezone

from app import customer_marketing as cm
from app.brochure_cadence_policy import decision, identity
from app.mail_threads import message_id, references
from app.storage import db, log, utcnow

LOCK = 73002030
FAMILY = 'jeddah-port-introduction-%'


class CadenceStopped(Exception):
    """A final pre-dispatch guard stopped a message before provider submission."""


def lock(c):
    c.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))


def snapshot(c):
    result = {}
    for row in c.execute('''SELECT r.*,COALESCE(r.sender_user_id,ch.approved_by,p.created_by) AS sender_user_id FROM customer_campaign_recipients r
        JOIN customer_campaigns p ON p.id=r.campaign_id
        LEFT JOIN customer_campaign_channels ch ON ch.campaign_id=r.campaign_id AND ch.channel=r.channel
        WHERE p.campaign_key LIKE %s OR p.brochure_url LIKE %s ORDER BY r.id''',
        (FAMILY, '%' + cm.PDF_PATH)).fetchall():
        key = (row['channel'], identity(row['channel'], row['recipient']))
        result.setdefault(key, []).append(row)
    return result


def audience(c):
    suppressed = [(r['channel'], identity(r['channel'], r['recipient']))
                  for r in c.execute('SELECT * FROM marketing_suppressions').fetchall()]
    roster = cm.roster()  # Shared registered-customer source; also used by the preview UI.
    return {(r['channel'], r['recipient']): r for r in cm.select_recipients(roster, suppressed)}


def replied(c, channel, recipient, history):
    if channel == 'whatsapp':
        # Recorded only from a signed, expected-account, private inbound event
        # after a brochure attempt exists. A fast reply may precede receipt write.
        return bool(c.execute("SELECT 1 FROM customer_campaign_replies WHERE channel='whatsapp' AND recipient=%s LIMIT 1", (recipient,)).fetchone())
    accepted = [r for r in history if r.get('sent_at')]
    if not accepted:
        return False
    first = min(r.get('claimed_at') or r['sent_at'] for r in accepted)
    # Only a validated human message with exact RFC ancestor, same mailbox owner,
    # and same sender counts. Notices, automated mail and loose subjects do not.
    receipts = {(r['sender_user_id'], r.get('provider_message_id')) for r in accepted if message_id(r.get('provider_message_id'))}
    if not receipts:
        return False
    for item in c.execute('''SELECT user_id,in_reply_to,message_references FROM spacemail_inbox
        WHERE sender_address=%s AND manual_reply_address=sender_address
        AND duplicate_of IS NULL AND notice_kind='none' AND imported_at>=%s''', (recipient, first)).fetchall():
        ancestors = references(item['message_references']) + [message_id(item['in_reply_to'])]
        if any((item['user_id'], ref) in receipts for ref in ancestors if ref):
            return True
    return False


def eligibility(c, key, history, now, *, current_id=None):
    stage, reason = decision(history, now, current_id=current_id)
    if stage and replied(c, *key, history):
        return None, 'recipient_replied'
    if stage and key[0] == 'email':
        from app.prospect_outreach import campaign_duplicate
        if campaign_duplicate(c, key[1]):
            return None, 'manual_prospect_exists'
    return stage, reason


def prepare(user_id, day=None, *, now=None):
    now = now or utcnow()
    day = day or now.astimezone(cm.RIYADH).date()
    daily_key = cm.KEY + '-' + day.isoformat()
    url, base = cm.origin() + cm.PDF_PATH, cm.origin() + '/marketing/unsubscribe/'
    with db() as c:
        lock(c)
        existing = c.execute('SELECT id FROM customer_campaigns WHERE campaign_key=%s', (daily_key,)).fetchone()
        if existing:
            return existing['id']
        history = snapshot(c)
        listing = []
        for key, item in audience(c).items():
            stage, _ = eligibility(c, key, history.get(key, []), now)
            if stage:
                item['stage'] = stage
                listing.append(item)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        listing.sort(key=lambda x: (x['stage'] != 'followup',
            min((r['sent_at'] for r in history.get((x['channel'], x['recipient']), []) if r.get('sent_at')), default=epoch), x['recipient']))
        caps = {'whatsapp': max(0, int(os.getenv('CAMPAIGN_WHATSAPP_DAILY_CAP', '200'))),
                'email': max(0, int(os.getenv('CAMPAIGN_EMAIL_DAILY_CAP', '50')))}
        campaign = c.execute('''INSERT INTO customer_campaigns(campaign_key,title,subject,plain_template,html_template,
            brochure_url,unsubscribe_base,created_by,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
            (daily_key, 'بروشور خدمات ميناء جدة — ' + day.isoformat(), cm.SUBJECT, cm.message_text(url, '__UNSUBSCRIBE__'),
             cm.message_html(url, '__UNSUBSCRIBE__'), url, base, user_id, now)).fetchone()['id']
        for channel in ('email', 'whatsapp'):
            c.execute('INSERT INTO customer_campaign_channels(campaign_id,channel,updated_at) VALUES(%s,%s,%s)', (campaign, channel, now))
        used = {'email': 0, 'whatsapp': 0}
        for item in listing:
            channel = item['channel']
            if used[channel] >= caps[channel]:
                continue
            used[channel] += 1
            c.execute('''INSERT INTO customer_campaign_recipients(campaign_id,channel,recipient,company_name,sources,unsubscribe_token,cadence_stage)
                VALUES(%s,%s,%s,%s,%s,%s,%s)''', (campaign, channel, item['recipient'], item['company_name'], json.dumps(item['sources']), secrets.token_urlsafe(24), item['stage']))
    log(user_id, 'customer_campaign_prepared', 'customer_campaign', campaign,
        f'{sum(used.values())} channel recipients (initial + at most one follow-up >=7 days); no messages sent')
    return campaign


def claim(c, cid, channel, now, user_id):
    """The committed sending status fences all other workers before network IO."""
    lock(c)
    state = c.execute('SELECT status FROM customer_campaign_channels WHERE campaign_id=%s AND channel=%s FOR UPDATE', (cid, channel)).fetchone()
    if not state or state['status'] != 'sending':
        return None
    history, available = snapshot(c), audience(c)
    for item in c.execute("SELECT * FROM customer_campaign_recipients WHERE campaign_id=%s AND channel=%s AND status='pending' ORDER BY id FOR UPDATE", (cid, channel)).fetchall():
        key = (channel, identity(channel, item['recipient']))
        from app.prospect_outreach import campaign_duplicate
        if channel == 'email' and campaign_duplicate(c, key[1]):
            stage, reason = None, 'manual_prospect_exists'
        else:
            stage, reason = eligibility(c, key, history.get(key, []), now, current_id=item['id']) if key in available else (None, 'suppressed_or_not_current_customer')
        if not stage:
            status = 'excluded_prospect' if reason == 'manual_prospect_exists' else 'suppressed' if key not in available else 'cadence_skipped'
            c.execute('UPDATE customer_campaign_recipients SET status=%s,last_error=%s WHERE id=%s', (status, reason, item['id']))
            # Later duplicate rows may proceed only when the older one was skipped
            # without attempting delivery. Update this transaction's snapshot too.
            for old in history.get(key, []):
                if old['id'] == item['id']:
                    old['status'] = status
            continue
        claimed = c.execute("""UPDATE customer_campaign_recipients SET status='sending',claimed_at=%s,
            cadence_stage=%s,sender_user_id=%s,last_error=NULL WHERE id=%s RETURNING *""", (now, stage, user_id, item['id'])).fetchone()
        claimed['dispatch_recipient'] = key[1]
        return claimed
    return None


def check_dispatch(item):
    """Recheck pause/opt-out/reply after provider preflight, before submission."""
    with db() as c:
        lock(c)
        current = c.execute('''SELECT r.status,ch.status AS channel_status FROM customer_campaign_recipients r
            JOIN customer_campaign_channels ch ON ch.campaign_id=r.campaign_id AND ch.channel=r.channel WHERE r.id=%s''', (item['id'],)).fetchone()
        if not current or current['status'] != 'sending' or current['channel_status'] != 'sending':
            raise CadenceStopped('campaign_paused_before_dispatch')
        key = (item['channel'], identity(item['channel'], item['recipient']))
        if key not in audience(c):
            raise CadenceStopped('suppressed_or_not_current_customer')
        stage, reason = eligibility(c, key, snapshot(c).get(key, []), utcnow(), current_id=item['id'])
        if not stage:
            raise CadenceStopped(reason)


def record_whatsapp_reply(c, recipient, event_id, text=""):
    """Caller has verified signature, account and exact private inbound identity."""
    recipient = identity('whatsapp', recipient)
    if not recipient:
        return
    lock(c)
    from app.prospect_outreach import stop_requested
    if stop_requested(text):
        c.execute("INSERT INTO marketing_suppressions(channel,recipient,created_at) VALUES('whatsapp',%s,%s) ON CONFLICT DO NOTHING", (recipient, utcnow()))
    history = snapshot(c).get(('whatsapp', recipient), [])
    if any(r['status'] in ('sent', 'sending', 'uncertain') or r.get('sent_at') or r.get('provider_message_id') for r in history):
        c.execute('''INSERT INTO customer_campaign_replies(channel,recipient,event_id,received_at)
            VALUES('whatsapp',%s,%s,%s) ON CONFLICT DO NOTHING''', (recipient, event_id, utcnow()))
