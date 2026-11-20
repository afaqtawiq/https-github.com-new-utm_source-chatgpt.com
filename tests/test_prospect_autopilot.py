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


def test_unapproved_wording_is_not_attempted(mods, monkeypatch):
    """Meta approved the earlier wording: the current one is not tried at all (no provider calls); the approved
    wording is used only when the owner switch is on."""
    dp, ap, extra = mods
    pitch = dp.classify('شركة أغذية', '', '')[3]
    with patch.dict(sys.modules, extra):
        old = dp._template_v2('{{1}}', '{{2}}') + '\n' + ap.STOP_LINE
        approved = [{'name': ap.TEMPLATE, 'language': 'ar', 'status': 'APPROVED',
                     'components': [{'type': 'BODY', 'text': old}]}]
        monkeypatch.delenv('AUTO_OUTREACH_APPROVED_TEXT', raising=False)
        assert ap.sendable(approved, ap.message_options('شركة أغذية', pitch)) is None
        monkeypatch.setenv('AUTO_OUTREACH_APPROVED_TEXT', '1')
        text = ap.sendable(approved, ap.message_options('شركة أغذية', pitch))
        assert text and 'البريد:' not in text and ap.STOP_LINE in text
        current = [{'components': ap.template_spec()['components']}]
        assert 'البريد:' in ap.sendable(current, ap.message_options('شركة أغذية', pitch))


def test_approved_template_body_is_used_as_is(mods, monkeypatch):
    """Production (20 Nov): the approved Meta wording is neither the current nor the guessed older text. With the
    owner switch on, the approved body itself is filled with the company and pitch, so it always matches."""
    dp, ap, extra = mods
    from app.zernio_whatsapp import template_parameters
    pitch = dp.classify('شركة أغذية', '', '')[3]
    body = ('مرحبًا فريق {{1}}،\nمعكم آفاق طويق للتخليص الجمركي والنقل. {{2}}\n'
            'هل لديكم شحنات قادمة؟ للتواصل: 0507665873')
    approved = [{'name': 'afaaq_marketing_v1', 'language': 'ar', 'status': 'APPROVED',
                 'components': [{'type': 'BODY', 'text': body}, {'type': 'FOOTER', 'text': ap.STOP_LINE}]},
                {'name': 'afaaq_marketing_other', 'language': 'ar', 'status': 'APPROVED',
                 'components': [{'type': 'BODY', 'text': 'عرض {{1}} {{2}} {{3}}'}]}]
    with patch.dict(sys.modules, extra):
        ap._approved[:] = approved
        try:
            monkeypatch.delenv('AUTO_OUTREACH_APPROVED_TEXT', raising=False)
            assert ap.sendable(approved, ap.message_options('شركة أغذية\nالمحدودة', pitch)) is None
            monkeypatch.setenv('AUTO_OUTREACH_APPROVED_TEXT', '1')
            text = ap.sendable(approved, ap.message_options('شركة أغذية\nالمحدودة', pitch))
            assert text and text.startswith('مرحبًا فريق شركة أغذية المحدودة') and ap.STOP_LINE in text
            assert template_parameters(approved[0], text) == ['شركة أغذية المحدودة', ' '.join(pitch.split())]
            assert ap.rendered(approved[1], 'x', 'y') is None
        finally:
            ap._approved[:] = []
