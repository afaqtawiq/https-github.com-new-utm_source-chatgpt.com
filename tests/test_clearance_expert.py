from app.clearance_expert import NOTES


def test_notes_cover_the_lecture():
    for k in ('تفويض', 'بوليصة الشحن', 'التفتيش والمعاينة', 'إشعار', 'إذن التسليم', 'الطبليات', 'الأرضيات', 'CIF', 'الرياض الجاف'):
        assert k in NOTES


def test_zatca_rules_cover_key_articles():
    from app.zatca_ports_knowledge import NOTES as R
    for k in ('م3/4', '90 يومًا', '5 سنوات', '15 يومًا', '29 أكتوبر 2025', 'ساعتين', 'SGP', 'RSGT', '15%'):
        assert k in R
    from app.virtual_office import scope
    names = scope('clearance')['tools']
    assert {'zatca_rules', 'port_storage', 'clearance_expert'} <= names
