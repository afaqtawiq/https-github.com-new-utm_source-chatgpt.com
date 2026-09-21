from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json

def run(client,app):
    from app import publication_reports as reports
    from app.storage import db,one,get_session,utcnow
    uid=get_session(client.cookies.get('gla_session'))['user_id']
    with db() as c:
        c.execute("UPDATE social_publications SET status='failed',updated_at=%s",(utcnow()-dt.timedelta(days=3),))
        p=c.execute('SELECT content_id FROM social_publications LIMIT 1').fetchone()
        assert p
        cid=p['content_id']
        results=[{'platform':'youtube','status':'published','url':'https://www.youtube.com/watch?v=test123'}]
        c.execute("UPDATE social_publications SET approved_by=%s,status='partial',results_json=%s,updated_at=%s WHERE content_id=%s",(uid,json.dumps(results),utcnow(),cid))
        c.execute("UPDATE social_content SET status='published' WHERE id=%s",(cid,))
    calls=[]
    def send(*args):
        calls.append(args);return '<report@example.invalid>'
    with patch('app.production_monitor.sender_ready',lambda *a:True),patch.object(reports.spacemail,'send',send),patch('app.social_publishing.connection',lambda:('fake',[])),patch('app.social_publishing.provider_request',return_value={}) as get,patch('app.social_publishing.publication_result',return_value=('abcdefabcdefabcdefabcdef','published',results)):
        reports.tick();assert calls==[]
        with db() as c:
            c.execute("UPDATE social_publications SET status='scheduled',provider_post_id='abcdefabcdefabcdefabcdef',scheduled_at=%s,payload_json=%s WHERE content_id=%s",(utcnow()-dt.timedelta(minutes=1),json.dumps({'platforms':[]}),cid))
        # TikTok can confirm publication before its public URL is available.
        incomplete=[dict(results[0],url='')]
        with patch('app.social_publishing.publication_result',return_value=('abcdefabcdefabcdefabcdef','published',incomplete)):
            reports.tick()
        assert get.call_count==1 and calls==[]
        assert one('SELECT status FROM social_publications WHERE content_id=?',(cid,))['status']=='published'
        reports.tick()
        assert get.call_count==2 and get.call_args.args[1]=='GET'
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _:reports.tick(),range(4)))
    assert len(calls)==1 and calls[0][1]==reports.spacemail.ADDRESS
    assert 'https://www.youtube.com/watch?v=test123' in calls[0][3]
    assert one('SELECT status FROM publication_mail_reports WHERE content_id=?',(cid,))['status']=='accepted'
    print('PASS: only confirmed full publications report; concurrent workers send once to official mailbox.')
