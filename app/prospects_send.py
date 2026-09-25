"""Prospects: message composition and a single, claimed, logged send step. Never raises.
"""
from app.prospects_schema import *  # noqa: F401,F403


# ---------------------------------------------------------------- outreach

def origin():
    return os.getenv('AFAAQ_PUBLIC_ORIGIN', 'https://gulf-logistics-ai-v7-production.up.railway.app').rstrip('/')


def compose(prospect, step):
    unsubscribe = origin() + '/prospects/unsubscribe/' + prospect['unsubscribe_token']
    greeting = 'السادة ' + prospect['name'] + ' المحترمين،\n\n'
    if step == 1:
        brochure = origin() + '/brochures/afaaq-jeddah-v2.pdf'
        return SUBJECT, greeting + message_text(brochure, unsubscribe), message_html(brochure, unsubscribe), True
    body = (greeting + 'نتابع رسالتنا السابقة بخصوص خدمات آفاق طويق في ميناء جدة الإسلامي.\n\n'
            'إن كانت لديكم شحنة قادمة أو خطة استيراد قريبة، يسعدنا تجهيز عرض مناسب لكم. '
            'يكفي إرسال نوع البضاعة والوزن أو عدد الحاويات وموعد الوصول والوجهة.\n\n'
            'واتساب: ' + PHONE + '\nالبريد: ' + EMAIL + '\nالموقع: ' + WEBSITE + '\n\n'
            'هذه آخر رسالة ضمن هذا التعريف ولن نكرر المراسلة.\nلإيقاف الرسائل: ' + unsubscribe)
    return FOLLOW_UP_SUBJECT, body, None, False


def _brochure():
    from pathlib import Path
    pdf = Path(__file__).parent / 'assets/afaaq-jeddah-brochure.pdf'
    return ('Afaaq_Jeddah_Brochure.pdf', 'application/pdf', pdf.read_bytes()) if pdf.exists() else None


def send_step(prospect, step, user_id, recipient=None):
    """Send one sequence step. Returns (status, detail). Never raises."""
    from app.spacemail import send as official_send
    subject, body, html_body, attach = compose(prospect, step)
    to = recipient or prospect['email']
    test = recipient is not None
    if not test:
        with db() as c:
            claim = c.execute('''INSERT INTO prospect_messages(prospect_id,step,recipient,subject,status,created_at)
                VALUES(%s,%s,%s,%s,'sending',%s) ON CONFLICT DO NOTHING RETURNING id''',
                (prospect['id'], step, to, subject, utcnow())).fetchone()
        if not claim:
            return 'duplicate', 'سبق تنفيذ هذه الخطوة'
    try:
        mid = official_send(user_id, to, subject, body, _brochure() if attach else None, html_body=html_body)
        if not mid:
            raise RuntimeError('لم يرجع خادم البريد معرف رسالة')
    except MailRecipientRejected as exc:
        if not test:
            with db() as c:
                c.execute("UPDATE prospect_messages SET status='rejected',last_error=%s WHERE prospect_id=%s AND step=%s", (str(exc), prospect['id'], step))
                if exc.permanent:
                    c.execute("INSERT INTO marketing_suppressions(channel,recipient,created_at) VALUES('email',%s,%s) ON CONFLICT DO NOTHING", (to, utcnow()))
                c.execute("UPDATE prospects SET status=%s,last_error=%s,updated_at=%s WHERE id=%s",
                          ('bounced' if exc.permanent else prospect['status'], str(exc), utcnow(), prospect['id']))
        log(user_id, 'prospect_email', 'prospect', prospect['id'], f'FAILED step={step} to={to}: {exc}')
        return 'rejected', str(exc)
    except MailConnectionFailed as exc:
        if not test:
            execute('DELETE FROM prospect_messages WHERE prospect_id=? AND step=? AND status=?', (prospect['id'], step, 'sending'))
        log(user_id, 'prospect_email', 'prospect', prospect['id'], f'FAILED step={step} retryable: {exc}')
        return 'retry', str(exc)
    except Exception as exc:
        if not test:
            execute("UPDATE prospect_messages SET status='uncertain',last_error=? WHERE prospect_id=? AND step=?",
                    (str(exc)[:300], prospect['id'], step))
        log(user_id, 'prospect_email', 'prospect', prospect['id'], f'FAILED step={step} uncertain: {str(exc)[:200]}')
        return 'uncertain', str(exc)[:300]
    if not test:
        with db() as c:
            c.execute("UPDATE prospect_messages SET status='sent',provider_message_id=%s,sent_at=%s WHERE prospect_id=%s AND step=%s",
                      (mid, utcnow(), prospect['id'], step))
            c.execute("UPDATE prospects SET status=%s,last_error=NULL,updated_at=%s WHERE id=%s",
                      ('contacted' if step == 1 else 'done', utcnow(), prospect['id']))
    log(user_id, 'prospect_email', 'prospect', prospect['id'], f'SUCCESS step={step} to={to} message_id={mid}')
    return 'sent', mid


