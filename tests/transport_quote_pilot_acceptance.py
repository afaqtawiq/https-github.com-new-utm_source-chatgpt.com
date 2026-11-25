"""WhatsApp transport quote pilot on isolated PostgreSQL. MOCK level: no WhatsApp, no model; the real rate-card and
draft tables and the agent's shadow hook are used. Nothing is sent and no existing price is touched."""
import asyncio
from datetime import date
import json
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = 'عندي حمولة من جدة إلى الرياض، بضاعة: خشب، حاوية ٢٠ قدم، ٢٥ طن، التحميل الخميس، مع رجوع الفارغ، بالرحلة'


def run():
    from app import transport_quote_pilot as ti, whatsapp_agent
    from app.prospect_replies import price_table
    from app.storage import db
    ti.init()
    before = price_table()
    today = date(2026, 11, 25)
    # 1) No approved rate card yet → Khaled, no amount; the base price list (Jeddah→Riyadh 4,500) is never used.
    r = ti.process('acc', 'conv-1', '966500000123', [BASE], today)
    assert r['state'] == 'rate_review' and r['owner'] == 'خالد' and r.get('amount_sar') is None
    # Same request again (reprocessing the same message) → the same draft, stored once.
    assert ti.process('acc', 'conv-1', '966500000123', [BASE], today)['draft_key'] == r['draft_key']
    with db() as c:
        assert c.execute('SELECT COUNT(*) n FROM transport_quote_drafts').fetchone()['n'] == 1
        # An approved card with every condition → Reem's internal draft; an unapproved one is ignored.
        c.execute('''INSERT INTO transport_rate_cards(ref,origin,destination,equipment,max_tons,empty_return,unit,cargo,currency,
            amount_sar,tax_included,charges_terms,valid_from,valid_until,approved,created_at) VALUES
            ('TEST-20','jeddah','riyadh','container_20',25,'true','trip','خشب','SAR',2000,false,'اختبار','2026-11-01','2026-11-30',true,NOW()),
            ('TEST-OFF','jeddah','riyadh','container_20',25,'true','trip','خشب','SAR',1500,false,'اختبار','2026-11-01','2026-11-30',false,NOW())''')
    d = ti.process('acc', 'conv-1', '966500000123', [BASE], today)
    assert d['state'] == 'internal_draft' and d['owner'] == 'ريم' and d['amount_sar'] == 2000 and d['rate_ref'] == 'TEST-20'
    assert d['send_allowed'] is False and d['draft_key'] != r['draft_key']
    # Missing details → only the missing field.
    m = ti.process('acc', 'conv-2', '966500000124', [BASE.replace('مع رجوع الفارغ، ', '')], today)
    assert m['state'] == 'need_details' and m['missing'] == ['هل رجوع الفارغ مشمول؟']
    text = ti.drafts_text()
    assert '📝 مسودة عرض' in text and '2,000 ريال (بطاقة TEST-20)' in text and 'الناقص: هل رجوع الفارغ مشمول؟' in text
    assert 'خشب' not in text and '966500000123' not in text  # no customer text or full number in the staff list
    assert price_table() == before

    # 2) Agent hook: shadow only, behind the closed flag, transport conversations only.
    job = {'account_id': 'acc', 'conversation_id': 'conv-3', 'sender': '966500000125'}
    async def hook(text, history, flag):
        with patch.dict(os.environ, {'TRANSPORT_QUOTE_PILOT': flag}):
            return await whatsapp_agent.transport_quote_shadow(job, text, history)
    assert asyncio.run(hook(BASE, [], '0')) is None
    assert asyncio.run(hook('السلام عليكم', [], '1')) is None
    multi = asyncio.run(hook(BASE.split('، ', 1)[1], [{'question': BASE.split('، ', 1)[0]}], '1'))
    assert multi['state'] == 'internal_draft' and multi['send_allowed'] is False
    with db() as c:
        assert c.execute("SELECT COUNT(*) n FROM transport_quote_drafts WHERE conversation_id='conv-3'").fetchone()['n'] == 1

    from app import command_agent, virtual_office
    assert 'transport_drafts' in command_agent.HANDLERS
    assert 'transport_drafts' in virtual_office.DEPARTMENTS['sales']['tools'] and 'transport_drafts' in virtual_office.DEPARTMENTS['transport']['tools']


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'transport_pilot_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env):
            import app.main  # noqa: F401
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: transport quote pilot — drafts stored once, approved full-condition cards only, Khaled without amount, shadow hook closed by default; sends 0.')


if __name__ == '__main__':
    main()
