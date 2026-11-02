"""Pure tests for the daily poster and the direct Meta connection (no network, no database)."""
import datetime as dt
import importlib.util
import io
import pathlib
import sys
import types
from unittest.mock import Mock, patch

import httpx  # noqa: F401  (imported before patch.dict so it is not unloaded)
from PIL import Image, ImageDraw, ImageFilter, ImageFont, JpegImagePlugin, PngImagePlugin  # noqa: F401

ROOT = pathlib.Path(__file__).resolve().parents[1] / 'app'
_storage = types.ModuleType('app.storage')
for _n in ('db', 'utcnow', 'log', 'one'):
    setattr(_storage, _n, Mock(side_effect=AssertionError('storage touched')))


def _load(name, file):
    with patch.dict(sys.modules, {'app.storage': _storage}):
        spec = importlib.util.spec_from_file_location(name, ROOT / file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


dp = _load('_dp', 'daily_poster.py')
ar = _load('_ar2', 'comment_autoreply.py')


def test_seven_topics_rotate_daily():
    days = [dt.date(2026, 11, 2) + dt.timedelta(days=i) for i in range(7)]
    assert len({dp.topic_for(d)['key'] for d in days}) == 7
    assert dp.topic_for(days[0]) == dp.topic_for(days[0] + dt.timedelta(days=7))


def test_caption_facts_only():
    for t in dp.TOPICS:
        c = dp.caption(t)
        assert '0507665873' in c and 'app.afaqtawiqs.net' in c and '2513' in c and '11/00098402' in c
        for banned in ('ريال', 'سعر', 'أسعار', 'خلال 24', 'ساعة', 'مضمون', 'أرخص'):
            assert banned not in c


def test_poster_is_feed_jpeg():
    from PIL import Image
    raw = dp.render_poster(dp.TOPICS[0])
    with Image.open(io.BytesIO(raw)) as img:
        assert img.format == 'JPEG' and img.size == (1080, 1350)


def test_due_only_after_poster_hour(monkeypatch):
    monkeypatch.setenv('POSTER_HOUR', '19')
    utc = dt.timezone.utc
    assert dp.due(dt.datetime(2026, 11, 2, 15, 59, tzinfo=utc)) is None          # 18:59 Riyadh
    assert dp.due(dt.datetime(2026, 11, 2, 16, 0, tzinfo=utc)) == dt.date(2026, 11, 2)


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv('AFAQ_DAILY_POSTER', raising=False)
    assert dp.enabled() is False


def test_tiktok_settings_public_only():
    creator = {'creator': {'canPostMore': True}, 'privacyLevels': [{'value': 'PUBLIC_TO_EVERYONE'}],
               'commercialContentTypes': [{'value': 'none'}, {'value': 'your_brand'}],
               'postingLimits': {'interactionSettings': {'allow_comment': {'enabled': True}}}}
    s = dp.tiktok_settings(creator)
    assert s['privacy_level'] == 'PUBLIC_TO_EVERYONE' and s['allow_comment'] and s['commercialContentType'] == 'your_brand'
    assert dp.tiktok_settings({'creator': {'canPostMore': False}}) is None


def test_claimed_day_never_republishes():
    with patch.object(dp, 'claim', return_value=False), patch.dict(sys.modules, {'app.storage': _storage}):
        out = dp.run_for(dt.date(2026, 11, 2))
    assert out['skipped'] == 'already_claimed'


def test_meta_comments_skip_own_and_answered():
    conn = {'page_id': 'P', 'token': 't', 'ig_id': 'I', 'ig_username': 'afaqwaiq'}

    def graph(method, path, token, params=None, data=None):
        return {
            'P/posts': {'data': [{'id': 'P_1'}]},
            'P_1/comments': {'data': [
                {'id': 'c1', 'message': 'كيف أتواصل؟', 'from': {'id': 'U'}},
                {'id': 'c2', 'message': 'شكرا', 'from': {'id': 'P'}},
                {'id': 'c3', 'message': 'سؤال', 'from': {'id': 'U'}, 'comments': {'data': [{'from': {'id': 'P'}}]}}]},
            'I/media': {'data': [{'id': 'M1'}]},
            'M1/comments': {'data': [
                {'id': 'i1', 'text': 'وين موقعكم', 'username': 'someone'},
                {'id': 'i2', 'text': 'ok', 'username': 'afaqwaiq'},
                {'id': 'i3', 'text': 'x', 'username': 'u2', 'replies': {'data': [{'username': 'afaqwaiq'}]}}]},
        }[path]

    got = ar.meta_comments(conn, graph)
    assert [(g[0], g[3]) for g in got] == [('facebook', 'c1'), ('instagram', 'i1')]


def test_choose_page_prefers_instagram_handle(monkeypatch):
    stubs = {'app.social_publishing': types.SimpleNamespace(admin=Mock(), cipher=Mock()),
             'app.social_content': types.SimpleNamespace(e=str, page=str)}
    with patch.dict(sys.modules, stubs):
        mc = _load('_mc', 'meta_connect.py')
    monkeypatch.delenv('META_PAGE_ID', raising=False)
    pages = [{'id': '1', 'name': 'Other'}, {'id': '2', 'name': 'Afaq', 'instagram_business_account': {'username': 'afaqwaiq'}}]
    assert mc.choose_page(pages)['id'] == '2'
    import pytest
    with pytest.raises(mc.MetaError):
        mc.choose_page([{'id': '1', 'name': 'Other'}])
