"""Owner-authorised autopilot: the agent contacts today's prospects without a per-batch approval.

Enabled only with AUTO_OUTREACH=1 and ENABLE_EXTERNAL_ACTIONS=1. Each run takes today's
pending prospects up to AUTO_OUTREACH_DAILY_CAP, approves them as the system, and sends the
standard introduction once per company: email from the official mailbox when an address is
known, and WhatsApp through one Meta-approved marketing template. Opt-outs (marketing
suppressions) and any earlier contact with the same phone or email are always respected.
A provider result that cannot be confirmed stops the run instead of retrying.
"""
import os
import re

from app.storage import db, log, one, utcnow

TEMPLATE = 'afaaq_marketing_prospect_intro_v1_ar'
STOP_LINE = 'لإيقاف الرسائل أرسل: إيقاف'
SUBJECT = 'آفاق طويق — التخليص الجمركي والنقل البري لشحناتكم'


def enabled():
    return os.getenv('AUTO_OUTREACH', '0') == '1' and os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') == '1'


def daily_cap():
    try:
        return max(0, min(100, int(os.getenv('AUTO_OUTREACH_DAILY_CAP', '20'))))
    except ValueError:
        return 20


def pitch_of(message):
    """Recover the segment pitch from a stored draft (AI opening lines are ignored)."""
    from app.daily_prospects import TRANSPORT_LICENCE
    m = re.search(r'رقم ' + re.escape(TRANSPORT_LICENCE) + r'\)\. (.+)', message or '')
    return m.group(1).strip() if m else ''


def standard_message(company_name, pitch):
    from app.daily_prospects import template_message
    return template_message(company_name, pitch) + '\n' + STOP_LINE


def template_spec():
    return {'name': TEMPLATE, 'language': 'ar', 'category': 'MARKETING', 'components': [
        {'type': 'body', 'text': standard_message('{{1}}', '{{2}}'),
         'example': {'body_text': [['مؤسسة المثال التجارية',
                                    'نخدم مستوردي مواد البناء من ميناء جدة الإسلامي والميناء الجاف بالرياض.']]}}]}


async def ensure_template():
    """Create the WhatsApp template once; returns its Meta status (APPROVED when usable)."""
    from app import zernio_whatsapp as wa
    async with wa.client() as c:
        await wa.validate_account(c)
        for item in await wa.templates(c):
            if item.get('name') == TEMPLATE and item.get('language') == 'ar':
                return str(item.get('status') or 'UNKNOWN')
        result = await c.post(wa.BASE + '/whatsapp/templates', json={'accountId': wa.account_id(), **template_spec()})
        return 'SUBMITTED' if result.is_success else 'CREATE_FAILED_' + str(result.status_code)


def system_user():
    row = one('''SELECT u.id FROM users u WHERE u.is_active::text IN ('1','true','t') AND u.role='admin'
        ORDER BY (SELECT COUNT(*) FROM spacemail_connections s WHERE s.user_id=u.id) DESC, u.id LIMIT 1''')
    return row['id'] if row else None


def already_contacted(c, phone, email):
    suppressed = c.execute('''SELECT 1 FROM marketing_suppressions WHERE (channel='whatsapp' AND recipient=%s)
        OR (channel='email' AND lower(recipient)=lower(%s)) LIMIT 1''', (phone or '-', email or '-')).fetchone()
    if suppressed:
        return 'suppressed'
    previous = c.execute('''SELECT 1 FROM daily_prospects WHERE status IN ('contacted','interested','not_interested','no_answer')
        AND ((phone<>'' AND phone=%s) OR (email<>'' AND lower(email)=lower(%s))) LIMIT 1''', (phone or '-', email or '-')).fetchone()
    return 'already_contacted' if previous else None


def pending_today(limit):
    from app.daily_prospects import today
    with db() as c:
        # Earlier companies that waited only for the WhatsApp template come first.
        return c.execute('''SELECT * FROM daily_prospects WHERE
            (status='pending' AND batch_date=%s)
            OR (status='approved' AND outcome_note='autopilot: waiting_channel' AND batch_date>=%s - 7)
            ORDER BY (status='approved') DESC, score DESC, id LIMIT %s''', (today(), today(), limit)).fetchall()


def contacted_today():
    from app.daily_prospects import today
    with db() as c:
        return c.execute('''SELECT COUNT(*) n FROM daily_prospects WHERE batch_date=%s AND (outcome_note LIKE 'autopilot: whatsapp%%' OR outcome_note LIKE 'autopilot: email%%') ''',
                         (today(),)).fetchone()['n']


async def run():
    """One bounded pass. Safe to call every discovery cycle; never resends to a company."""
    stats = {'enabled': enabled(), 'whatsapp': 0, 'email': 0, 'skipped': 0, 'template': None}
    if not stats['enabled']:
        return stats
    from starlette.concurrency import run_in_threadpool
    from app import zernio_whatsapp as wa
    from app.daily_prospects import decide
    from app.spacemail import send as mail_send
    uid = system_user()
    if not uid:
        stats['error'] = 'no_admin_user'
        return stats
    try:
        stats['template'] = await ensure_template()
    except Exception as exc:
        stats['template'] = 'ERROR_' + type(exc).__name__
    room = daily_cap() - contacted_today()
    for item in pending_today(max(0, room)):
        with db() as c:
            reason = already_contacted(c, item['phone'], item['email'])
        if reason:
            decide([item['id']], 'reject', uid, note='autopilot: ' + reason)
            stats['skipped'] += 1
            continue
        pitch = pitch_of(item['message'])
        if not pitch:
            stats['skipped'] += 1
            continue
        text = standard_message(item['company_name'], pitch)
        if item['status'] == 'pending':
            decide([item['id']], 'approve', uid)
        channels = []
        if item['status'] == 'approved' and stats['template'] != 'APPROVED':
            continue  # still waiting for Meta; email was already attempted on the first pass
        if item['phone'] and stats['template'] == 'APPROVED':
            try:
                await wa.send(item['phone'], text, template_prefix='afaaq_marketing_')
                channels.append('whatsapp')
                stats['whatsapp'] += 1
            except wa.WhatsAppBlocked as exc:
                print('AUTO_OUTREACH_WHATSAPP_BLOCKED', item['id'], str(exc)[:160], flush=True)
            except Exception as exc:  # uncertain provider result: stop, never retry automatically
                decide([item['id']], 'contacted', uid, note='autopilot: whatsapp_uncertain')
                stats['stopped'] = 'whatsapp_uncertain:' + type(exc).__name__
                break
        if item['email'] and item['status'] == 'pending':
            try:
                await run_in_threadpool(mail_send, uid, item['email'], SUBJECT, text)
                channels.append('email')
                stats['email'] += 1
            except Exception as exc:
                print('AUTO_OUTREACH_EMAIL_FAILED', item['id'], type(exc).__name__, str(exc)[:160], flush=True)
        if channels:
            decide([item['id']], 'contacted', uid, note='autopilot: ' + '+'.join(channels))
        else:
            # Approved and queued as a call task for the team; WhatsApp waits for Meta template approval.
            with db() as c:
                c.execute("UPDATE daily_prospects SET outcome_note='autopilot: waiting_channel',updated_at=%s WHERE id=%s",
                          (utcnow(), item['id']))
    log(uid, 'prospect_autopilot_run', 'daily_prospect', None,
        f"واتساب {stats['whatsapp']} · بريد {stats['email']} · مستبعد {stats['skipped']} · القالب {stats['template']}")
    return stats
