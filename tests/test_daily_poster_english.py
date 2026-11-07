"""Offline tests: no production DB, secrets, provider requests or publishing."""
import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import types
from unittest.mock import Mock, patch
import pytest
from PIL import Image, JpegImagePlugin, PngImagePlugin

ROOT = Path(__file__).resolve().parents[1]
_storage = types.ModuleType('app.storage')
for name in ('db', 'utcnow', 'log', 'one'):
    setattr(_storage, name, Mock(side_effect=AssertionError('real storage forbidden')))

def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'app' / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

with patch.dict(sys.modules, {'app.storage': _storage}):
    ar = load('_poster_ar', 'daily_poster.py')
with patch.dict(sys.modules, {'app.storage': _storage, 'app.daily_poster': ar}):
    en = load('_poster_en', 'daily_poster_english.py')
DAY = dt.date(2026, 11, 8)
MORNING = dt.datetime(2026, 11, 8, 6, 0, tzinfo=dt.timezone.utc)

def test_arabic_is_byte_for_byte_unchanged():
    assert hashlib.sha256((ROOT / 'app/daily_poster.py').read_bytes()).hexdigest() == 'b812d58e9e1653da20e0f240f8a3377a851d5af1a9cfd1669ff3a6be8fa7f7b0'

def test_independent_and_global_activation_gates(monkeypatch):
    monkeypatch.setenv('AFAQ_DAILY_POSTER', '1')
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS', '1')
    monkeypatch.delenv('AFAQ_DAILY_POSTER_EN', raising=False)
    assert not en.enabled()
    monkeypatch.setenv('AFAQ_DAILY_POSTER_EN', '1')
    assert en.enabled()
    monkeypatch.setenv('ENABLE_EXTERNAL_ACTIONS', '0')
    assert not en.enabled()

@pytest.mark.parametrize('hour,minute,expected', [(5,59,None),(6,0,DAY),(8,59,DAY),(9,0,None),(16,0,None),(23,0,None)])
def test_morning_window(monkeypatch, hour, minute, expected):
    monkeypatch.delenv('POSTER_EN_HOUR', raising=False)
    assert en.due(MORNING.replace(hour=hour, minute=minute)) == expected

@pytest.mark.parametrize('value,expected', [('0',9),('19',9),('-1',9),('no',9),('8',8),('11',11)])
def test_config_cannot_turn_morning_into_evening(monkeypatch, value, expected):
    monkeypatch.setenv('POSTER_EN_HOUR', value)
    monkeypatch.setenv('POSTER_HOUR', '20')
    assert en.poster_hour() == expected
    assert ar.poster_hour() == 20

def test_english_topics_and_facts():
    assert [t['key'] for t in en.TOPICS] == [t['key'] for t in ar.TOPICS]
    for i in range(7):
        day = DAY + dt.timedelta(days=i)
        topic = en.topic_for(day)
        assert topic['key'] == ar.topic_for(day)['key']
        assert topic == en.topic_for(day + dt.timedelta(days=7))
        caption = en.caption(topic)
        assert all(fact in caption for fact in ('0507665873','0530130435','app.afaqtawiqs.net','2513','11/00098402'))
        assert not any('\u0600' <= c <= '\u06ff' for c in caption)
        assert len(caption) < 2200
        assert not any(s in caption.lower() for s in ('guaranteed','cheapest','24 hours','sar ','free'))

@pytest.mark.parametrize('topic', en.TOPICS, ids=lambda t:t['key'])
def test_english_poster_dimensions(topic):
    with Image.open(io.BytesIO(en.render_poster(topic))) as image:
        assert image.format == 'JPEG' and image.size == (1080,1350)

def test_video_frame_dimensions():
    with Image.open(io.BytesIO(en.video_frame(en.render_poster(en.TOPICS[0])))) as image:
        assert image.size == (1080,1920)

def test_media_urls_do_not_collide():
    assert en.media_urls(DAY) != ar.media_urls(DAY)
    assert all('/daily-poster-en/' in url for url in en.media_urls(DAY))

