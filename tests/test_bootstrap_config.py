"""Synthetic deployment settings only; never read or print real secrets."""
import pytest
from app.bootstrap_config import required_admin_password


@pytest.mark.parametrize('settings',[{}, {'ADMIN_PASSWORD':''}])
def test_missing_or_empty_bootstrap_password_fails_closed(settings):
    with pytest.raises(RuntimeError,match='Administrator bootstrap password is not configured'):
        required_admin_password(settings)


def test_configured_value_is_returned_unchanged():
    settings={'ADMIN_PASSWORD':' synthetic-fixture-value '}
    assert required_admin_password(settings)==settings['ADMIN_PASSWORD']


def test_environment_path_requires_configuration(monkeypatch):
    monkeypatch.delenv('ADMIN_PASSWORD',raising=False)
    with pytest.raises(RuntimeError):
        required_admin_password()
    monkeypatch.setenv('ADMIN_PASSWORD','synthetic-fixture-value')
    assert required_admin_password()=='synthetic-fixture-value'
