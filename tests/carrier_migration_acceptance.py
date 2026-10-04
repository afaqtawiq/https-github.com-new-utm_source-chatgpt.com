"""Synthetic pre-migration preservation and concurrent import regressions."""
from pathlib import Path
import re
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import carrier_directory_acceptance as acceptance


def run():
    from app import main, data_import, command_assistant
    from app.storage import db,rows,one,utcnow,create_session
    now=utcnow()
    with db() as c:
        for i in range(83):
            c.execute('INSERT INTO drivers(driver_name,whatsapp_phone,vehicle_type,company_name,offer_consent,consent_date,notes,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(f'Synthetic Legacy {i:02}',f'+966500{i:06}' if i%3 else f'malformed raw {i}','raw vehicle','free text company',i%2,'2024-01-01',f'untouched note {i}',now,now))
        bid=c.execute("INSERT INTO driver_broadcasts(raw_command,message,status,recipient_count,sent_count,created_at,updated_at) VALUES('synthetic historic','synthetic historic','sent',83,83,%s,%s) RETURNING id",(now,now)).fetchone()['id']
        for r in c.execute('SELECT * FROM drivers ORDER BY id').fetchall():
            c.execute("INSERT INTO driver_broadcast_recipients(broadcast_id,driver_id,driver_name,phone,status,provider_message_id,sent_at) VALUES(%s,%s,%s,%s,'sent',%s,%s)",(bid,r['id'],r['driver_name'],r['whatsapp_phone'],'synthetic-'+str(r['id']),now))
    before=rows('SELECT * FROM drivers ORDER BY id');hist=rows('SELECT * FROM driver_broadcast_recipients ORDER BY id')
    assert 'record_type' not in before[0]
    from app.bootstrap import app
    from app import carrier_directory as d
    d.init_storage();d.init_storage()
    after=rows('SELECT * FROM drivers ORDER BY id');posthist=rows('SELECT * FROM driver_broadcast_recipients ORDER BY id')
    assert len(after)==83
    for a,b in zip(before,after):
        assert all(b[k]==v for k,v in a.items()),(a['id'],'legacy changed')
        assert b['record_type']=='unreviewed' and b['carrier_company_id'] is None
    for a,b in zip(hist,posthist):assert all(b[k]==v for k,v in a.items()),'history changed'
    print('PASS: actual pre-migration 83 synthetic driver rows, mixed flags, malformed raw fields, IDs, consent dates and 83 history rows unchanged after bootstrap + repeated migration')
    with db() as c:
        uid=c.execute("INSERT INTO users(email,name,password_hash,role,created_at) VALUES('reviewer@fixture.invalid','reviewer','not-a-password','admin',%s) RETURNING id",(now,)).fetchone()['id']
    sid,csrf,_=create_session(uid)
    from fastapi.testclient import TestClient
    def request(method,path,**kwargs):
        with_cookie=TestClient(app,base_url='http://testserver',follow_redirects=False)
        with_cookie.cookies.set('gla_session',sid)
        try:return with_cookie.request(method,path,headers={'Origin':'http://testserver'},**kwargs)
        finally:with_cookie.close()
    def preview(name,phone):
        r=request('POST','/carriers/import/preview',data={'csrf':csrf},files={'file':('x.csv',f'company_name,country,phone\n{name},SA,{phone}\n','text/csv')})
        assert r.status_code==200,r.text
        return re.search(r'/carriers/import/([^/]+)/commit',r.text)[1]
    same=preview('Concurrent Same','0500000991')
    def commit(batch):
        r=request('POST',f'/carriers/import/{batch}/commit',data={'csrf':csrf});assert r.status_code==200,r.text
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(commit,[same]*4))
    assert one("SELECT COUNT(*) n FROM carrier_companies WHERE company_name='Concurrent Same'")['n']==1
    assert one("SELECT COUNT(*) n FROM activity WHERE action='carrier_import'")['n']==1
    a=preview('Race A','0500000992');b=preview('Race B','0500000992')
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(commit,[a,b]))
    assert one("SELECT COUNT(*) n FROM carrier_companies WHERE phone='+966500000992'")['n']==1
    assert sorted(rows('SELECT inserted_count FROM carrier_import_batches WHERE id IN (%s,%s)',(a,b)),key=lambda x:x['inserted_count'])==[{'inserted_count':0},{'inserted_count':1}]
    print('PASS: simultaneous first commit (4 callers) inserts once; racing distinct preview batches sharing a phone insert one and safely skip the other')
    payload='</title><script>alert(1)</script>'
    r=request('POST','/carriers/new',data={'csrf':csrf,'company_name':payload,'country':'SA','notes':'</textarea><img src=x onerror=alert(1)>','website':'http://127.0.0.1:9/private'})
    assert r.status_code==303,r.text
    body=request('GET',r.headers['location']).text
    assert payload not in body and '&lt;script&gt;alert(1)&lt;/script&gt;' in body
    assert '<img src=x onerror=alert(1)>' not in body
    assert request('POST','/carriers/new',data={'csrf':'wrong','company_name':'CSRF','country':'SA'}).status_code==403
    assert one('SELECT COUNT(*) n FROM drivers')['n']==83
    assert one('SELECT COUNT(*) n FROM driver_broadcast_recipients')['n']==83
    assert one('SELECT COUNT(*) n FROM driver_broadcasts')['n']==1
    print('PASS: stored HTML escaped in detail/title/input/textarea; wrong CSRF rejected; carrier actions leave all 83 drivers and history untouched')

if __name__ == '__main__':
    acceptance.run = run
    acceptance.main()
