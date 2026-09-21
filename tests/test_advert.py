import io
from decimal import Decimal
from pathlib import Path
import shutil
import subprocess

import pytest
from PIL import Image

from app import advert_provider as p, advert_render as r, media_fal as f
from app.advert_spec import default_plan, step_specs, plan_from_form


def test_plan_native_formats_and_reuse():
    plan = default_plan()
    assert len(step_specs(plan)) == 21
    plan['reuse_job_id'] = 2
    steps = step_specs(plan)
    assert len(steps) == 19
    assert 'video-9:16-0' not in {s['key'] for s in steps}
    assert 'video-16:9-0' in {s['key'] for s in steps}
    with pytest.raises(f.MediaError):
        plan_from_form({'format': 'bad'})


@pytest.mark.parametrize('unit,price', [('characters','.0001'), ('1000 characters','.1'), ('1m characters','100')])
def test_voice_cost_conservative(monkeypatch, unit, price):
    monkeypatch.setattr(f, 'call', lambda *a, **kw: {'prices':[{'endpoint_id':f.VOICE_MODEL,'currency':'USD','unit':unit,'unit_price':price}]})
    rate = p.voice_rate('test-key')
    assert p.step_cost({'stage':'voice','prompt':'آفاق طويق'}, {'voice':rate}) == Decimal('.1')


@pytest.mark.parametrize('unit,price', [('minute','.1'), ('characters','NaN'), ('characters','-1')])
def test_voice_price_fail_closed(monkeypatch, unit, price):
    monkeypatch.setattr(f, 'call', lambda *a, **kw: {'prices':[{'endpoint_id':f.VOICE_MODEL,'currency':'USD','unit':unit,'unit_price':price}]})
    with pytest.raises(f.MediaError):
        p.voice_rate('test-key')


def test_voice_submission_exact_model_and_controls(monkeypatch):
    calls = []
    def call(key, method, url, **kwargs):
        calls.append((method,url,kwargs))
        root = 'https://queue.fal.run/fal-ai/minimax/requests/request-123456'
        return {'request_id':'request-123456','status_url':root+'/status','response_url':root}
    monkeypatch.setattr(f, 'call', call)
    receipt = p.submit('test-key', {'stage':'voice','prompt':'آفاق طويق'})
    assert receipt['request_id'] == 'request-123456' and len(calls) == 1
    payload = calls[0][2]['payload']
    assert payload['language_boost'] == 'Arabic'
    assert payload['voice_setting']['voice_id'] == 'Arabic_FriendlyGuy'
    assert payload['voice_setting']['pitch'] == -2
    assert payload['output_format'] == 'url'


def test_download_rejects_external_host_before_network(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError('network must not be called')
    monkeypatch.setattr(r.httpx, 'Client', forbidden)
    for url in ['https://example.com/file.mp4','http://v3b.fal.media/a.mp4','https://127.0.0.1/a.mp4']:
        with pytest.raises(f.MediaError):
            r.download(url, 'video', tmp_path/'file')


def test_logo_validation_and_both_arabic_cards():
    bad = b'<svg><script>alert(1)</script></svg>'
    with pytest.raises(f.MediaError):
        r.normalized_logo(bad)
    source = io.BytesIO()
    Image.new('RGB',(32,20),'white').save(source,'JPEG')
    logo = r.normalized_logo(source.getvalue())
    for ratio, dimensions in r.SIZES.items():
        card = r.card(ratio, default_plan()['scenes'][-1], end=True, logo=logo)
        assert Image.open(io.BytesIO(card)).size == dimensions


@pytest.mark.parametrize('long_voice', [False, True])
def test_real_montage_two_formats_has_voice_video_and_bounded_duration(tmp_path, long_voice):
    """Real FFmpeg integration using local synthetic fixtures, no generation or spending."""
    plan = default_plan()
    voice = tmp_path/'voice.mp3'
    subprocess.run(['ffmpeg','-loglevel','error','-y','-f','lavfi','-i','sine=frequency=220:duration=2',str(voice)],check=True)
    longer = tmp_path/'longer.mp3'
    subprocess.run(['ffmpeg','-loglevel','error','-y','-f','lavfi','-i','sine=frequency=220:duration=7.1',str(longer)],check=True)
    paths = {}
    for ratio, (w,h) in r.SIZES.items():
        clip = tmp_path/('vertical.mp4' if ratio == '9:16' else 'horizontal.mp4')
        subprocess.run(['ffmpeg','-loglevel','error','-y','-f','lavfi','-i',f'color=c=0x284858:s={w}x{h}:r=25:d=5',
                        '-c:v','libx264','-preset','ultrafast','-threads','2',str(clip)],check=True)
        paths[ratio] = clip
    outputs = {f'voice-{i}':'https://v3.fal.media/test.mp3' for i in range(5)}
    if long_voice:
        outputs['voice-1'] = 'https://v3.fal.media/longer.mp3'
    outputs.update({f'video-{ratio}-{i}':ratio for ratio in plan['ratios'] for i in range(4)})
    def fetch(url, stage, path):
        shutil.copyfile((longer if url.endswith('longer.mp3') else voice) if stage == 'voice' else paths[url],path)
    rendered = r.render(plan,outputs,fetch=fetch)
    for ratio, item in rendered.items():
        final = tmp_path/('final-'+ratio.replace(':','-')+'.mp4')
        final.write_bytes(item['data'])
        meta = r.probe(final)
        assert (27.2 <= item['duration'] <= 27.6) if long_voice else (24.8 <= item['duration'] <= 25.2)
        assert any(s['codec_type']=='audio' and s['codec_name']=='aac' for s in meta['streams'])
        assert len(item['data']) < r.MAX_EXPORT
        assert (item['width'],item['height']) == r.SIZES[ratio]
