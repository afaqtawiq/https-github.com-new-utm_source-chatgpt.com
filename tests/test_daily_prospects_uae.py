"""UAE carrier (Batha) segment: pure classification tests, no database."""
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


@pytest.fixture(scope='module')
def dp():
    storage = types.ModuleType('app.storage')
    for name in ('db', 'one', 'rows', 'utcnow', 'get_session', 'log'):
        setattr(storage, name, Mock(side_effect=AssertionError('Pure test touched storage: ' + name)))
    mailbox = types.ModuleType('app.official_mailbox')
    mailbox.ADDRESS = 'info@afaqtawiqs.net'
    path = Path(__file__).resolve().parents[1] / 'app' / 'daily_prospects.py'
    spec = importlib.util.spec_from_file_location('_daily_prospects_uae_tests', path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'app.storage': storage, 'app.official_mailbox': mailbox}):
        spec.loader.exec_module(module)
    return module


def test_uae_carrier_segment_and_pitch(dp):
    key, label, score, pitch = dp.classify('Mega Al Sahar Cargo', 'FTL Dubai to Saudi Arabia', '')
    assert key == 'uae_carrier' and score == 30
    for phrase in ('البطحاء', 'الترانزيت', 'استيراد وتصدير', 'باب عميلكم'):
        assert phrase in pitch
    assert 'ريال' not in pitch


def test_uae_city_scored_and_named(dp):
    info = dp.score_contact({'company_name': 'Trela Shipping', 'phone': '+971502980026', 'email': 'info@trela.ae',
                             'city': 'Dubai', 'activity': '', 'notes': ''})
    assert info['segment'] == 'uae_carrier' and info['city'] == 'دبي'
    assert info['score'] > 80


def test_saudi_importers_unchanged(dp):
    assert dp.classify('مؤسسة استيراد من الصين', '', '')[0] == 'china'
    assert dp.classify('Riyadh food trading', '', '')[0] == 'food'
