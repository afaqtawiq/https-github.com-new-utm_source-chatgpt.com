"""Owner request (20 Nov 2026): «ليش نورة ما ترسل كشف الحساب اليومي على شكل PDF». Every evening Noura sends the
owner the current month's account statements (الياسمين، عمران، سلة الرحائب) as PDF files in his WhatsApp chat with
the agent, plus the text summary. When the PDFs cannot be delivered (chat unknown / window closed) the summary with
the printable links is sent instead and the reason is said.
"""
import asyncio
import datetime as dt
import os

RIYADH = dt.timezone(dt.timedelta(hours=3))
HOUR = int(os.getenv('DAILY_STATEMENTS_HOUR', '21'))


def run():
    from app import billing_rules, statement_import, statement_pdf
    from app.virtual_office import owner_chat
    month = dt.datetime.now(RIYADH).strftime('%Y-%m')
    text = statement_import.all_statements([month])
    if not text:
        return ''
    statements = [statement_import.statement(p, month) for p in (billing_rules.YASMEN, billing_rules.OMRAN, billing_rules.SALLA)]
    statements = [s for s in statements if s.get('lines')]
    chat = owner_chat()
    sent, failed = (statement_pdf.send_to_requester(chat, statements) if chat and chat[1] else ([], [s['party'] for s in statements]))
    head = '📊 نورة — كشوفات الحسابات اليومية لشهر ' + month
    if sent:
        head += '\n📎 أرسلت لك ملفات PDF: ' + '، '.join('كشف ' + p for p in sent) + '.'
    if failed:
        head += ('\n⚠️ تعذر إرسال PDF لـ' + '، '.join(failed) + ' (نافذة محادثتك مع الوكيل مغلقة أو غير معروفة). '
                 'أرسل أي رسالة للوكيل ثم اكتب لنورة «أرسل الكشوفات» لتصلك الملفات.')
    return head + '\n\n' + text


def register_worker(app):
    async def loop():
        from starlette.concurrency import run_in_threadpool
        from app.owner_briefing import deliver
        await asyncio.sleep(120)
        done = None
        while True:
            try:
                now = dt.datetime.now(RIYADH)
                if now.hour == HOUR and done != now.date():
                    done = now.date()
                    text = await run_in_threadpool(run)
                    if text:
                        await deliver(text)
                    print('DAILY_STATEMENTS', 'sent' if text else 'empty', flush=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('DAILY_STATEMENTS', type(exc).__name__, str(exc)[:160], flush=True)
            await asyncio.sleep(300)

    @app.on_event('startup')
    async def start():
        app.state.daily_statements_worker = asyncio.create_task(loop())
