"""Weekly scorecard of the virtual office from the office history (no model)."""
import datetime as dt

from app import office_scorecard, virtual_office
from app.storage import db, utcnow


def test_scorecard_counts_per_department():
    virtual_office.init()
    now = utcnow() + dt.timedelta(days=400)   # a window with only this test's rows
    at = now - dt.timedelta(days=1)
    rows = [('transport', 'واتساب عميل', 'طلبت أسعار من 5 سائقين. للإرسال اكتب: نفذ A1B2C3'),
            ('transport', 'قروب', 'أقل سعر 1800 ريال من السائق فهد.'),
            ('transport', 'المنصة', 'تعذر الوصول لقائمة السائقين الآن.'),
            ('clearance', 'واتساب', 'البند 690721 والرسم 5%.')]
    with db() as c:
        for key, channel, reply in rows:
            c.execute('''INSERT INTO office_messages(department,channel,author,command,reply,created_at) VALUES(%s,%s,'t','x',%s,%s)''',
                      (key, channel, reply, at))
    try:
        d = office_scorecard.data(7, now)
        t = {x['key']: x for x in d['depts']}
        assert t['transport']['total'] == 3 and t['transport']['from_whatsapp'] == 2
        assert t['transport']['needs_owner'] == 1 and t['transport']['failed'] == 1 and t['transport']['done_alone'] == 1
        assert t['clearance']['done_alone'] == 1 and t['finance']['total'] == 0
        text = office_scorecard.text(7, now)
        assert 'خالد (النقل' in text and 'أنجزه بنفسه 1 (33%)' in text and 'بدون شغل' in text and 'بيانات ناقصة' in text
    finally:
        with db() as c:
            c.execute('DELETE FROM office_messages WHERE created_at=%s', (at,))
