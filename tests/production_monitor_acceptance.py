"""Real DB claims and approval tests; all outgoing email is stubbed."""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch


def run(client, app):
    from app import production_monitor as m
    from app.storage import db, one, rows, utcnow, get_session
    session = get_session(client.cookies.get('gla_session'))
    uid, csrf = session['user_id'], session['csrf']
    sender = 'monitor@example.invalid'
    conn = {'sender_email':sender, 'status':'connected'}
    calls = []
    def send(*args):
        calls.append(args)
        return 'ci-email-' + str(len(calls))
    data = {'csrf':csrf, 'recipient':sender, 'minutes':'15', 'enabled':'yes'}
    with patch.object(m.mail, 'connection', lambda _: conn), patch.object(m.mail, 'send_gmail', send):
        with db() as c:
            c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (utcnow()+dt.timedelta(minutes=10),session['id']))
        assert client.get('/production-monitor').status_code == 200
        with patch.object(m.mail, 'access_token', return_value='never-render-this-token') as refresh:
            assert client.post('/production-monitor/check-email', data={'csrf':'bad'}).status_code == 403
            refresh.assert_not_called()
            response = client.post('/production-monitor/check-email', data={'csrf':csrf})
            assert response.status_code == 200 and 'نجح تجديد' in response.text
            assert 'never-render-this-token' not in response.text and not calls
        with patch.object(m.mail, 'access_token', side_effect=RuntimeError('Google OAuth 400: invalid_grant')):
            assert 'invalid_grant' in client.post('/production-monitor/check-email', data={'csrf':csrf}).text
        with patch.object(m.mail, 'access_token', side_effect=RuntimeError('private-diagnostic-value')):
            assert 'private-diagnostic-value' not in client.post('/production-monitor/check-email', data={'csrf':csrf}).text
        assert client.post('/production-monitor/settings', data={**data,'csrf':'bad'}).status_code == 403
        assert client.post('/production-monitor/settings', data={**data,'minutes':'0'}).status_code == 400
        with db() as c:
            c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (utcnow()-dt.timedelta(seconds=1),session['id']))
        assert client.post('/production-monitor/settings', data=data).status_code == 428
        with db() as c:
            c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (utcnow()+dt.timedelta(minutes=10),session['id']))
        assert client.post('/production-monitor/settings', data=data).status_code == 200
        settings = one('SELECT * FROM production_monitor_settings WHERE user_id=?',(uid,))
        job = one("SELECT id FROM advert_jobs WHERE status='needs_review' ORDER BY id LIMIT 1")
        jid = job['id']
        # Existing errors are opt-in; a manual check records them without a paid request.
        assert client.post('/production-monitor/check',data={'csrf':csrf,'kind':'advert','job_id':str(jid)}).status_code == 200
        item = one("SELECT * FROM production_incidents WHERE kind='advert' AND job_id=?",(jid,))
        assert item and item['alert_status']=='ready' and item['support_status']=='draft' and not calls
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _:m.deliver(item['id']),range(4)))
        assert len(calls)==1 and calls[0][1]==sender
        m.tick(); m.tick()
        assert len(calls)==1
        assert one('SELECT alert_status,support_status FROM production_incidents WHERE id=?',(item['id'],))=={'alert_status':'sent','support_status':'draft'}
        assert client.post(f"/production-monitor/{item['id']}/send-support", data={'csrf':csrf}).status_code==409
        with db() as c:
            c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (utcnow()-dt.timedelta(seconds=1),session['id']))
        assert client.post(f"/production-monitor/{item['id']}/send-support",data={'csrf':csrf,'approve':'yes'}).status_code==428
        with db() as c:
            c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (utcnow()+dt.timedelta(minutes=10),session['id']))
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda _:client.post(f"/production-monitor/{item['id']}/send-support",data={'csrf':csrf,'approve':'yes'}).status_code,range(3)))
        assert results==[200]*3 and len(calls)==2 and calls[-1][1]==m.SUPPORT
        assert 'api_key' not in calls[-1][3] and 'refresh_token' not in calls[-1][3]
        now = utcnow()
        assert m.classify({'status':'running','changed':now-dt.timedelta(minutes=16)},15,now)=='stalled'
        assert m.classify({'status':'running','changed':now-dt.timedelta(minutes=1)},15,now) is None
        assert m.classify({'status':'draft','changed':now-dt.timedelta(days=1)},15,now) is None
        # Updated job timestamp alone is not used: a completed advert step resets stagnation.
        with db() as c:
            c.execute("UPDATE advert_jobs SET status='running',updated_at=%s WHERE id=%s",(now-dt.timedelta(minutes=20),jid))
            c.execute('UPDATE advert_steps SET updated_at=%s WHERE job_id=%s',(now-dt.timedelta(minutes=20),jid))
        m.scan(); m.scan()
        stalled = one("SELECT * FROM production_incidents WHERE job_id=? AND kind='advert' AND event='stalled'",(jid,))
        assert stalled and len(rows("SELECT id FROM production_incidents WHERE job_id=? AND event='stalled'",(jid,)))==1
        with patch.dict('os.environ', {'ENABLE_EXTERNAL_ACTIONS':'0'}):
            m.deliver(stalled['id'])
        assert len(calls)==2
        # Turning off monitoring suppresses pending mail.
        assert client.post('/production-monitor/settings',data={**data,'enabled':'no'}).status_code==200
        m.deliver(stalled['id']); assert len(calls)==2
        assert client.post('/production-monitor/settings',data=data).status_code==200
        with patch.object(m.mail,'connection',lambda _: {**conn,'sender_email':'changed@example.invalid'}):
            m.deliver(stalled['id'])
        assert len(calls)==2
        with patch.object(m.mail,'send_gmail',side_effect=TimeoutError):
            m.deliver(stalled['id'])
        assert one('SELECT alert_status FROM production_incidents WHERE id=?',(stalled['id'],))['alert_status']=='uncertain'
        m.deliver(stalled['id']); assert len(calls)==2
        with db() as c:
            c.execute('UPDATE advert_steps SET updated_at=%s WHERE job_id=%s AND ordinal=0',(utcnow(),jid))
        assert m.classify(m.snapshot('advert',jid),15,utcnow()) is None
        m.scan()
        assert one('SELECT resolved_at FROM production_incidents WHERE id=?',(stalled['id'],))['resolved_at']
        with db() as c:
            c.execute("UPDATE advert_jobs SET status='complete',updated_at=%s WHERE id=%s",(utcnow(),jid))
        m.scan()
        assert one('SELECT resolved_at FROM production_incidents WHERE id=?',(item['id'],))['resolved_at']
        # Interrupted delivery never gets a blind automatic retry.
        with db() as c:
            c.execute("UPDATE production_incidents SET alert_status='sending',alert_updated_at=%s WHERE id=%s",(utcnow()-dt.timedelta(minutes=4),item['id']))
        m.tick()
        assert one('SELECT alert_status FROM production_incidents WHERE id=?',(item['id'],))['alert_status']=='uncertain'
    print('PASS: production alerts, MFA/CSRF, support approval, concurrent single send, delay threshold, progress reset, opt-out, sender pinning, disabled gate, ambiguous email no retry. Live emails: 0.')
