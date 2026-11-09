"""FASAH live status tracking against disposable, real PostgreSQL (private schema). Nothing is sent: customer
messages are only prepared as «نفذ» codes, and the manager delivery is not called here."""
import datetime as dt
import json
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def database_target():
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in {'postgres', 'postgresql'} or t.hostname not in {'localhost', '127.0.0.1'} or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('AFAAQ_TEST_DATABASE_URL must name local disposable afaaq_test')
    return url


def row(number, details, ref='20261100000001', date='01/11/2026'):
    return {'رقم المرجع': ref, 'رقم البيان': number, 'التاريخ': date, 'التفاصيل': details}


def run():
    from app import agent_runner, fasah_tracking as ft
    from app.storage import db
    ft.init()
    agent_runner.init()
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ)''')
    chat = patch('app.transport_desk.manager_chat', return_value=('966500000001', 'conv-manager'))
    chat.start()
    t0 = dt.datetime(2026, 11, 3, 6, 0, tzinfo=dt.timezone.utc)

    # 1) First sighting is recorded silently.
    first = [row('418900', 'سلة الرحائب للتجارة ميناء جدة الإسلامي تحت المعالجة'),
             row('418901', 'مؤسسة الياسمين ميناء جدة مرحلة إنتظار تحصيل الرسوم الجمركيه'),
             row('ABC', 'سطر غير صالح')]
    assert ft.ingest(first, 'import', now=t0) == []
    with db() as c:
        assert c.execute('SELECT COUNT(*) n FROM fasah_status').fetchone()['n'] == 2
        assert c.execute("SELECT duties_since FROM fasah_status WHERE number='418901'").fetchone()['duties_since'] == t0

    # 2) Same status again: no change, no message.
    assert ft.ingest(first, 'import', now=t0 + dt.timedelta(hours=2)) == []

    # 3) Unknown customer: change reported with instructions to save the number, no send code.
    t1 = t0 + dt.timedelta(hours=4)
    changes = ft.ingest([row('418900', 'سلة الرحائب للتجارة ميناء جدة الإسلامي مرحلة إنتظار تحصيل الرسوم الجمركيه')], 'import', now=t1)
    assert [(x['number'], x['old'], x['new']) for x in changes] == [('418900', 'under_review', 'duties_due')]
    text = ft.change_message(changes)
    assert '418900' in text and 'بانتظار سداد الرسوم' in text and 'رقم المستورد' in text and 'نفذ' not in text

    # 4) Manager saves the importer number; the next change prepares a customer message behind a «نفذ» code.
    assert 'حفظت رقم سلة الرحائب' in ft.save_contact('سلة الرحائب', '0551234567', 'المدير')
    assert ft.save_contact('س', 'x').startswith('اكتب اسم المستورد')
    t2 = t1 + dt.timedelta(hours=2)
    changes = ft.ingest([row('418900', 'سلة الرحائب للتجارة ميناء جدة جاهز لطباعة إشعار الفسح الجمركي')], 'import', now=t2)
    text = ft.change_message(changes)
    assert 'تم الفسح' in text and '+966551234567' in text and 'نفذ ' in text
    with db() as c:
        pend = c.execute('SELECT command FROM whatsapp_voice_pending').fetchall()
        assert len(pend) == 1
        action = json.loads(pend[0]['command'].partition(':')[2])
        assert action['tool'] == 'send_whatsapp' and action['to'] == '+966551234567' and 'تم فسح بيانكم الجمركي رقم 418900' in action['text']
        assert c.execute("SELECT duties_since FROM fasah_status WHERE number='418900'").fetchone()['duties_since'] is None
        assert c.execute('SELECT COUNT(*) n FROM fasah_status_events').fetchone()['n'] == 2

    # 5) Duties waiting more than a day: one alert per declaration per day; not before 24 hours.
    assert ft.duties_alerts(now=t0 + dt.timedelta(hours=20)) == []
    ft.ingest(first[1:2], 'import', now=t0 + dt.timedelta(hours=25))
    alerts = ft.duties_alerts(now=t0 + dt.timedelta(hours=26))
    assert len(alerts) == 1 and '418901' in alerts[0] and 'منذ 1 يوم و2 ساعة' in alerts[0] and 'رقم العميل غير معروف' in alerts[0]
    assert ft.duties_alerts(now=t0 + dt.timedelta(hours=27)) == []

    # 6) Status text + customer's own view (saved number only).
    with db() as c:
        c.execute("UPDATE fasah_status SET seen_at=NOW(), changed_at=NOW()")
    assert '418901' in ft.status_text() and '418900' not in ft.status_text()
    assert ft.status_text('غير موجود').startswith('لا توجد بيانات مفتوحة')
    assert ft.customer_lines('+966551234567') == ['• بيان 418900: تم الفسح ✅']
    assert ft.customer_lines('+966500000099') == []

    # 7) Schedule: only with the work computer online and idle, once per 2 hours, within 7:00-23:00 Riyadh.
    noon = dt.datetime(2026, 11, 3, 9, 0, tzinfo=dt.timezone.utc)  # 12:00 Riyadh
    assert ft.due_reads(now=noon) == []  # no device
    with db() as c:
        c.execute("INSERT INTO runner_devices(name,token_hash,last_seen,created_at) VALUES('trial',%s,%s,%s)",
                  (secrets.token_hex(16), noon, noon))
    ids = ft.due_reads(now=noon)
    assert len(ids) == 2
    with db() as c:
        params = [json.loads(r['params_json']) for r in c.execute('SELECT params_json FROM runner_tasks ORDER BY id').fetchall()]
    assert [p['which'] for p in params] == ['import', 'export'] and all(p['track'] and p['since'] == '2026-10-13' for p in params)
    assert ft.due_reads(now=noon) == []  # busy
    with db() as c:
        c.execute("UPDATE runner_tasks SET status='failed', created_at=%s", (noon,))
        c.execute('UPDATE runner_devices SET last_seen=%s', (noon + dt.timedelta(hours=1),))
    assert ft.due_reads(now=noon + dt.timedelta(hours=1)) == []  # too soon
    night = dt.datetime(2026, 11, 3, 21, 0, tzinfo=dt.timezone.utc)  # 00:00 Riyadh
    with db() as c:
        c.execute('UPDATE runner_devices SET last_seen=%s', (night,))
    assert ft.due_reads(now=night) == []

    # 8) Two failed automatic reads -> one session notice, quiet until a read succeeds.
    assert 'متابعة فسح متوقفة' in ft.session_notice()
    assert ft.session_notice() is None
    ft.read_succeeded()
    # A manual read («افتح فسح») that succeeded after the failed automatic ones proves the session is alive → no notice.
    with db() as c:
        manual = c.execute("""INSERT INTO runner_tasks(kind,params_json,status,created_by,created_at)
            VALUES('fasah_declarations','{}','done','محمد',NOW()) RETURNING id""").fetchone()['id']
    assert ft.session_notice() is None
    with db() as c:
        c.execute('DELETE FROM runner_tasks WHERE id=%s', (manual,))
    assert 'متابعة فسح متوقفة' in ft.session_notice()

    # 9) The runner hook: an automatic read updates tracking and never prepares billing.
    with db() as c:
        tid = c.execute("""INSERT INTO runner_tasks(kind,params_json,status,created_by,created_at)
            VALUES('fasah_declarations',%s,'done',%s,NOW()) RETURNING id""",
                        (json.dumps({'which': 'import', 'track': True}), ft.AUTO_ACTOR)).fetchone()['id']
        csv_text = 'رقم المرجع,رقم البيان,التاريخ,التفاصيل\n20261100000009,418901,01/11/2026,مؤسسة الياسمين فسح كلي\n'
        c.execute("INSERT INTO runner_files(task_id,name,mime,size,sha256,verified,data,created_at) VALUES(%s,'f.csv','text/csv',1,'x',TRUE,%s,NOW())",
                  (tid, ('﻿' + csv_text).encode()))
    sent = []
    with patch.object(agent_runner, 'notify', side_effect=sent.append), patch.object(agent_runner, 'unbilled', side_effect=AssertionError('billing')):
        agent_runner.after_fasah(tid)
    assert len(sent) == 1 and '418901' in sent[0] and 'تم الفسح' in sent[0], sent
    assert ft.session_notice() is None
    chat.stop()
    print('fasah tracking acceptance: OK')


def main():
    import psycopg
    from psycopg import sql
    url = database_target()
    schema = 'fasah_tracking_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        options = '-c search_path=' + schema
        os.environ['DATABASE_URL'] = url + '?' + urlencode({'options': options}, quote_via=quote)
        os.environ.setdefault('ADMIN_EMAIL', 'fasah-tracking@example.invalid')
        os.environ.setdefault('ADMIN_PASSWORD', secrets.token_urlsafe(24))
        os.environ['FASAH_TRACKING'] = '1'
        run()
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    main()
