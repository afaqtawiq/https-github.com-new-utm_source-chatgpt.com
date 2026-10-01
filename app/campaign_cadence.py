"""Brochure campaign cadence: one introduction, one follow-up no sooner than 7 days later, then stop,
with daily per-channel caps (WhatsApp 200, email 50 by default).

Installed at startup by app.prospects_app; replaces customer_marketing.prepare so the daily
schedule no longer re-sends the same brochure to the same address every day.
"""
import json
import os
import secrets
from datetime import datetime, timedelta

from app import customer_marketing as cm
from app.storage import db, log, rows, utcnow


def prepare(user_id, day=None):
    day = day or datetime.now(cm.RIYADH).date()
    daily_key = cm.KEY + '-' + day.isoformat()
    listing = cm.select_recipients(cm.roster(), [(r['channel'], r['recipient']) for r in rows('SELECT * FROM marketing_suppressions')])
    history = {(h['channel'], h['recipient']): h for h in rows('''SELECT r.channel,r.recipient,COUNT(*) AS n,MAX(COALESCE(r.sent_at,r.claimed_at)) AS last
        FROM customer_campaign_recipients r JOIN customer_campaigns p ON p.id=r.campaign_id
        WHERE p.campaign_key LIKE ? AND r.status IN ('sent','sending','uncertain','bounced','rejected')
        GROUP BY r.channel,r.recipient''', (cm.KEY + '-%',))}
    cutoff = datetime.combine(day, datetime.min.time(), cm.RIYADH) - timedelta(days=7)
    listing = [x for x in listing if not (h := history.get((x['channel'], x['recipient']))) or
               (h['n'] < 2 and h['last'] is not None and h['last'] <= cutoff)]
    # Daily caps keep WhatsApp inside Meta's messaging tier (250 new conversations / 24h at start)
    # and protect sender reputation. Follow-ups (oldest first) go before first introductions;
    # whoever does not fit today is picked up automatically on the next daily run.
    caps = {'whatsapp': int(os.getenv('CAMPAIGN_WHATSAPP_DAILY_CAP', '200')), 'email': int(os.getenv('CAMPAIGN_EMAIL_DAILY_CAP', '50'))}
    epoch = datetime(1970, 1, 1, tzinfo=cm.RIYADH)
    listing.sort(key=lambda x: (0 if history.get((x['channel'], x['recipient'])) else 1,
                                (history.get((x['channel'], x['recipient'])) or {}).get('last') or epoch))
    used, capped = {}, []
    for item in listing:
        if used.get(item['channel'], 0) < caps.get(item['channel'], 0):
            used[item['channel']] = used.get(item['channel'], 0) + 1
            capped.append(item)
    listing = capped
    url, base = cm.origin() + cm.PDF_PATH, cm.origin() + '/marketing/unsubscribe/'
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(73002030)')
        existing = c.execute('SELECT id FROM customer_campaigns WHERE campaign_key=%s', (daily_key,)).fetchone()
        if existing:
            return existing['id']
        campaign = c.execute('''INSERT INTO customer_campaigns(campaign_key,title,subject,plain_template,html_template,
            brochure_url,unsubscribe_base,created_by,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
            (daily_key, 'بروشور خدمات ميناء جدة — ' + day.isoformat(), cm.SUBJECT, cm.message_text(url, '__UNSUBSCRIBE__'),
             cm.message_html(url, '__UNSUBSCRIBE__'), url, base, user_id, utcnow())).fetchone()['id']
        for channel in ('email', 'whatsapp'):
            c.execute('INSERT INTO customer_campaign_channels(campaign_id,channel,updated_at) VALUES(%s,%s,%s)', (campaign, channel, utcnow()))
        for item in listing:
            c.execute('''INSERT INTO customer_campaign_recipients(campaign_id,channel,recipient,company_name,sources,unsubscribe_token)
                VALUES(%s,%s,%s,%s,%s,%s)''', (campaign, item['channel'], item['recipient'], item['company_name'], json.dumps(item['sources']), secrets.token_urlsafe(24)))
    log(user_id, 'customer_campaign_prepared', 'customer_campaign', campaign, f'{len(listing)} channel recipients (cadence: intro + one follow-up); no messages sent')
    return campaign


cm.prepare = prepare
