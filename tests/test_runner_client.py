import importlib.util, pathlib
import pytest
pytest.importorskip('requests')
_spec = importlib.util.spec_from_file_location('afaq_runner', pathlib.Path(__file__).resolve().parents[1] / 'desktop-runner' / 'afaq_runner.py')
rn = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(rn)


class Vault:
    def __init__(self): self.data = {}
    def get_password(self, s, u): return self.data.get((s, u))
    def set_password(self, s, u, p): self.data[(s, u)] = p
    def delete_password(self, s, u): self.data.pop((s, u))


def test_allowlist_rules():
    d = ['fasah.zatca.gov.sa', 'zatca.gov.sa']
    assert rn.allowed('https://fasah.zatca.gov.sa/ar/broker/2.0/', d)
    assert not rn.allowed('http://fasah.zatca.gov.sa/', d)
    assert not rn.allowed('https://zatca.gov.sa.evil.com/', d)
    assert not rn.allowed('http://127.0.0.1:8000/', d)
    assert rn.allowed('http://127.0.0.1:8000/', ['127.0.0.1'], loopback=True)
    assert not rn.allowed('http://localhost:8000/', ['127.0.0.1'], loopback=True)


def test_verify_types(tmp_path):
    good = tmp_path / 'a.pdf'; good.write_bytes(b'%PDF-1.4\nx\n%%EOF\n'); assert rn.verify(good)
    bad = tmp_path / 'b.pdf'; bad.write_bytes(b'%PDF-1.4 broken'); assert not rn.verify(bad)
    empty = tmp_path / 'c.csv'; empty.write_bytes(b''); assert not rn.verify(empty)
    csvf = tmp_path / 'd.csv'; csvf.write_text('a,b\n1,2\n', encoding='utf-8'); assert rn.verify(csvf)
    unknown = tmp_path / 'e.exe'; unknown.write_bytes(b'MZ'); assert not rn.verify(unknown)


def test_token_lives_in_vault_not_files(tmp_path, monkeypatch):
    vault = Vault(); vault.set_password(rn.SERVICE, 'device-token', 'afaq-runner-x')
    assert rn.load_token(vault) == 'afaq-runner-x'
    rn.reset_token(vault)
    assert vault.get_password(rn.SERVICE, 'device-token') is None
    source = (pathlib.Path(rn.__file__)).read_text(encoding='utf-8')
    assert "'token'" not in source.split('def load_server')[1].split('def load_token')[0]


def test_secret_fields_and_sensitive_words():
    assert rn.SECRET_FIELD.search('كلمة المرور') and rn.SECRET_FIELD.search('OTP code') and rn.SECRET_FIELD.search('رقم البطاقة')
    assert not rn.SECRET_FIELD.search('اسم العميل')


def test_api_retries_slow_system_but_never_repeats_claim(monkeypatch):
    calls = []

    class Ok:
        def raise_for_status(self): pass
        def json(self): return {'ok': True}

    def fake(method, url, json=None, headers=None, timeout=None):
        calls.append((method, url, timeout))
        if len(calls) < 3 and not url.endswith('/claim'):
            raise rn.requests.Timeout('slow')
        if url.endswith('/claim'):
            raise rn.requests.Timeout('slow')
        return Ok()
    monkeypatch.setattr(rn.requests, 'request', fake)
    monkeypatch.setattr(rn.time, 'sleep', lambda s: None)
    api = rn.Api('https://x.example', 't')
    assert api.post('/api/runner/tasks/1/step', {'text': 'a'}) == {'ok': True} and len(calls) == 3 and calls[0][2] == 90
    with pytest.raises(rn.requests.Timeout):
        api.post('/api/runner/claim')
    assert len(calls) == 4
