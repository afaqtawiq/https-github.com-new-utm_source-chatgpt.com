"""Autopilot message must match its WhatsApp template exactly; pure tests, no database."""
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, rel, extra):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, extra):
        spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def mods():
    storage = types.ModuleType('app.storage')
    for n in ('db', 'one', 'rows', 'utcnow', 'get_session', 'log', 'execute'):
        setattr(storage, n, Mock(side_effect=AssertionError('storage touched: ' + n)))
    mailbox = types.ModuleType('app.official_mailbox')
    mailbox.ADDRESS = 'info@afaqtawiqs.net'
    dp = load('_dp_auto', 'app/daily_prospects.py', {'app.storage': storage, 'app.official_mailbox': mailbox})
    extra = {'app.storage': storage, 'app.daily_prospects': dp, 'app.official_mailbox': mailbox}
    ap = load('_ap_auto', 'app/prospect_autopilot.py', extra)
    return dp, ap, extra


def test_template_matches_standard_message(mods):
    dp, ap, extra = mods
    from app.zernio_whatsapp import template_parameters
    with patch.dict(sys.modules, extra):
        spec = ap.template_spec()
        pitch = dp.classify('معرض سيراميك النخبة', '', '')[3]
        message = ap.standard_message('معرض سيراميك النخبة', pitch)
    template = {'components': spec['components']}
    assert template_parameters(template, message) == ['معرض سيراميك النخبة', pitch]
    assert ap.STOP_LINE in message and len(spec['components'][0]['text']) < 1024


def test_pitch_recovered_from_ai_draft(mods):
    dp, ap, extra = mods
    pitch = dp.classify('شركة أغذية', '', '')[3]
    draft = dp._with_opening(dp.template_message('شركة أغذية', pitch), 'افتتاحية مخصصة من الذكاء الاصطناعي.')
    with patch.dict(sys.modules, extra):
        assert ap.pitch_of(draft) == pitch.strip()


def test_disabled_by_default(mods, monkeypatch):
    _, ap, _ = mods
    monkeypatch.delenv('AUTO_OUTREACH', raising=False)
    assert ap.enabled() is False
    monkeypatch.setenv('AUTO_OUTREACH', '1'); monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS', '1')
    assert ap.enabled() is True
