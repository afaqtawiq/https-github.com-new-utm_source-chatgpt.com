import datetime as dt
from email.message import EmailMessage
from email.utils import formatdate
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

def run(client,app):
    from app import official_replies as r
    from app.storage import db,one,utcnow,get_session
    msg=EmailMessage()
    msg['From']='customer@example.com';msg['To']=r.spacemail.ADDRESS
    msg['Date']=formatdate(usegmt=True);msg['Message-ID']='<new-customer@example.com>'
    msg['Subject']='طلب شحن';msg.set_content('أريد شحن بضاعة من جدة إلى الرياض')
    assert r.eligible_message(msg)=='customer@example.com'
    msg.replace_header('Date',formatdate())
    assert r.eligible_message(msg)=='customer@example.com'
    msg['Auto-Submitted']='auto-replied'
    assert r.eligible_message(msg) is None
    del msg['Auto-Submitted'];msg['List-Id']='mailing-list'
    assert r.eligible_message(msg) is None
    del msg['List-Id'];msg['Reply-To']='other@example.com'
    assert r.eligible_message(msg) is None
    del msg['Reply-To'];msg.replace_header('Date','Mon, 01 Jan 2024 00:00:00 +0000')
    assert r.eligible_message(msg) is None
    s=get_session(client.cookies.get('gla_session'));uid=s['user_id']
    with db() as c:
        c.execute('INSERT INTO official_reply_settings(user_id,enabled,enabled_at) VALUES(%s,TRUE,%s) ON CONFLICT(user_id) DO UPDATE SET enabled=TRUE,enabled_at=excluded.enabled_at',(uid,utcnow()-dt.timedelta(minutes=1)))
        row=c.execute('''INSERT INTO spacemail_inbox(user_id,uidvalidity,uid,message_id,sender,subject,body,received,imported_at,reply_address)
            VALUES(%s,'ops-test',999,'<new-customer@example.com>','customer@example.com','طلب شحن','test','today',%s,'customer@example.com') RETURNING id''',(uid,utcnow())).fetchone()
    calls=[]
    def send(*args,**kwargs):
        calls.append((args,kwargs));return '<reply@example.invalid>'
    with patch.dict('os.environ',{'ENABLE_EXTERNAL_ACTIONS':'1'}),patch('app.production_monitor.sender_ready',lambda *a:True),patch.object(r.spacemail,'send',send):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _:r.deliver(row['id']),range(4)))
        r.deliver(row['id'])
    assert len(calls)==1
    assert calls[0][0][1]=='customer@example.com'
    assert calls[0][0][3]==r.BODY
    assert calls[0][1]['automatic'] is True
    assert one('SELECT status FROM official_reply_log WHERE inbox_id=?',(row['id'],))['status']=='sent'
    assert client.post('/official-replies',data={'csrf':'bad','enabled':'yes'}).status_code in (403,428)
    print('PASS: reply eligibility, loop prevention, stale mail exclusion and concurrent one-send claim.')
