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
CHINA_SUBJECT = 'Saudi customs clearance partner for your KSA shipments | 沙特清关合作伙伴 — Afaq Tuwaiq'


def china_message(company):
    """China partner campaign (owner, 21 Nov 2026): English + Chinese, by email (WhatsApp templates are Arabic)."""
    return (f'Hello {company},\n\n'
            'We are Afaq Tuwaiq Customs Clearance & Logistics, a licensed customs broker in Saudi Arabia (licence no. 2513). '
            'We are looking for partner freight forwarders and sourcing agents in China who ship to Saudi Arabia and the GCC.\n\n'
            'For your customers\' shipments we provide:\n'
            '- Customs clearance at all Saudi ports (Jeddah, Dammam, Riyadh Dry Port and land borders) through our own FASAH account\n'
            '- SABER / SFDA compliance follow-up\n'
            '- Importer-of-record service through our registered Saudi company when the consignee needs it\n'
            '- Inland trucking to the customer\'s door in any Saudi city, with daily status updates\n\n'
            'If you ship FCL or LCL to Saudi Arabia, we would be glad to be your clearing partner. '
            'Reply to this email or WhatsApp +966 50 766 5873.\n\n'
            '您好，\n\n'
            '我们是沙特阿拉伯的 Afaq Tuwaiq 清关及物流公司（持牌报关行，执照号 2513）。我们正在寻找向沙特及海湾地区发货的中国货代和采购代理合作伙伴。\n\n'
            '我们可为贵司客户的货物提供：\n'
            '- 沙特所有口岸（吉达港、达曼港、利雅得陆港及陆路口岸）清关，使用我们自己的 FASAH 账户\n'
            '- SABER / SFDA 合规跟进\n'
            '- 如收货人需要，可由我们在沙特注册的公司担任进口商（IOR）\n'
            '- 送货上门至沙特任何城市，并每日更新货物状态\n\n'
            '如贵司有发往沙特的整柜或拼箱货物，欢迎与我们合作。请直接回复本邮件，或通过 WhatsApp 联系 +966 50 766 5873。\n\n'
            'Best regards / 此致\nAfaq Tuwaiq Customs Clearance & Logistics — info@afaqtawiqs.net')


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


def approved_text_enabled():
    """Owner switch: also send the wording Meta already approved when the current wording has no approved template."""
    return os.getenv('AUTO_OUTREACH_APPROVED_TEXT', '0') == '1'


def rendered(template, company_name, pitch):
    """The approved template's own body with {{1}} = company and {{2}} = pitch; None when it takes other parameters."""
    parts = template.get('components') or []
    if not parts or any(str(p.get('type', '')).upper() not in ('BODY', 'FOOTER') for p in parts):
        return None
    text = '\n'.join(p.get('text', '') for p in parts)
    if set(re.findall(r'\{\{(\d+)\}\}', text)) - {'1', '2'}:
        return None
    return text.replace('{{1}}', ' '.join(str(company_name).split())).replace('{{2}}', ' '.join(str(pitch).split()))


def message_options(company_name, pitch):
    """Wordings to try, newest first. With AUTO_OUTREACH_APPROVED_TEXT=1 (owner decision, 20 Nov 2026: «نفذ التواصل»)
    the text of each template Meta approved is also offered, filled with this company's name and pitch."""
    options = [standard_message(company_name, pitch)]
    if approved_text_enabled():
        from app.daily_prospects import _template_v2
        options.append(_template_v2(company_name, pitch) + '\n' + STOP_LINE)
        for item in _approved:
            text = rendered(item, company_name, pitch)
            if text and text not in options:
                options.append(text)
    return options


def sendable(approved, options):
    """The first wording that an approved marketing template can carry, else None — decided locally, with
    no provider call, so prospects that cannot be reached do not eat the WhatsApp rate limit."""
    from app.zernio_whatsapp import template_parameters
    for text in options:
        for item in approved:
            if template_parameters(item, text) is not None:
                return text
    return None


_approved = []


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
        found = await wa.templates(c)
        _approved[:] = [t for t in found if str(t.get('name', '')).startswith('afaaq_marketing_')
                        and t.get('language') == 'ar' and t.get('status') == 'APPROVED']
        for item in found:
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
    """Companies the autopilot contacted TODAY (Riyadh), whatever list day they came from — the cap is per sending day
    (20 Nov 2026: earlier-day companies waiting for the template were not counted and 40 went out in one day)."""
    import datetime as _dt
    start = _dt.datetime.combine(_dt.datetime.now(_dt.timezone(_dt.timedelta(hours=3))).date(), _dt.time(0),
                                 _dt.timezone(_dt.timedelta(hours=3)))
    with db() as c:
        return c.execute('''SELECT COUNT(*) n FROM daily_prospects WHERE updated_at >= %s
            AND (outcome_note LIKE 'autopilot: whatsapp%%' OR outcome_note LIKE 'autopilot: email%%') ''', (start,)).fetchone()['n']


async def run():
    """One bounded pass. Safe to call every discovery cycle; never resends to a company."""
    stats = {'enabled': enabled(), 'whatsapp': 0, 'email': 0, 'skipped': 0, 'template': None}
    if not stats['enabled']:
        return stats
    _approved[:] = []
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
        if item.get('segment') == 'china_partner':
            # China partner campaign: bilingual email only; never an Arabic WhatsApp template to a Chinese company.
            if item['status'] == 'pending':
                decide([item['id']], 'approve', uid)
            if item['email'] and item['status'] == 'pending':
                try:
                    await run_in_threadpool(mail_send, uid, item['email'], CHINA_SUBJECT, china_message(item['company_name']))
                    stats['email'] += 1
                    decide([item['id']], 'contacted', uid, note='autopilot: email china')
                    continue
                except Exception as exc:
                    print('AUTO_OUTREACH_EMAIL_FAILED', item['id'], type(exc).__name__, str(exc)[:160], flush=True)
            with db() as c:
                c.execute("UPDATE daily_prospects SET outcome_note='china: needs email or WeChat',updated_at=%s WHERE id=%s",
                          (utcnow(), item['id']))
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
        wa_text = sendable(_approved, message_options(item['company_name'], pitch)) if item['phone'] else None
        if item['phone'] and stats['template'] == 'APPROVED' and not wa_text:
            # Meta approved a different wording: sending would be refused after several provider calls.
            stats['mismatch'] = stats.get('mismatch', 0) + 1
        if wa_text and stats['template'] == 'APPROVED':
            try:
                await wa.send(item['phone'], wa_text, template_prefix='afaaq_marketing_')
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
    if stats.get('mismatch'):
        print('AUTO_OUTREACH_TEMPLATES', [(t.get('name'), len(re.findall(r'\{\{\d+\}\}', ' '.join(p.get('text', '') for p in t.get('components') or []))))
                                          for t in _approved][:6], flush=True)
        print('AUTO_OUTREACH_TEMPLATE_MISMATCH', stats['mismatch'],
              'القالب المعتمد في Meta لا يطابق نص الرسالة الحالي؛ لم تُجرَّب أي رسالة واتساب', flush=True)
    log(uid, 'prospect_autopilot_run', 'daily_prospect', None,
        f"واتساب {stats['whatsapp']} · بريد {stats['email']} · مستبعد {stats['skipped']} · القالب {stats['template']}")
    return stats
