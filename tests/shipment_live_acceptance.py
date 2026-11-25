"""Live shipment file pilot on isolated PostgreSQL with 10 de-identified Jeddah Islamic Port cases
(tests/fixtures/shipment_live_jeddah10.py). Read-only: no WhatsApp, no finance, no change to the existing records.
Set PREVIEW_OUT=/path/file.html to also write the staff page preview."""
import json
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests' / 'fixtures'))


def load(fx):
    from app import agent_runner, container_returns, fasah_tracking, line_desk, shipment_files, shipment_tracking, staff_documents
    from app.storage import db
    for m in (shipment_files, fasah_tracking, shipment_tracking, container_returns, line_desk, staff_documents, agent_runner):
        m.init()
    with db() as c:
        c.execute('DELETE FROM shipment_files')  # drop the built-in seed rows: the pilot runs on the 10 cases only
        for bill, cust, stage, decl, boxes in fx.FILES:
            c.execute('''INSERT INTO shipment_files(bill_no,customer,pod,stage,declaration_no,containers,history,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,'[]',%s,%s)''', (bill, cust, fx.PORT, stage, decl, json.dumps(boxes), fx.t(20), fx.t(24, 18)))
        for num, ref, stage, details, seen, changed, duties in fx.FASAH:
            c.execute('''INSERT INTO fasah_status(number,kind,ref,declared_on,details,stage,first_seen,seen_at,changed_at,duties_since)
                VALUES(%s,'import',%s,'',%s,%s,%s,%s,%s,%s)''', (num, ref, details, stage, fx.t(18), seen, changed, duties))
        for bill, arrived, eta, checked in fx.TRACKS:
            c.execute('''INSERT INTO shipment_tracks(ref,ref_type,status,arrived,eta,created_at,checked_at)
                VALUES(%s,'bill','tracking',%s,%s,%s,%s)''', (bill, arrived, eta, fx.t(20), checked))
        for box, bill, free, est, delivered, status in fx.CONTAINERS:
            c.execute('''INSERT INTO container_returns(container,bill,free_until,free_until_estimated,delivered_on,status,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''', (box, bill, free, est, delivered, status, fx.t(20), fx.t(24)))
        c.execute('''INSERT INTO runner_tasks(kind,params_json,status,created_by,created_at,finished_at)
            VALUES('fasah_declarations','{}','done','متابعة تلقائية',%s,%s)''', (fx.LAST_READ, fx.LAST_READ))
        ids = []
        for name, fields in fx.DOCS:
            ids.append(c.execute('''INSERT INTO staff_documents(sender,filename,mime,data,fields,created_at)
                VALUES('966500000000',%s,'application/pdf',%s,%s,NOW()) RETURNING id''',
                                 (name, b'%PDF-anon', json.dumps(fields, ensure_ascii=False))).fetchone()['id'])
    return ids


def snapshot():
    from app.storage import db
    with db() as c:
        return {t: c.execute(f'SELECT md5(string_agg(x::text, \'|\' ORDER BY x::text)) h FROM {t} x').fetchone()['h']
                for t in ('shipment_files', 'fasah_status', 'shipment_tracks', 'container_returns', 'staff_documents')}


