"""Riyadh ceramics segment: pure classification tests, no database."""
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
    spec = importlib.util.spec_from_file_location('_daily_prospects_ceramics_tests', path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'app.storage': storage, 'app.official_mailbox': mailbox}):
        spec.loader.exec_module(module)
    return module

def test_ceramics_segment_and_pitch(dp):
    for name in ('معرض الفخامة للسيراميك', 'Riyadh Porcelain Tiles Co', 'مؤسسة الرخام والجرانيت', 'شركة الأدوات الصحية'):
        key, label, score, pitch = dp.classify(name, '', '')
        assert key == 'ceramics' and score == 35, name
    pitch = dp.classify('سيراميك', '', '')[3]
    for phrase in ('الدمام', 'جدة', 'الميناء الجاف بالرياض', 'فسح', 'للأحمال الثقيلة', 'الرياض'):
        assert phrase in pitch
    assert 'ريال' not in pitch


def test_riyadh_ceramics_ranked_top(dp):
    cer = dp.score_contact({'company_name': 'معرض سيراميك النخبة', 'phone': '0501234567', 'email': 'a@b.sa',
                            'city': 'الرياض', 'activity': '', 'notes': ''})
    food = dp.score_contact({'company_name': 'شركة أغذية', 'phone': '0501234568', 'email': 'c@d.sa',
                             'city': 'جدة', 'activity': '', 'notes': ''})
    assert cer['segment'] == 'ceramics' and cer['city'] == 'الرياض'
    assert cer['score'] > food['score']


def test_uae_carriers_excluded_from_agent(dp):
    assert dp.is_uae_handled({'company_name': 'Trela Shipping', 'city': 'Dubai', 'phone': '+971502980026'})
    assert dp.is_uae_handled({'company_name': 'X', 'email': 'info@trela.ae'})
    assert not dp.is_uae_handled({'company_name': 'معرض سيراميك', 'city': 'الرياض', 'phone': '0501234567'})


def test_saudi_importers_unchanged(dp):
    assert dp.classify('مؤسسة استيراد من الصين', '', '')[0] == 'china'
    assert dp.classify('Riyadh food trading', '', '')[0] == 'food'
