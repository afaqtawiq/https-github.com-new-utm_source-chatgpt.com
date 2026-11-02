import asyncio, importlib.util, pathlib, sys, types
from unittest.mock import Mock, patch
import httpx  # noqa: F401
_storage = types.ModuleType('app.storage')
for _n in ('db', 'utcnow'):
    setattr(_storage, _n, Mock(side_effect=AssertionError('storage touched')))
with patch.dict(sys.modules, {'app.storage': _storage}):
    _spec = importlib.util.spec_from_file_location('_ob', pathlib.Path(__file__).resolve().parents[1] / 'app' / 'owner_briefing.py')
    ob = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ob)


def test_alerts_only_on_change(monkeypatch):
    states = {}
    def transition(name, ok, detail):
        prev = states.get(name); states[name] = ok
        if prev == ok: return None
        return 'broken' if not ok else ('recovered' if prev is not None else None)
    monkeypatch.setattr(ob, 'transition', transition)
    async def bad(): return False, 'HTTP 401'
    async def good(): return True, ''
    monkeypatch.setattr(ob, 'CHECKS', {'claude': bad, 'meta': good})
    first = asyncio.run(ob.run_checks())
    assert len(first) == 1 and 'Claude' in first[0]
    assert asyncio.run(ob.run_checks()) == []
    monkeypatch.setattr(ob, 'CHECKS', {'claude': good, 'meta': good})
    assert 'عاد' in asyncio.run(ob.run_checks())[0]
