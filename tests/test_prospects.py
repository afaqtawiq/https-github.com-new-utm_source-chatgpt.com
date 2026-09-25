import importlib
import sys
import types
from unittest.mock import MagicMock, patch
import pytest

# Isolated import: other suites may stub app.storage; supply only what prospects uses.
storage = types.ModuleType("app.storage")
for name in ("db", "execute", "get_session", "log", "one", "rows", "utcnow"):
    setattr(storage, name, MagicMock())
perms = types.ModuleType("app.fine_permissions")
perms.has_permission = MagicMock(return_value=True)
with patch.dict(sys.modules, {"app.storage": storage, "app.fine_permissions": perms}):
    sys.modules.pop("app.prospects", None)
    p = importlib.import_module("app.prospects")
    sys.modules.pop("app.prospects", None)


def test_pick_email_prefers_company_role_mailbox():
    found = ["logo@2x.png", "user@example.com", "ahmad@gmail.com", "Sales@WahaFoods.sa", "info@wahafoods.sa"]
    assert p.pick_email(found, "https://www.wahafoods.sa/ar") in {"sales@wahafoods.sa", "info@wahafoods.sa"}
    assert p.pick_email(["owner@gmail.com"], "https://x.sa") == "owner@gmail.com"
    assert p.pick_email(["me@sentry.io", "a@wixpress.com"], "") == ""


@pytest.mark.parametrize("name,category,types,tier", [
    ("شركة النخبة للتخليص الجمركي", "مخلص جمركي", [], "excluded"),
    ("Fast Cargo Logistics", "Logistics", ["moving_company"], "excluded"),
    ("مطعم السلطان", "مطعم", ["restaurant"], "excluded"),
    ("شركة الشرق لاستيراد وتوزيع المواد الغذائية", "تاجر جملة", ["wholesaler"], "qualified"),
])
def test_qualify(name, category, types, tier):
    place = {"displayName": {"text": name}, "primaryTypeDisplayName": {"text": category}, "types": types, "userRatingCount": 20}
    assert p.qualify(place, "info@x.sa", True, "+966126000000", "https://x.sa")[1] == tier


def test_trading_company_that_also_ships_is_not_a_competitor():
    place = {"displayName": {"text": "شركة الرواد للاستيراد والتصدير والشحن"}, "types": []}
    assert p.qualify(place, "info@x.sa", True, "+966126000000", "https://x.sa")[1] == "qualified"


def test_closed_and_no_mx():
    assert p.qualify({"displayName": {"text": "مصنع"}, "businessStatus": "CLOSED_TEMPORARILY"})[1] == "excluded"
    assert p.qualify({"displayName": {"text": "مصنع حديد"}}, "info@x.sa", False, "+966126000000", "")[1] != "qualified"


def test_private_hosts_are_never_fetched():
    assert not p._public_host("localhost")
    assert not p._public_host("127.0.0.1")
    assert not p._public_host("169.254.169.254")


def test_emails_from_website_follows_contact_page():
    pages = {"https://acme.sa": '<a href="/contact-us">اتصل بنا</a>', "https://acme.sa/contact-us": "راسلونا info@acme.sa"}
    with patch.object(p, "_fetch", side_effect=lambda url, client: (pages.get(url, ""), url)):
        assert p.emails_from_website("https://acme.sa") == ("info@acme.sa", "https://acme.sa/contact-us")


def test_follow_up_has_no_prices_and_announces_stop():
    subject, body, html_body, attach = p.compose({"name": "شركة س", "unsubscribe_token": "t"}, 2)
    assert "ريال" not in body and "لن نكرر" in body and html_body is None and not attach