def test_atomic_independent_claim(monkeypatch):
    c = Mock()
    c.execute.return_value.fetchone.return_value = {'day':DAY}
    monkeypatch.setattr(en, 'db', lambda:contextlib.nullcontext(c))
    monkeypatch.setattr(en, 'utcnow', lambda:MORNING)
    en.init()
    assert 'CREATE TABLE IF NOT EXISTS afaq_daily_posters_en' in c.execute.call_args.args[0]
    assert 'day DATE PRIMARY KEY' in c.execute.call_args.args[0]
    assert en.claim(DAY,en.TOPICS[0],'text')
    assert 'INSERT INTO afaq_daily_posters_en(' in c.execute.call_args.args[0]
    assert 'ON CONFLICT DO NOTHING RETURNING day' in c.execute.call_args.args[0]
    c.execute.return_value.fetchone.return_value = None
    assert not en.claim(DAY,en.TOPICS[0],'text')

def test_disabled_and_late_runs_do_not_claim(monkeypatch):
    claim = Mock(side_effect=AssertionError('claim forbidden'))
    monkeypatch.setattr(en,'claim',claim)
    monkeypatch.setattr(en,'enabled',lambda:False)
    assert en.run_for(DAY,MORNING)['skipped'] == 'disabled'
    monkeypatch.setattr(en,'enabled',lambda:True)
    assert en.run_for(DAY,MORNING.replace(hour=16))['skipped'] == 'outside_morning_window'
    claim.assert_not_called()

def test_duplicate_does_not_render(monkeypatch):
    monkeypatch.setattr(en,'enabled',lambda:True)
    monkeypatch.setattr(en,'claim',lambda *a:False)
    render=Mock(side_effect=AssertionError('render forbidden'))
    monkeypatch.setattr(en,'render_poster',render)
    assert en.run_for(DAY,MORNING)['skipped'] == 'already_claimed'
    render.assert_not_called()

@pytest.mark.parametrize('state,expected',[('publishing','pending'),('scheduled','pending'),('submitting','pending'),('partial','partial'),('needs_review','partial'),('published','published')])
def test_accepted_is_not_published(state,expected):
    results={'facebook':{'status':'published'},'instagram':{'status':'published'},'youtube_tiktok':{'status':state,'tiktok':True},'drafts':{'status':'saved'}}
    assert en.final_status(results) == expected
    results['youtube_tiktok']['tiktok']=False
    assert en.final_status(results) == 'partial'

@pytest.mark.parametrize('name',['bad.jpg','2026-11-08.png','../2026-11-08.jpg','2026-11-08.jpg.extra'])
def test_media_rejects_invalid_names(name):
    with pytest.raises(en.HTTPException) as exc:
        en.public_media(name)
    assert exc.value.status_code == 404

@pytest.mark.parametrize('timeout',[False,True])
def test_existing_video_accounts_and_no_retries(monkeypatch, timeout):
    c=Mock()
    c.execute.return_value.fetchone.return_value={'id':5}
    monkeypatch.setattr(en,'db',lambda:contextlib.nullcontext(c))
    monkeypatch.setattr(en,'utcnow',lambda:MORNING)
    provider=Mock(side_effect=TimeoutError('fixture') if timeout else None,return_value={})
    save=Mock()
    sp=types.SimpleNamespace(connection=lambda:('fixture-key',{}),save_result=save)
    sz=types.SimpleNamespace(creator_info=lambda *a:{'creator':{'canPostMore':True},'privacyLevels':[{'value':'PUBLIC_TO_EVERYONE'}],'commercialContentTypes':[{'value':'your_brand'}]},verified_accounts=lambda *a:{'youtube':{'accountId':'YT'},'tiktok':{'accountId':'TT'}},provider_request=provider,publication_result=lambda *a:('POST','publishing',[]))
    with patch.dict(sys.modules,{'app.social_publishing':sp,'app.social_zernio':sz}):
        if timeout:
            with pytest.raises(TimeoutError):
                en.publish_video(DAY,en.TOPICS[0],'text',en.media_urls(DAY)[1],1,guard=lambda:None)
            assert save.call_args.args[2] == 'needs_review'
        else:
            out=en.publish_video(DAY,en.TOPICS[0],'text',en.media_urls(DAY)[1],1,guard=lambda:None)
            assert out['status']=='publishing' and out['tiktok']
    provider.assert_called_once()
    payload=provider.call_args.kwargs['payload']
    assert [p['accountId'] for p in payload['platforms']] == ['YT','TT']
    assert payload['metadata']=={'afaqDailyPoster':'2026-11-08','language':'en'}
    assert payload['timezone']=='Asia/Riyadh'
    assert payload['mediaItems'][0]['url'].endswith('/daily-poster-en/2026-11-08.mp4')
    assert payload['title']=='Afaq Tuwaiq | Customs Clearance'
    assert payload['tiktokSettings']['commercialContentType']=='your_brand'
    assert payload['platforms'][0]['platformSpecificData']['madeForKids'] is False
    assert 'UPDATE afaq_daily_posters_en' in c.execute.call_args.args[0]

