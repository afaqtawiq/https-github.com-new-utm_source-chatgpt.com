from app.clearance_expert import NOTES


def test_notes_cover_the_lecture():
    for k in ('تفويض', 'بوليصة الشحن', 'التفتيش والمعاينة', 'إشعار', 'إذن التسليم', 'الطبليات', 'الأرضيات', 'CIF', 'الرياض الجاف'):
        assert k in NOTES
