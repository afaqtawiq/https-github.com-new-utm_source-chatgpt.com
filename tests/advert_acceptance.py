"""PostgreSQL concurrency, financial gates, recovery and durable media serving."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
from decimal import Decimal
import io
import json
from unittest.mock import patch

from PIL import Image


def run(client, app):
    from app import advert_studio as s, advert_provider as p, advert_render as r
    from app.advert_spec import default_plan
    from app.media_fal import MediaError
    from app.storage import db, one, rows, get_session, utcnow
    session = get_session(client.cookies.get('gla_session'))
    csrf = session['csrf']
    plan = default_plan()
    data = {'csrf':csrf,'format':'both','title':plan['title'],'caption':plan['caption']}
    for i, scene in enumerate(plan['scenes']):
        for key in ('voice','text','image','motion'):
            data[f'{key}_{i}'] = scene[key]
    pricing = {'image':Decimal('.03'),'video':Decimal('.35'),'voice':Decimal('.0001')}
    calls = []
    mode = {'ambiguous':False, 'waiting':False, 'render_error':False}
    def submit(key, spec, **kwargs):
        calls.append(spec['key'])
        if mode['ambiguous']:
            raise MediaError('Uncertain provider response')
        if spec['stage']=='video':
            assert kwargs['image_url'].endswith('.png')
        return {'request_id':spec['key'],'status_url':'fixture','response_url':'fixture'}
    def result(key, stage, receipt):
        if mode['waiting']:
            return None
        return 'https://v3.fal.media/acceptance.'+{'image':'png','voice':'mp3','video':'mp4'}[stage]
    def render(plan, outputs, **kwargs):
        if mode['render_error']:
            raise MediaError('Simulated recoverable renderer failure')
        assert len([k for k in outputs if k.startswith('voice-')])==5
        return {ratio:{'data':b'ci-video-fixture-0123456789','duration':25,'width':r.SIZES[ratio][0],
                       'height':r.SIZES[ratio][1]} for ratio in plan['ratios']}
    def prepare(**extra):
        response=client.post('/advert-studio/prepare',data={**data,**extra},follow_redirects=False)
        assert response.status_code==303,response.text
        return int(response.headers['location'].rsplit('/',1)[1])
    def stamp(jid):
        return one('SELECT quote_expires_at FROM advert_jobs WHERE id=?',(jid,))['quote_expires_at'].isoformat()
    def approve(jid, **extra):
        return client.post(f'/advert-studio/{jid}/run',data={'csrf':csrf,'approve_cost':'yes','quote_stamp':stamp(jid),**extra},follow_redirects=False)
    def drain(jid):
        for _ in range(55):
            s.process(jid)
            state=one('SELECT status FROM advert_jobs WHERE id=?',(jid,))['status']
            if state!='running':
                return state
        raise AssertionError('Job did not reach terminal state')
    with patch.object(p,'rates',lambda key:dict(pricing)),patch.object(p,'submit',submit),patch.object(p,'result',result),patch.object(r,'render',render):
        assert client.get('/advert-studio').status_code==200
        jid=prepare()
        assert len(rows('SELECT id FROM advert_steps WHERE job_id=?',(jid,)))==21 and calls==[]
        assert '3.5400' in client.get(f'/advert-studio/{jid}').text
        assert client.get(f'/advert-studio/{jid}/preview/vertical.png').headers['content-type']=='image/png'
        assert client.get(f'/advert-studio/{jid}/preview/unknown.png').status_code==404
        assert approve(jid,csrf='bad').status_code==403
        assert approve(jid,approve_cost='no').status_code==409
        with db() as c:
            c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s',(utcnow()-dt.timedelta(minutes=1),session['id']))
        assert approve(jid).status_code==428
        with db() as c:
            c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s',(utcnow()+dt.timedelta(minutes=10),session['id']))
        with patch.dict('os.environ',{'ENABLE_EXTERNAL_ACTIONS':'0'}):
            assert approve(jid).status_code==409 and calls==[]
        old_stamp=stamp(jid)
        assert client.post(f'/advert-studio/{jid}/requote',data={'csrf':csrf}).status_code==200
        assert approve(jid,quote_stamp=old_stamp).status_code==409
        pricing['voice']=Decimal('.0002')
        assert approve(jid).status_code==409 and calls==[]
        pricing['voice']=Decimal('.0001')
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses=list(pool.map(lambda _:approve(jid).status_code,range(4)))
        assert statuses.count(303)==1,statuses
        assert calls==[]  # Approval queues work; the route never submits paid calls itself.
        assert client.post(f'/advert-studio/{jid}/sync',data={'csrf':csrf}).status_code==200 and calls==[]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _:s.process(jid),range(4)))
        assert calls==['voice-0']
        mode['waiting']=True
        s.process(jid)
        assert one('SELECT status FROM advert_steps WHERE job_id=? ORDER BY ordinal LIMIT 1',(jid,))['status']=='pending'
        mode['waiting']=False
        assert drain(jid)=='complete'
        assert len(calls)==21 and len(set(calls))==21
        exports=rows('SELECT * FROM advert_exports WHERE job_id=?',(jid,))
        assert len(exports)==2
        assert one('SELECT reserved_bytes FROM advert_jobs WHERE id=?',(jid,))['reserved_bytes']==0
        for export in exports:
            item=one('SELECT * FROM social_content WHERE id=?',(export['content_id'],))
            assert item['status']=='draft' and item['approval_id'] is None
            assert not one('SELECT id FROM social_publications WHERE content_id=?',(item['id'],))
            from fastapi.testclient import TestClient
            public=TestClient(app,base_url='http://testserver')
            path='/media-exports/'+export['token']+'.mp4'
            assert public.get(path).content==bytes(export['payload'])
            partial=public.get(path,headers={'Range':'bytes=2-7'})
            assert partial.status_code==206 and partial.content==bytes(export['payload'])[2:8]
            assert public.head(path).headers['content-length']==str(len(export['payload']))
            assert public.get(path,headers={'Range':'bytes=99999-'}).status_code==416
        assert approve(jid).status_code==409
        assert client.get('/media-exports/'+'f'*48+'.mp4').status_code==404

        uncertain=prepare(format='9:16')
        assert approve(uncertain).status_code==303
        mode['ambiguous']=True
        before=len(calls)
        s.process(uncertain)
        assert one('SELECT status FROM advert_jobs WHERE id=?',(uncertain,))['status']=='needs_review'
        s.process(uncertain)
        assert len(calls)==before+1
        assert client.post(f'/advert-studio/{uncertain}/retry-render',data={'csrf':csrf}).status_code==409
        mode['ambiguous']=False

        interrupted=prepare(format='9:16')
        assert approve(interrupted).status_code==303
        with db() as c:
            c.execute("UPDATE advert_steps SET status='submitting',updated_at=%s WHERE job_id=%s AND ordinal=0",(utcnow()-dt.timedelta(minutes=5),interrupted))
        before=len(calls)
        s.process(interrupted)
        assert len(calls)==before and one('SELECT status FROM advert_jobs WHERE id=?',(interrupted,))['status']=='needs_review'

        recoverable=prepare(format='9:16')
        assert approve(recoverable).status_code==303
        mode['render_error']=True
        assert drain(recoverable)=='needs_review'
        before=len(calls)
        mode['render_error']=False
        assert client.post(f'/advert-studio/{recoverable}/retry-render',data={'csrf':csrf}).status_code==200
        s.process(recoverable)
        assert one('SELECT status FROM advert_jobs WHERE id=?',(recoverable,))['status']=='complete' and len(calls)==before

        capped=prepare(format='9:16')
        with patch.object(s,'EXPORT_QUOTA',1):
            assert approve(capped).status_code==409
        assert one('SELECT status FROM advert_jobs WHERE id=?',(capped,))['status']=='draft'
        with db() as c:
            c.execute('UPDATE advert_jobs SET quote_expires_at=%s WHERE id=%s',(utcnow()-dt.timedelta(seconds=1),capped))
        assert approve(capped).status_code==409
        assert client.post(f'/advert-studio/{capped}/requote',data={'csrf':csrf}).status_code==200
        assert approve(capped).status_code==303
        pricing['voice']=Decimal('.0002')
        before=len(calls)
        s.process(capped)
        assert len(calls)==before and one('SELECT status FROM advert_jobs WHERE id=?',(capped,))['status']=='needs_review'
        pricing['voice']=Decimal('.0001')

        image=io.BytesIO()
        Image.new('RGB',(30,20),'white').save(image,'PNG')
        assert client.post('/advert-studio/brand',data={'csrf':csrf},files={'logo':('logo.png',image.getvalue(),'image/png')}).status_code==200
        with_logo=prepare(format='9:16')
        assert one('SELECT logo FROM advert_jobs WHERE id=?',(with_logo,))['logo']
        assert not one('SELECT logo FROM advert_jobs WHERE id=?',(jid,))['logo']
        assert client.get('/advert-studio/brand/logo.png').status_code==200
    print('PASS: cinematic quote, MFA/CSRF, stale quote, costs, concurrency, no duplicate paid work, two exports, range/HEAD, logo snapshots, safe render recovery. Live spend: 0.')