def test_x_linkedin_only_drafts(monkeypatch):
    c=Mock()
    c.execute.return_value.fetchone.return_value={'id':8}
    monkeypatch.setattr(en,'db',lambda:contextlib.nullcontext(c))
    monkeypatch.setattr(en,'utcnow',lambda:MORNING)
    assert en.save_drafts(DAY,en.TOPICS[0],'text','https://example.invalid/image.jpg',1)==[8,8]
    assert [call.args[1][1] for call in c.execute.call_args_list] == ['X','LinkedIn']
    assert all("'draft'" in call.args[0] for call in c.execute.call_args_list)

def test_disabled_tick_does_not_sync(monkeypatch):
    monkeypatch.setattr(en,'enabled',lambda:False)
    sync=Mock(side_effect=AssertionError('provider forbidden'))
    monkeypatch.setattr(en,'sync_pending',sync)
    assert en.tick(MORNING) is None
    sync.assert_not_called()

@pytest.mark.parametrize('failure',[None,'facebook','credentials','render'])
def test_bounded_run_isolated_failures_and_no_second_publish(monkeypatch,failure):
    c=Mock()
    monkeypatch.setattr(en,'db',lambda:contextlib.nullcontext(c))
    monkeypatch.setattr(en,'utcnow',lambda:MORNING)
    monkeypatch.setattr(en,'log',Mock())
    monkeypatch.setattr(en,'enabled',lambda:True)
    monkeypatch.setattr(en,'claim',Mock(side_effect=[True,False]))
    monkeypatch.setattr(en,'render_poster',Mock(side_effect=ValueError() if failure=='render' else None,return_value=b'jpeg'))
    monkeypatch.setattr(en,'render_video',Mock(return_value=b'mp4'))
    monkeypatch.setattr(en,'set_result',Mock())
    monkeypatch.setattr(en,'save_drafts',Mock(return_value=[8,9]))
    monkeypatch.setattr(en,'record_meta',Mock())
    fb=Mock(side_effect=TimeoutError() if failure=='facebook' else None,return_value={'status':'published','id':'F','url':'https://facebook.com/F'})
    ig=Mock(return_value={'status':'published','id':'I','url':'https://instagram.com/I'})
    video=Mock(return_value={'status':'publishing','tiktok':True,'content_id':10})
    monkeypatch.setattr(ar,'publish_facebook',fb)
    monkeypatch.setattr(en,'publish_instagram',ig)
    monkeypatch.setattr(en,'publish_video',video)
    meta=types.SimpleNamespace(connected=lambda:True,credentials=Mock(side_effect=ValueError() if failure=='credentials' else None,return_value={'page_id':'fixture'}))
    with patch.dict(sys.modules,{'app.prospect_autopilot':types.SimpleNamespace(system_user=lambda:1),'app.meta_connect':meta}):
        out=en.run_for(DAY,MORNING)
        second=en.run_for(DAY,MORNING)
    assert second['skipped']=='already_claimed'
    assert out['status']==('pending' if failure is None else ('needs_review' if failure=='render' else 'partial'))
    assert fb.call_count==(1 if failure in (None,'facebook') else 0)
    assert ig.call_count==(1 if failure in (None,'facebook') else 0)
    assert video.call_count==(0 if failure=='render' else 1)
    assert all('afaq_daily_posters_en' in call.args[0] for call in c.execute.call_args_list)


def test_confirmed_sync_updates_english_record_without_new_post(monkeypatch):
    c=Mock()
    import json
    results={'facebook':{'status':'published'},'instagram':{'status':'published'},'youtube_tiktok':{'status':'publishing','tiktok':True}}
    c.execute.return_value.fetchall.return_value=[{'day':DAY,'results_json':json.dumps(results),'content_id':10,'provider_post_id':'POST','payload_json':json.dumps({'platforms':[{'platform':'youtube'},{'platform':'tiktok'}]}),'status':'publishing'}]
    monkeypatch.setattr(en,'db',lambda:contextlib.nullcontext(c))
    monkeypatch.setattr(en,'utcnow',lambda:MORNING)
    provider=Mock(return_value={})
    sp=types.SimpleNamespace(connection=lambda:('fixture',{}),save_result=Mock())
    sz=types.SimpleNamespace(identifier=lambda x:x,provider_request=provider,publication_result=lambda *a:('POST','published',[{'platform':'youtube','status':'published','url':'https://youtube.com/fixture'},{'platform':'tiktok','status':'published','url':'https://tiktok.com/fixture'}]))
    with patch.dict(sys.modules,{'app.social_publishing':sp,'app.social_zernio':sz}):
        assert en.sync_pending()==1
    provider.assert_called_once_with('fixture','GET','/posts/POST')
    assert c.execute.call_args.args[1][0]=='published'
    assert 'UPDATE afaq_daily_posters_en' in c.execute.call_args.args[0]


