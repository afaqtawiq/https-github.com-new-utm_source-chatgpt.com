"""Recovery must not duplicate accepted/unknown requests or bypass owner/MFA gates."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi import HTTPException

def run(client, app):
    from app import agent_operations as ops
    from app.storage import db, one, get_session, utcnow
    s = get_session(client.cookies.get('gla_session'))
    uid = s['user_id']
    with db() as c:
        j = c.execute('''INSERT INTO advert_jobs(status,plan_json,total_cost,credential_version,quote_expires_at,
            approved_by,approved_at,created_by,created_at,updated_at,last_error)
            SELECT 'needs_review',plan_json,total_cost,credential_version,quote_expires_at,%s,%s,%s,%s,%s,%s
            FROM advert_jobs LIMIT 1 RETURNING id,total_cost''',
            (uid,utcnow(),uid,utcnow(),utcnow(),'الرصيد غير كافٍ أو الدفع غير مهيأ لدى fal.ai. test')).fetchone()
        jid=j['id']
        c.execute("""INSERT INTO advert_steps(job_id,ordinal,step_key,spec_json,status,cost_limit,updated_at)
            VALUES(%s,0,'voice-0','{"stage":"voice"}','submitting',.1,%s)""",(jid,utcnow()))
    def attempt(owner=uid):
        try:
            ops.recover(jid,owner)
            return 200
        except HTTPException as exc:
            return exc.status_code
    with patch('app.agent_operations.advert.enabled'):
        assert attempt(uid+999)==409
        with db() as c:
            c.execute("UPDATE advert_steps SET receipt='accepted-receipt' WHERE job_id=%s",(jid,))
        assert attempt()==409
        with db() as c:
            c.execute('UPDATE advert_steps SET receipt=NULL WHERE job_id=%s',(jid,))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:attempt(),range(4)))
        assert results.count(200)==1,results
        assert one('SELECT total_cost FROM advert_jobs WHERE id=?',(jid,))['total_cost']==j['total_cost']
        assert one('SELECT status FROM advert_steps WHERE job_id=?',(jid,))['status']=='ready'
        with db() as c:
            c.execute("UPDATE advert_jobs SET status='needs_review' WHERE id=%s",(jid,))
            c.execute("UPDATE advert_steps SET status='submitting' WHERE job_id=%s",(jid,))
        assert attempt()==409
    assert client.post('/agent-operations/test-alert',data={'csrf':'bad'}).status_code in (403,428)
    calls=[]
    with db() as c:
        c.execute("UPDATE production_monitor_settings SET enabled=TRUE,sender=%s,recipient=%s WHERE user_id=%s",(ops.spacemail.ADDRESS,ops.spacemail.ADDRESS,uid))
    def send(*args):
        calls.append(args)
        return '<ops-test@example.invalid>'
    with patch.object(ops.spacemail,'connection',lambda _: {'status':'connected'}),patch.object(ops.spacemail,'send',send):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _:ops.alert_check(uid),range(4)))
    assert len(calls)==1
    assert calls[0][1]==ops.spacemail.ADDRESS
    assert 'اختبار' in calls[0][2]
    assert one("SELECT status FROM agent_checks WHERE user_id=? AND kind='alert'",(uid,))['status']=='accepted'
    print('PASS: recovery preserves budget, rejects accepted receipts/wrong owners, one concurrent recovery, one operational alert.')
