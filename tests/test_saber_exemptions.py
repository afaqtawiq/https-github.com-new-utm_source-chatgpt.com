from app import saber_exemptions as se


def test_office_items_match(monkeypatch):
    monkeypatch.setattr(se, '_added', lambda: [])
    for q, name in (('هل الفحم النباتي يحتاج سابر؟', 'الفحم'), ('سلندر غاز الطهي عليه سابر؟', 'غاز الطهي'),
                    ('اسطوانات الغاز تحتاج سابر', 'غاز الطهي'), ('انبوب درب الحقن', 'درب الحقن'),
                    ('IV set import', 'درب الحقن'), ('احواض غسيل للمراكز الصحية', 'أحواض')):
        m = se.match(q)
        assert m and name in m['name'], q
    assert se.match('هل الفحم معفى من سابر؟') is None
    assert se.match('فحم حجري') is None
    assert 'هيئة الغذاء والدواء' in se.reply(se.match('انبوب درب الحقن'))
