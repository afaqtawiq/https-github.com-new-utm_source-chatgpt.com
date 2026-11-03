import importlib.util, pathlib, sys, types
from unittest.mock import Mock, patch
_storage = types.ModuleType('app.storage'); _storage.db = Mock(side_effect=AssertionError('db')); _storage.utcnow = Mock()
with patch.dict(sys.modules, {'app.storage': _storage}):
    _spec = importlib.util.spec_from_file_location('_ar', pathlib.Path(__file__).resolve().parents[1] / 'app' / 'agent_runner.py')
    ar = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ar)


def test_domain_allowlist():
    assert ar.domain_allowed('https://fasah.zatca.gov.sa/ar/broker/2.0/')
    assert ar.domain_allowed('https://www.zatca.gov.sa/x')
    assert not ar.domain_allowed('http://fasah.zatca.gov.sa/')
    assert not ar.domain_allowed('https://zatca.gov.sa.evil.com/')
    assert not ar.domain_allowed('https://bank.example.com/pay')


def test_kinds_are_read_only():
    assert set(ar.KINDS) == {'download_test', 'read_page', 'download_file', 'fasah_declarations'}
