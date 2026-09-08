import os,secrets,base64,html
from email.message import EmailMessage
import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from app.storage import get_session,one,execute,log,utcnow
router=APIRouter()
AUTH='https://accounts.google.com/o/oauth2/v2/auth';TOKEN='https://oauth2.googleapis.com/token';USERINFO='https://www.googleapis.com/oauth2/v2/userinfo';SEND='https://gmail.googleapis.com/gmail/v1/users/me/messages/send'
def auth(r):
 s=get_session(r.cookies.get('gla_session'))
 if not s:raise HTTPException(401)
 return s
def cfg():
 cid=os.getenv('GOOGLE_CLIENT_ID');sec=os.getenv('GOOGLE_CLIENT_SECRET');redir=os.getenv('GOOGLE_REDIRECT_URI');key=os.getenv('TOKEN_ENCRYPTION_KEY');scope=os.getenv('GOOGLE_GMAIL_SCOPE','https://www.googleapis.com/auth/gmail.send')
 if not all((cid,sec,redir,key)):raise RuntimeError('Google OAuth is not fully configured')
 return cid,sec,redir,key,scope
def enc(v,key):return Fernet(key.encode()).encrypt(v.encode()).decode()
def dec(v,key):return Fernet(key.encode()).decrypt(v.encode()).decode()
def connection(uid):return one('SELECT * FROM email_connections WHERE user_id=?',(uid,))
@router.get('/settings/email',response_class=HTMLResponse)
def settings(request:Request):
 s=auth(request);c=connection(s['user_id']);configured=all(os.getenv(k) for k in ('GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','GOOGLE_REDIRECT_URI','TOKEN_ENCRYPTION_KEY'))
 status=('متصل: '+html.escape(c.get('sender_email') or 'Gmail')) if c and c.get('status')=='connected' else 'غير متصل'
 action='<a href="/auth/google/start" style="display:inline-block;padding:12px 18px;background:#22c55e;color:#06120b;border-radius:10px;text-decoration:none;font-weight:bold">ربط Gmail</a>' if configured else '<b>إعداد Google OAuth غير مكتمل في Railway.</b>'
 if c and c.get('status')=='connected':action+='<form method="post" action="/settings/email/disconnect" style="margin-top:12px"><button>فصل الربط</button></form>'
 return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><title>إعداد البريد</title><body style="font-family:Arial;background:#07131f;color:white;padding:30px"><a href="/dashboard" style="color:white">الرئيسية</a><h1>قناة البريد</h1><p>'+status+'</p><p>النطاق المطلوب: إرسال Gmail فقط. لا تتم قراءة البريد.</p>'+action+'</body></html>')
@router.get('/auth/google/start')
def start(request:Request):
 s=auth(request);cid,sec,redir,key,scope=cfg();state=secrets.token_urlsafe(32);execute('UPDATE sessions SET csrf=? WHERE id=?',(state,s['id']))
 q=httpx.QueryParams({'client_id':cid,'redirect_uri':redir,'response_type':'code','scope':scope+' openid email','access_type':'offline','prompt':'consent','state':state,'include_granted_scopes':'true'})
 return RedirectResponse(AUTH+'?'+str(q),302)
@router.get('/auth/google/callback')
def callback(request:Request,code:str='',state:str='',error:str=''):
 s=auth(request)
 if error:raise HTTPException(400,'Google authorization was not completed')
 if not state or not secrets.compare_digest(state,s.get('csrf') or ''):raise HTTPException(400,'Invalid OAuth state')
 cid,sec,redir,key,scope=cfg()
 with httpx.Client(timeout=20) as client:
  tr=client.post(TOKEN,data={'code':code,'client_id':cid,'client_secret':sec,'redirect_uri':redir,'grant_type':'authorization_code'});tr.raise_for_status();tok=tr.json();refresh=tok.get('refresh_token')
  if not refresh:raise HTTPException(400,'Google did not return an offline refresh token')
  ui=client.get(USERINFO,headers={'Authorization':'Bearer '+tok['access_token']});ui.raise_for_status();sender=ui.json().get('email','')
 now=utcnow();existing=connection(s['user_id']);cipher=enc(refresh,key)
 if existing:execute('UPDATE email_connections SET sender_email=?,refresh_token_enc=?,scope=?,status=?,updated_at=? WHERE user_id=?',(sender,cipher,scope,'connected',now,s['user_id']))
 else:execute('INSERT INTO email_connections(user_id,provider,sender_email,refresh_token_enc,scope,status,connected_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(s['user_id'],'gmail',sender,cipher,scope,'connected',now,now))
 execute('UPDATE sessions SET csrf=? WHERE id=?',(secrets.token_urlsafe(24),s['id']));log(s['user_id'],'connect_gmail','email_connection',None,'Gmail sender connected');return RedirectResponse('/settings/email',303)
@router.post('/settings/email/disconnect')
def disconnect(request:Request):
 s=auth(request);execute('DELETE FROM email_connections WHERE user_id=?',(s['user_id'],));log(s['user_id'],'disconnect_gmail','email_connection',None,'Gmail sender disconnected');return RedirectResponse('/settings/email',303)
def send_gmail(user_id,recipient,subject,body):
 if os.getenv('ENABLE_EXTERNAL_ACTIONS','0')!='1':raise RuntimeError('External actions are disabled')
 c=connection(user_id)
 if not c or c.get('status')!='connected':raise RuntimeError('Gmail is not connected')
 cid,sec,redir,key,scope=cfg();refresh=dec(c['refresh_token_enc'],key)
 with httpx.Client(timeout=25) as client:
  tr=client.post(TOKEN,data={'client_id':cid,'client_secret':sec,'refresh_token':refresh,'grant_type':'refresh_token'});tr.raise_for_status();access=tr.json()['access_token']
  msg=EmailMessage();msg['To']=recipient;msg['From']=c.get('sender_email') or 'me';msg['Subject']=subject;msg.set_content(body);raw=base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip('=')
  sr=client.post(SEND,headers={'Authorization':'Bearer '+access},json={'raw':raw});sr.raise_for_status();return sr.json().get('id','')
