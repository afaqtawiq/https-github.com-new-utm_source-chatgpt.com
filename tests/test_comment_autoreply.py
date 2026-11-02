"""Pure tests for automatic comment replies (no network, no database)."""
import sys, types
from unittest.mock import Mock, patch
_storage = types.ModuleType('app.storage')
for _n in ('db', 'utcnow'):
    setattr(_storage, _n, Mock(side_effect=AssertionError('storage touched')))
with patch.dict(sys.modules, {'app.storage': _storage}):
    import importlib.util, pathlib
    _spec = importlib.util.spec_from_file_location('_ar', pathlib.Path(__file__).resolve().parents[1] / 'app' / 'comment_autoreply.py')
    ar = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ar)


def test_post_ids_from_published_urls():
    assert ar.post_id_from('youtube', 'https://www.youtube.com/watch?v=wChGDz-T-l8') == 'wChGDz-T-l8'
    assert ar.post_id_from('youtube', 'https://youtu.be/abc123XYZ') == 'abc123XYZ'
    assert ar.post_id_from('youtube', 'https://www.youtube.com/shorts/abc123XYZ') == 'abc123XYZ'
    assert ar.post_id_from('tiktok', 'https://www.tiktok.com/@afaqt79/video/7702530286281674004') == '7702530286281674004'
    assert ar.post_id_from('tiktok', 'https://www.tiktok.com/@afaqt79') is None


def test_owner_answered_and_disabled(monkeypatch):
    assert ar.owner_answered({'replies': [{'from': {'isOwner': True}}]})
    assert not ar.owner_answered({'replies': [{'from': {'isOwner': False}}]})
    monkeypatch.delenv('AFAQ_AUTO_COMMENTS', raising=False)
    assert ar.enabled() is False


def test_unsafe_comment_never_gets_reply():
    import asyncio
    assert asyncio.run(ar.compose('كم السعر؟ رقمي 0501234567')) is None
