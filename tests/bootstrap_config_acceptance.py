"""Synthetic local PostgreSQL startup checks; existing credentials never rotate."""
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import carrier_directory_acceptance as acceptance


def run():
    from app.storage import init_db, one, authenticate
    original=secrets.token_urlsafe(30)
    replacement=secrets.token_urlsafe(30)
    email='bootstrap-existing@fixture.invalid'
    init_db(email,original)
    saved=one('SELECT id,password_hash FROM users WHERE email=%s',(email,))
    script='''import socket
connect=socket.socket.connect
def local_only(sock,address):
    if isinstance(address,tuple) and address[0] not in ('localhost','127.0.0.1','::1'):
        raise AssertionError('External network blocked in bootstrap fixture')
    return connect(sock,address)
socket.socket.connect=local_only
from app.afaq_only import app
print('APPLICATION_READY')
'''
    for value in (None,'',replacement):
        env=dict(os.environ,ADMIN_EMAIL=email,ENABLE_EXTERNAL_ACTIONS='0',DISCOVERY_AUTO_ENABLED='0')
        if value is None:env.pop('ADMIN_PASSWORD',None)
        else:env['ADMIN_PASSWORD']=value
        result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,env=env,text=True,capture_output=True,timeout=60)
        if value:
            assert result.returncode==0 and 'APPLICATION_READY' in result.stdout,result.stderr
        else:
            assert result.returncode!=0
            assert 'Administrator bootstrap password is not configured' in result.stderr
            assert 'APPLICATION_READY' not in result.stdout
        assert original not in result.stdout+result.stderr and replacement not in result.stdout+result.stderr
        assert one('SELECT id,password_hash FROM users WHERE email=%s',(email,))==saved
        assert authenticate(email,original) is not None
        assert authenticate(email,replacement) is None
    assert one('SELECT COUNT(*) n FROM users')['n']==1
    print('PASS: missing/empty deployment configuration fails closed; configured production entrypoint starts; existing admin ID/password hash/login unchanged; no secret output.')


if __name__=='__main__':
    acceptance.run=run
    acceptance.main()
