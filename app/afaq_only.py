"""Production entrypoint: the Afaq Tuwaiq WhatsApp number serves Afaq Tuwaiq only.

Shawahid Alhadaf has its own number and account, so the team chooser is skipped and
every conversation on this platform goes straight to the Afaq Tuwaiq agent.
It also installs the brochure campaign cadence (no daily re-sends to the same address).
"""
from app.bootstrap import app  # noqa: F401  (served by run_api.py)
from app import zernio_receiver as _receiver
from app import campaign_cadence  # noqa: F401  (brochure: intro + one follow-up after 7 days, then stop)


def _afaq_only(text, interactive="", previous=None):
    return "afaaq"


_receiver.choose_agent = _afaq_only
