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
    from app import agent_runner, container_returns, fasah_tracking, line_desk, shipment_files, shipment_tracking, shipment_workflow, staff_documents
    from app.storage import db
    for m in (shipment_files, shipment_workflow, fasah_tracking, shipment_tracking, container_returns, line_desk, staff_documents, agent_runner):
        m.init()
    with db() as c:
        c.execute('DELETE FROM shipment_files')  # drop the built-in seed rows: the pilot runs on the 10 cases only
        for bill, cust, stage, decl, boxes in fx.FILES:
            c.execute("""INSERT INTO shipment_files(bill_no,customer,pod,stage,declaration_no,containers,history,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,'[]',%s,%s)""", (bill, cust, fx.PORT, stage, decl, json.dumps(boxes), fx.t(20), fx.t(24, 18)))
        # a legacy checklist tick that already exists (made earlier by the name fallback) — must stay as it is
        c.execute("""UPDATE shipment_files SET docs='["bl","invoice"]' WHERE bill_no='ANONBL001'""")
        c.execute("ALTER TABLE fasah_status ADD COLUMN IF NOT EXISTS party TEXT NOT NULL DEFAULT ''")
        for num, ref, declared, stage, details, seen, changed, duties in fx.FASAH:
            c.execute("""INSERT INTO fasah_status(number,kind,ref,declared_on,details,stage,first_seen,seen_at,changed_at,duties_since)
                VALUES(%s,'import',%s,%s,%s,%s,%s,%s,%s,%s)""", (num, ref, declared, details, stage, fx.t(18), seen, changed, duties))
        for bill, arrived, eta, checked in fx.TRACKS:
            c.execute("""INSERT INTO shipment_tracks(ref,ref_type,status,arrived,eta,created_at,checked_at)
                VALUES(%s,'bill','tracking',%s,%s,%s,%s)""", (bill, arrived, eta, fx.t(20), checked))
        for box, bill, free, est, delivered, status in fx.CONTAINERS:
            c.execute("""INSERT INTO container_returns(container,bill,free_until,free_until_estimated,delivered_on,status,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""", (box, bill, free, est, delivered, status, fx.t(20), fx.t(24)))
        for at, params, cov in fx.READS:
            add_read(c, at, params, cov)
        ids = []
        for name, fields, _ in fx.DOCS:
            ids.append(c.execute("""INSERT INTO staff_documents(sender,filename,mime,data,fields,created_at)
                VALUES('966500000000',%s,'application/pdf',%s,%s,NOW()) RETURNING id""",
                                 (name, b'%PDF-anon', json.dumps(fields, ensure_ascii=False))).fetchone()['id'])
    return ids


def add_read(c, at, params, cov):
    c.execute("""INSERT INTO runner_tasks(kind,params_json,status,created_by,result_json,created_at,finished_at)
        VALUES('fasah_declarations',%s,'done','متابعة تلقائية',%s,%s,%s)""",
              (json.dumps(params, ensure_ascii=False), json.dumps({'coverage': cov} if cov else {}, ensure_ascii=False), at, at))


def snapshot():
    from app.storage import db
    with db() as c:
        return {t: c.execute(f"SELECT md5(string_agg(x::text, '|' ORDER BY x::text)) h FROM {t} x").fetchone()['h']
                for t in ('shipment_files', 'fasah_status', 'shipment_tracks', 'container_returns', 'staff_documents')}


