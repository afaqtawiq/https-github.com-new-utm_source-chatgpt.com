from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json

def run(client,app):
    from app import publication_reports as reports
    from app.storage import db,one,get_session,utcnow
    uid=get_session(client.cookies.get('gla_session'))['user_id']
    with db() as c:
        c.execute('UPDATE social_publications SET updated_at=%s',(utcnow()-dt.timedelta(days=3),))
        p=c.execute('SELECT content_id FROM social_publications LIMIT 1').fetchone()
        assert p
        cid=p['content_id']
        results=[{'platform':'youtube','status':'published','url':'https://www.youtube.com/watch?v=test123'}]
        c.execute("UPDATE social_publications SET approved_by=%s,status='partial',results_json=%s,updated_at=%s WHERE content_id=%s",(uid,json.dumps(results),utcnow(),cid))
        c.execute("UPDATE social_content SET status='published' WHERE id=%s",(cid,))
    calls=[]
    def send(*args):
        calls.append(args);return '<report@example.invalid>'
    with patch('app.production_monitor.sender_ready',lambda *a:True),patch.object(reports.spacemail,'send',send):
        reports.tick();assert calls==[]
        with db() as c:
            c.execute("UPDATE social_publications SET status='published' WHERE content_id=%s",(cid,))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _:reports.tick(),range(4)))
    assert len(calls)==1 and calls[0][1]==reports.spacemail.ADDRESS
    assert 'https://www.youtube.com/watch?v=test123' in calls[0][3]
    assert one('SELECT status FROM publication_mail_reports WHERE content_id=?',(cid,))['status']=='accepted'
    print('PASS: only confirmed full publications report; concurrent workers send once to official mailbox.')
