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


def test_fasah_session_survives_a_browser_restart(tmp_path, monkeypatch):
    """Owner (24 Nov 2026): signing in to FASAH 3+ times a day. A relaunch/self-update keeps the FASAH session."""
    monkeypatch.setattr(rn, 'SESSION_FILE', tmp_path / 'fasah-session.json')

    class Page:
        def __init__(self, url): self.url, self.calls = url, []
        def is_closed(self): return False
        def evaluate(self, js): self.calls.append(js); return '{"token":"abc"}'
        def goto(self, url, **kw): self.url = url
        class mouse:
            @staticmethod
            def move(*a): pass
        class keyboard:
            @staticmethod
            def press(*a): pass

    class Ctx:
        def __init__(self, pages): self.pages, self.added, self.scripts = pages, [], []
        def cookies(self): return [{'name': 's', 'value': 'v', 'domain': 'fasah.zatca.gov.sa'}, {'name': 'x', 'domain': 'other.com'}]
        def add_cookies(self, c): self.added += c
        def add_init_script(self, js): self.scripts.append(js)
        def new_page(self): p = Page('about:blank'); self.pages.append(p); return p

    old = Ctx([Page('https://fasah.zatca.gov.sa/home')])
    rn.save_fasah_session(old)
    new = Ctx([Page('about:blank')])
    assert rn.restore_fasah_session(new) is True
    assert [c['domain'] for c in new.added] == ['fasah.zatca.gov.sa'] and 'token' in new.scripts[0]
    assert new.pages[0].url == 'https://fasah.zatca.gov.sa/home' and not (tmp_path / 'fasah-session.json').exists()
    assert rn.restore_fasah_session(Ctx([])) is False  # nothing saved -> normal sign-in

    page = Page('https://fasah.zatca.gov.sa/home')
    rn._last_refresh[0] = 0
    rn.keep_fasah_alive(Ctx([page]))
    assert any('fetch(location.href' in js for js in page.calls)  # a real request extends the server session