def run():
    import shipment_live_jeddah10 as fx
    from app import shipment_live as sl
    from app.storage import db
    doc_ids = load(fx)
    before = snapshot()

    # 1) Documents: linked ONLY when every reference agrees on one shipment; one test per case.
    result = sl.link_recent()
    assert result == {'linked': 3, 'review': 4}, result
    with db() as c:
        links = {r['doc_id']: r for r in c.execute('SELECT * FROM shipment_live_links').fetchall()}
        review = {r['doc_id']: r for r in c.execute('SELECT * FROM shipment_live_review').fetchall()}
    for doc_id, (name, fields, (state, expect)) in zip(doc_ids, fx.DOCS):
        if state == 'linked':
            assert links[doc_id]['bill_no'] == expect and doc_id not in review, (name, links.get(doc_id))
        else:
            assert doc_id not in links and review[doc_id]['reason'] == expect, (name, review.get(doc_id))
    assert links[doc_ids[6]]['matched_by'] == 'البوليصة + الحاوية + رقم البيان'                 # all three agree
    assert json.loads(review[doc_ids[2]]['candidates_json']) == ['ANONBL003', 'ANONBL010']      # conflicting
    assert json.loads(review[doc_ids[5]]['candidates_json']) == ['ANONBL001']                   # known bill + unknown container
    assert json.loads(review[doc_ids[4]]['candidates_json']) == []                              # customer name only
    assert sl.link_document(doc_ids[2], dict(fx.DOCS[2][1])) == ('review', 'ambiguous')        # re-running never merges
    rtext = sl.review_text()
    for words in ('المراجع تشير لأكثر من شحنة', 'فيه مرجع لا يطابق أي شحنة مسجلة', 'ما فيه إلا اسم العميل', 'لا يحمل رقم بوليصة'):
        assert words in rtext, words

    # 2) Legacy name fallback (shipment_workflow.note_document) — tested OFF on this branch; old ticks untouched.
    from app import shipment_workflow
    name_doc = {'document_kind': 'commercial_invoice', 'consignee': 'عميل أ'}
    with patch.dict(os.environ, {'DOC_LINK_BY_NAME': '0'}):
        assert shipment_workflow.note_document(name_doc) is None
    with db() as c:
        assert c.execute("SELECT docs FROM shipment_files WHERE bill_no='ANONBL001'").fetchone()['docs'] == '["bl","invoice"]'
    assert snapshot() == before

    # 3) FASAH freshness — ANONBL004 (declared 20/11, last seen 22/11). Newer reads that do NOT prove it is gone:
    #    another importer's filtered list, a read stopped at its page limit, an export read, a read with no coverage proof.
    cards = {k['bill_no']: k for k in sl.board(fx.PORT, fx.NOW)}
    assert len(cards) == 10
    k4 = cards['ANONBL004']
    assert k4['stale_fasah']['state'] == 'unverified' and 'تحت المعالجة' not in k4['status']
    assert k4['status'] == 'وصلت الميناء' and k4['source'] == 'تتبع الخط الملاحي'
    assert k4['stale_fasah']['why_stale'] == 'تعذر التحقق: لا توجد قراءة كاملة أحدث تشمل هذا البيان'
    assert k4['blocker'].startswith('حالة فسح غير مؤكدة') and 'آخر حالة معروفة في فسح: تحت المعالجة — 22/11/2026 11:30' in sl.card_text(k4)
    # Fresh statuses are current whatever the other reads say.
    assert cards['ANONBL002']['status'].startswith('بانتظار سداد الرسوم') and cards['ANONBL002']['source'] == 'فسح — قراءة جهاز العمل'
    # A complete, unfiltered import read whose window (04/11+) covers 20/11 → confirmed missing.
    with db() as c:
        add_read(c, *fx.COVERING_READ)
    k4b = sl.build(dict(sl_row('ANONBL004')), fx.NOW)
    assert k4b['stale_fasah']['state'] == 'missing' and 'لم يظهر في قراءة كاملة لفسح تشمل نطاقه (25/11/2026 08:45)' in k4b['stale_fasah']['why_stale']
    assert k4b['blocker'].startswith('البيان غاب عن قراءة فسح الكاملة') and k4b['status'] == 'وصلت الميناء'
    # …but not when its window starts after the declaration date (20/11): same read with since 21/11 proves nothing.
    with db() as c:
        c.execute("UPDATE runner_tasks SET result_json=replace(result_json,'2026-11-04','2026-11-21'), "
                  "params_json=replace(params_json,'2026-11-04','2026-11-21') WHERE finished_at=%s", (fx.COVERING_READ[0],))
    assert sl.build(dict(sl_row('ANONBL004')), fx.NOW)['stale_fasah']['state'] == 'unverified'

    # 4) Blockers, owners and free-day alerts (documented dates only).
    assert cards['ANONBL002']['owner'].startswith('نورة') and cards['ANONBL002']['due'] == '25/11/2026 10:30'
    assert cards['ANONBL003']['blocker'].startswith('تحت الكشف') and '1 مستند بانتظار المطابقة' in cards['ANONBL003']['blocker']
    assert cards['ANONBL010']['review_docs'] == 1 and cards['ANONBL001']['linked_docs'] == 1 and cards['ANONBL001']['review_docs'] == 1
    assert cards['ANONBL005']['due'] == '27/11/2026 18:00' and cards['ANONBL006']['blocker'] == 'وصلت الشحنة ولا يوجد بيان مسجل'
    assert any('باقي 1 يوم' in a for a in cards['ANONBL001']['alerts']) and any('متأخرة 1 يوم' in a for a in cards['ANONBL007']['alerts'])
    assert not cards['ANONBL008']['alerts'] and cards['ANONBL008']['estimated_free_days'] == ['ANUU1000081']
    alerts = sl.free_day_alerts(fx.NOW)
    assert len(alerts) == 3 and not any('ANUU1000081' in a for a in alerts)

    # 5) Read-only on the existing records (the pilot writes only its own link/review tables).
    assert snapshot() == before
    if os.getenv('PREVIEW_OUT'):
        ordered = sorted(cards.values(), key=lambda k: (not k['alerts'], not k['stale_fasah'], not k['blocker'], k['bill_no']))
        Path(os.environ['PREVIEW_OUT']).write_text(sl.page_html(ordered, rtext, subtitle=
            'تجربة قراءة فقط — 10 حالات تخليص منزوعة الهوية من ميناء جدة الإسلامي — الوقت 09:00 25/11/2026'), encoding='utf-8')
        Path(os.environ['PREVIEW_OUT']).with_suffix('.txt').write_text(
            '\n\n'.join(sl.card_text(k) for k in ordered) + '\n\n' + rtext, encoding='utf-8')

    # 6) A FRESH status (ANONBL002, seen 08:30 today) loses «current» when a later complete read of the same scope
    #    (import, window 04/11+, no importer filter) finished at 08:50 without it — even though it is < 6 hours old.
    with db() as c:
        c.execute("DELETE FROM runner_tasks WHERE finished_at=%s", (fx.COVERING_READ[0],))
        add_read(c, fx.t(25, 8, 50), {'which': 'import', 'since': '2026-11-04', 'pages': 20},
                 {'complete': False, 'end': 'page_stuck', 'which': 'import', 'party': '', 'since': '2026-11-04'})
    k2 = sl.build(dict(sl_row('ANONBL002')), fx.NOW)
    assert k2['stale_fasah'] is None and k2['source'] == 'فسح — قراءة جهاز العمل'       # a stuck (incomplete) read proves nothing
    with db() as c:
        add_read(c, fx.t(25, 8, 55), {'which': 'import', 'since': '2026-11-04', 'pages': 20},
                 {'complete': True, 'end': 'last_page', 'which': 'import', 'party': '', 'since': '2026-11-04'})
    k2 = sl.build(dict(sl_row('ANONBL002')), fx.NOW)
    assert k2['stale_fasah']['state'] == 'missing' and not k2['stale_fasah']['fresh']
    assert 'لم يظهر في قراءة كاملة لفسح تشمل نطاقه (25/11/2026 08:55)' in k2['stale_fasah']['why_stale']
    assert k2['source'] != 'فسح — قراءة جهاز العمل' and 'بانتظار سداد الرسوم الجمركية (بيان' not in k2['status']
    assert 'آخر حالة معروفة في فسح: بانتظار سداد الرسوم الجمركية — 25/11/2026 08:30' in sl.card_text(k2)
    assert snapshot() == before

    # 7) Legacy behaviour in production is unchanged (flag default = on): the name fallback still ticks files.
    assert shipment_workflow.note_document(name_doc)
    from app import command_agent, virtual_office
    assert 'shipment_live' in command_agent.HANDLERS and 'shipment_live' in virtual_office.DEPARTMENTS['clearance']['tools']


def sl_row(bill):
    from app.storage import db
    with db() as c:
        return c.execute('SELECT * FROM shipment_files WHERE bill_no=%s', (bill,)).fetchone()


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
