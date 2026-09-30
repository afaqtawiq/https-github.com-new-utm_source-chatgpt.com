"""Production entrypoint: the Afaq Tuwaiq WhatsApp number serves Afaq Tuwaiq only.

Shawahid Alhadaf has its own number and account, so the team chooser is skipped and
every conversation on this platform goes straight to the Afaq Tuwaiq agent.
It also installs the brochure campaign cadence (no daily re-sends to the same address),
reads Naqliat load screenshots the owner sends on WhatsApp, and lets the command assistant
understand free-form management messages. Customers are answered in their own language
(Arabic, English or Chinese).
"""
from app.bootstrap import app  # noqa: F401  (served by run_api.py)
from app import zernio_receiver as _receiver
from app import campaign_cadence  # noqa: F401  (brochure: intro + one follow-up after 7 days, then stop)
from app import load_vision  # noqa: F401  (owner load screenshots on WhatsApp are read and registered)
from app import command_ai  # noqa: F401  (management messages are understood in free Arabic)
from app import multilingual  # noqa: F401  (customers are answered in Arabic, English or Chinese)
from app import ai_intake  # noqa: F401  (customer conversations understood by Claude, rule-based fallback)


def _afaq_only(text, interactive="", previous=None):
    return "afaaq"


_receiver.choose_agent = _afaq_only
