"""PostgreSQL acceptance, transport mocked: no live mail or credentials."""
import datetime as dt
import ssl
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, MagicMock


def run(client, app):
    from app import spacemail as m, gmail_oauth as g
    from app.storage import db, one, get_session, utcnow
    s = get_session(client.cookies.get('gla_session'))
    uid = s['user_id']
    data = {'csrf':s['csrf'], 'email':m.ADDRESS, 'password':'ci-test-secret'}
    with db() as c:
        c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (utcnow()+dt.timedelta(minutes=10),s['id']))
    assert client.get(m.PATH).status_code == 200
    with patch.object(m, 'validate') as validate:
        assert client.post(m.PATH, data={**data,'csrf':'wrong'}).status_code == 403
        validate.assert_not_called()
        with db() as c:
            c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (utcnow()-dt.timedelta(seconds=1),s['id']))
        assert client.post(m.PATH, data=data).status_code == 428
        validate.assert_not_called()
        with db() as c:
            c.execute('UPDATE stepup_auth SET expires_at=%s WHERE session_id=%s', (utcnow()+dt.timedelta(minutes=10),s['id']))
        assert client.post(m.PATH, data=data).status_code == 200
    saved = one('SELECT password_enc FROM spacemail_connections WHERE user_id=?',(uid,))
    assert saved['password_enc'] != data['password'] and m.password(uid) == data['password']
    assert data['password'] not in client.get(m.PATH).text
    assert g.connection(uid)['provider'] == 'spacemail'
    assert 'صندوق الوارد الرسمي' in client.get('/settings/email').text
    settings = one('SELECT sender,recipient FROM production_monitor_settings WHERE user_id=?',(uid,))
    assert settings == {'sender':m.ADDRESS,'recipient':m.ADDRESS}
    with patch.object(m, 'validate', side_effect=RuntimeError('private-error')):
        response = client.post(m.PATH,data={**data,'password':'wrong-password'})
        assert 'private-error' not in response.text and m.password(uid)==data['password']
    smtp = MagicMock()
    smtp.send_message.return_value = {}
    with patch.object(m.smtplib, 'SMTP_SSL', return_value=smtp) as factory:
        mid = g.send_gmail(uid, m.ADDRESS, 'test', 'body')
        assert mid.endswith('@shodai.cc>')
        assert factory.call_args.args == (m.HOST,465)
        context = factory.call_args.kwargs['context']
        assert context.check_hostname and context.verify_mode==ssl.CERT_REQUIRED
        smtp.login.assert_called_once_with(m.ADDRESS,data['password'])
    calls=[]
    def send(*args):
        calls.append(args)
        return '<self-test@shodai.cc>'
    with patch.object(m,'send',send):
        with ThreadPoolExecutor(max_workers=3) as pool:
            codes=list(pool.map(lambda _:client.post(m.PATH+'/test',data={'csrf':s['csrf']}).status_code,range(3)))
        assert codes==[200]*3 and len(calls)==1 and calls[0][1]==m.ADDRESS
    imap=MagicMock()
    imap.response.return_value=('UIDVALIDITY',[b'7'])
    imap.uid.side_effect=lambda op,*args: ('OK',[b'1']) if op=='search' else ('OK',[(b'meta',b'From: sender@example.invalid\r\nSubject: <script>untrusted</script>\r\nMessage-ID: <self-test@shodai.cc>\r\nContent-Type: text/plain\r\n\r\nhello')])
    with patch.object(m,'imap_login',return_value=imap):
        m.tick(); m.tick()
    assert one('SELECT COUNT(*) AS n FROM spacemail_inbox WHERE user_id=?',(uid,))['n']==1
    assert one('SELECT test_status FROM spacemail_connections WHERE user_id=?',(uid,))['test_status']=='received'
    assert any(call.args==('fetch','1','(BODY.PEEK[]<0.262144>)') for call in imap.uid.call_args_list)
    response=client.get('/official-inbox')
    assert '&lt;script&gt;' in response.text and '<script>untrusted' not in response.text
    assert 'وارد آفاق طويق' in client.get('/sales-inbox').text
    with patch.dict('os.environ',{'ENABLE_EXTERNAL_ACTIONS':'0'}), patch.object(m,'smtp_login') as login:
        try:m.send(uid,m.ADDRESS,'test','body')
        except RuntimeError:pass
        else:raise AssertionError('send gate ignored')
        login.assert_not_called()
    print('PASS: Spacemail encrypted save, failed validation preserves connection, MFA/CSRF, TLS, official routing, concurrent single test, read-only deduplicated inbox, escaped content, self-delivery verification. Live emails: 0.')