def run():
    import shipment_live_jeddah10 as fx
    from app import shipment_live as sl
    doc_ids = load(fx)
    before = snapshot()

    # 1) Documents: exact unique reference → linked; no reference / several shipments → review, never merged.
    result = sl.link_recent()
    assert result == {'linked': 2, 'review': 2}, result
    from app.storage import db
    with db() as c:
        links = {r['doc_id']: (r['bill_no'], r['matched_by']) for r in c.execute('SELECT * FROM shipment_live_links').fetchall()}
        review = {r['doc_id']: r for r in c.execute('SELECT * FROM shipment_live_review').fetchall()}
    assert links[doc_ids[0]] == ('ANONBL001', 'البوليصة') and links[doc_ids[3]] == ('ANONBL002', 'رقم البيان')
    ambiguous = review[doc_ids[2]]
    assert ambiguous['reason'] == 'ambiguous' and json.loads(ambiguous['candidates_json']) == ['ANONBL003', 'ANONBL010']
    assert review[doc_ids[1]]['reason'] == 'no_reference'
    assert doc_ids[2] not in links  # the ambiguous document is attached to neither shipment
    assert sl.link_document(doc_ids[2], dict(fx.DOCS[2][1])) == ('review', 'ambiguous')  # re-running never merges it
    rtext = sl.review_text()
    assert 'بيان-مختلط.pdf' in rtext and 'أكثر من شحنة' in rtext and 'ANONBL003، ANONBL010' in rtext

    cards = {k['bill_no']: k for k in sl.board(fx.PORT, fx.NOW)}
    assert len(cards) == 10

    # 2) Stale FASAH status (ANONBL004): last seen 22/11, missing from the 08:30 read → never shown as current.
    k4 = cards['ANONBL004']
    assert 'تحت المعالجة' not in k4['status'] and k4['status'] == 'وصلت الميناء' and k4['source'] == 'تتبع الخط الملاحي'
    assert k4['stale_fasah']['label'] == 'تحت المعالجة' and not k4['stale_fasah']['fresh']
    assert 'لم يظهر في آخر قراءة لفسح' in k4['stale_fasah']['why_stale']
    assert k4['blocker'].startswith('حالة فسح غير محدّثة') and k4['owner'].startswith('فيصل')
    assert 'قديمة، ليست الحالة الحالية' in sl.card_text(k4)

    # 3) Fresh statuses carry source and time; blockers and owners from documented facts only.
    assert cards['ANONBL002']['status'].startswith('بانتظار سداد الرسوم') and cards['ANONBL002']['source'] == 'فسح — قراءة جهاز العمل'
    assert cards['ANONBL002']['owner'].startswith('نورة') and cards['ANONBL002']['due'] == '25/11/2026 10:30'
    assert cards['ANONBL003']['blocker'].startswith('تحت الكشف') and '1 مستند بانتظار المطابقة' in cards['ANONBL003']['blocker']
    assert cards['ANONBL010']['review_docs'] == 1 and cards['ANONBL001']['linked_docs'] == 1
    assert cards['ANONBL005']['blocker'].startswith('البيان مقدّم والشحنة لم تصل') and cards['ANONBL005']['due'] == '27/11/2026 18:00'
    assert cards['ANONBL006']['blocker'] == 'وصلت الشحنة ولا يوجد بيان مسجل'
    assert cards['ANONBL009']['status'].startswith('أُرجعت الحاويات')

    # 4) Free-day alerts: documented dates only; estimated ones are listed as estimated, never alerted.
    assert cards['ANONBL001']['owner'].startswith('خالد') and cards['ANONBL001']['due'].startswith('26/11/2026')
    assert any('باقي 1 يوم' in a for a in cards['ANONBL001']['alerts'])
    assert any('متأخرة 1 يوم' in a for a in cards['ANONBL007']['alerts'])
    assert not cards['ANONBL008']['alerts'] and cards['ANONBL008']['estimated_free_days'] == ['ANUU1000081']
    assert 'غير موثّق' in cards['ANONBL008']['due'] and not cards['ANONBL010']['alerts']
    alerts = sl.free_day_alerts(fx.NOW)
    assert len(alerts) == 3 and not any('ANUU1000081' in a for a in alerts)

    # 5) Read-only: the existing records are untouched; nothing was sent.
    assert snapshot() == before
    html_page = sl.page_html(list(cards.values()), rtext, subtitle='10 حالات منزوعة الهوية — ميناء جدة الإسلامي — الساعة 09:00 25/11/2026')
    assert html_page.count('class="card') == 10 and 'قديمة ولا تُعرض كحالة حالية' in html_page
    if os.getenv('PREVIEW_OUT'):
        ordered = sorted(cards.values(), key=lambda k: (not k['alerts'], not k['stale_fasah'], not k['blocker'], k['bill_no']))
        Path(os.environ['PREVIEW_OUT']).write_text(sl.page_html(ordered, rtext, subtitle=
            'تجربة قراءة فقط — 10 حالات تخليص منزوعة الهوية من ميناء جدة الإسلامي — الوقت 09:00 25/11/2026'), encoding='utf-8')
        Path(os.environ['PREVIEW_OUT']).with_suffix('.txt').write_text(
            '\n\n'.join(sl.card_text(k) for k in ordered) + '\n\n' + rtext, encoding='utf-8')

    from app import command_agent, virtual_office
    assert 'shipment_live' in command_agent.HANDLERS
    assert 'shipment_live' in virtual_office.DEPARTMENTS['clearance']['tools']


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'shipment_live_' + secrets.token_hex(5)
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
    print('PASS: live shipment file — 10 de-identified Jeddah cases; ambiguous document held for review; stale FASAH never current; '
          'documented free-day alerts only; existing records unchanged; sends 0.')


if __name__ == '__main__':
    main()
