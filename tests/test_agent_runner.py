import importlib.util, os, pathlib, sys, types
from unittest.mock import Mock, patch
_storage = types.ModuleType('app.storage'); _storage.db = Mock(side_effect=AssertionError('db')); _storage.utcnow = Mock()
with patch.dict(sys.modules, {'app.storage': _storage}):
    _spec = importlib.util.spec_from_file_location('_ar', pathlib.Path(__file__).resolve().parents[1] / 'app' / 'agent_runner.py')
    ar = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ar)
ar.init = lambda: None


def test_domain_allowlist():
    assert ar.domain_allowed('https://fasah.zatca.gov.sa/ar/broker/2.0/')
    assert ar.domain_allowed('https://www.zatca.gov.sa/x')
    assert not ar.domain_allowed('http://fasah.zatca.gov.sa/')
    assert not ar.domain_allowed('https://zatca.gov.sa.evil.com/')
    assert not ar.domain_allowed('https://bank.example.com/pay')
    assert not ar.domain_allowed('http://127.0.0.1/x')
    with patch.dict(os.environ, {'RUNNER_ALLOW_HTTP_LOOPBACK': '1', 'RUNNER_ALLOWED_DOMAINS': '127.0.0.1'}):
        assert ar.domain_allowed('http://127.0.0.1:9/x')
        assert not ar.domain_allowed('http://localhost:9/x')


def test_create_task_refusals_before_any_storage():
    assert ar.create_task('pay_invoice', {})[0] is None
    assert ar.create_task('read_page', {'url': 'https://evil.example.com'})[0] is None
    tid, msg = ar.create_task('fill_form', {'url': 'https://fasah.zatca.gov.sa/x', 'fields': [{'label': 'كلمة المرور', 'value': 'x'}]})
    assert tid is None and 'كلمات المرور' in msg
    assert ar.create_task('fill_form', {'url': 'https://fasah.zatca.gov.sa/x', 'fields': [{'label': 'IBAN', 'value': 'x'}]})[0] is None


def test_only_known_kinds():
    assert set(ar.KINDS) == {'download_test', 'read_page', 'download_file', 'fill_form', 'fasah_declarations', 'fasah_details', 'fasah_release_notice', 'fasah_authorizations', 'inspect_form', 'fasah_fill', 'platform_signup'}
    assert 'application/x-msdownload' not in ar.FILE_TYPES


def test_fasah_params_validated_before_storage():
    assert ar.create_task('fasah_details', {'number': 'abc'})[0] is None
    assert ar.create_task('fasah_declarations', {'since': '1/10/2026'})[0] is None


def test_fasah_fill_is_typing_only_and_refuses_secrets_before_storage():
    tid, msg = ar.create_task('fasah_fill', {'fields': [{'label': 'كلمة المرور', 'value': 'x'}]})
    assert tid is None and 'كلمات المرور' in msg
    assert ar.create_task('fasah_fill', {'fields': []})[0] is None
    assert ar.create_task('fasah_fill', {'fields': [{'label': 'رقم الفاتورة', 'value': '  '}]})[0] is None
    assert 'بدون تقديم' in ar.KINDS['fasah_fill']


def test_platform_signup_refusals_before_storage():
    # a site the manager did not approve is never opened
    assert ar.create_task('platform_signup', {'url': 'https://unknown-platform.example.com/register',
                                              'fields': [{'label': 'الاسم', 'value': 'x'}]})[0] is None
    with patch.dict(os.environ, {'RUNNER_ALLOWED_DOMAINS': 'app.gulf-transports.com'}):
        tid, msg = ar.create_task('platform_signup', {'url': 'https://app.gulf-transports.com/register/',
                                                      'fields': [{'label': 'كلمة المرور', 'value': 'x'}]})
        assert tid is None and 'كلمات المرور' in msg
        assert ar.create_task('platform_signup', {'url': 'https://app.gulf-transports.com/register/', 'fields': []})[0] is None