def test_cutoff_during_instagram_processing_does_not_publish(monkeypatch):
    guard=Mock(side_effect=[None,en.PublicationWindowClosed()])
    graph=Mock(side_effect=[{'id':'CONTAINER'},{'status_code':'FINISHED'}])
    meta=types.SimpleNamespace(MetaError=RuntimeError,graph=graph)
    with patch.dict(sys.modules,{'app.meta_connect':meta}):
        with pytest.raises(en.PublicationWindowClosed):
            en.publish_instagram({'ig_id':'IG','token':'fixture'},'https://example.invalid/a.jpg','caption',guard)
    assert graph.call_count==2
    assert all('/media_publish' not in call.args[1] for call in graph.call_args_list)


def test_cutoff_after_video_account_check_does_not_submit(monkeypatch):
    c=Mock()
    c.execute.return_value.fetchone.return_value={'id':5}
    monkeypatch.setattr(en,'db',lambda:contextlib.nullcontext(c))
    monkeypatch.setattr(en,'utcnow',lambda:MORNING)
    provider=Mock(side_effect=AssertionError('provider must not be called'))
    save=Mock()
    guard=Mock(side_effect=[None,en.PublicationWindowClosed()])
    sp=types.SimpleNamespace(connection=lambda:('fixture',{}),save_result=save)
    sz=types.SimpleNamespace(creator_info=lambda *a:{},verified_accounts=lambda *a:{'youtube':{'accountId':'YT'},'tiktok':{'accountId':'TT'}},provider_request=provider,publication_result=Mock())
    with patch.dict(sys.modules,{'app.social_publishing':sp,'app.social_zernio':sz}):
        with pytest.raises(en.PublicationWindowClosed):
            en.publish_video(DAY,en.TOPICS[0],'text',en.media_urls(DAY)[1],1,guard=guard)
    provider.assert_not_called()
    assert save.call_args.args[2]=='cancelled'


def test_cancellation_and_draft_failure_cannot_report_full_success():
    results={'facebook':{'status':'published'},'instagram':{'status':'published'},'youtube_tiktok':{'status':'cancelled','tiktok':True}}
    assert en.final_status(results)=='partial'
    results['youtube_tiktok']['status']='published'
    results['drafts']={'status':'failed'}
    assert en.final_status(results)=='partial'


def test_sync_rejects_wrong_post_identity(monkeypatch):
    c=Mock()
    c.execute.return_value.fetchall.return_value=[{'day':DAY,'results_json':'{}','content_id':10,'provider_post_id':'EXPECTED','payload_json':'{"platforms":[]}','status':'publishing'}]
    monkeypatch.setattr(en,'db',lambda:contextlib.nullcontext(c))
    save=Mock()
    sp=types.SimpleNamespace(connection=lambda:('fixture',{}),save_result=save)
    sz=types.SimpleNamespace(identifier=lambda x:x,provider_request=Mock(return_value={}),publication_result=lambda *a:('WRONG','published',[]))
    with patch.dict(sys.modules,{'app.social_publishing':sp,'app.social_zernio':sz}):
        en.sync_pending()
    save.assert_not_called()
    assert c.execute.call_count==1
    assert "'cancelled'" in c.execute.call_args.args[0]


def test_live_guard_rechecks_time_and_activation(monkeypatch):
    monkeypatch.setattr(en,'enabled',Mock(side_effect=[True,True,False]))
    monkeypatch.setattr(en,'due',Mock(side_effect=[DAY,None]))
    en.publishing_guard(DAY)
    with pytest.raises(en.PublicationWindowClosed):
        en.publishing_guard(DAY)
    with pytest.raises(en.PublicationWindowClosed):
        en.publishing_guard(DAY)
