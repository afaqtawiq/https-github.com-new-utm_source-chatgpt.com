"""Production entrypoint: the Afaq Tuwaiq WhatsApp number serves Afaq Tuwaiq only.

Shawahid Alhadaf has its own number and account, so the team chooser is skipped and
every conversation on this platform goes straight to the Afaq Tuwaiq agent.
"""
from app.bootstrap import app  # noqa: F401  (served by run_api.py)
from app import zernio_receiver as _receiver


def _afaq_only(text, interactive="", previous=None):
    return "afaaq"


_receiver.choose_agent = _afaq_only
