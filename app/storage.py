import os, hashlib, hmac, secrets, datetime
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row

DATABASE_URL=os.getenv('DATABASE_URL','')
if not DATABASE_URL: raise RuntimeError('DATABASE_URL is required for production shared storage')
OFFICIAL_DISCOVERY_SOURCES=[('ZATCA Tenders & Procurement','https://www.zatca.gov.sa/ar/AboutUs/Pages/Procurement-and-Tenders.aspx','web'),('ZATCA Procurement Plan 2026','https://zatca.gov.sa/ar/MediaCenter/Elan/Pages/Procurement-and-Tenders-for-the-Fiscal-Year-2026.aspx','web')]
def utcnow(): return datetime.datetime.now(datetime.timezone.utc)
@contextmanager
def db():
    with psycopg.connect(DATABASE_URL,row_factory=dict_row,autocommit=False) as c:
        try: yield c; c.commit()
        except Exception: c.rollback(); raise
def hash_password(password,salt=None):
    salt=salt or secrets.token_bytes(16);dk=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,210000);return salt.hex()+':'+dk.hex()
def verify_password(password,stored):
    try:
        sh,dh=stored.split(':',1);salt=bytes.fromhex(sh);got=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,210000).hex();return hmac.compare_digest(got,dh)
    except Exception:return False
def init_db(admin_email,admin_password):
    ddl=[
    '''CREATE TABLE IF NOT EXISTS users(id BIGSERIAL PRIMARY KEY,email TEXT UNIQUE NOT NULL,name TEXT NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'admin',created_at TIMESTAMPTZ NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,csrf TEXT NOT NULL,expires_at TIMESTAMPTZ NOT NULL,created_at TIMESTAMPTZ NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS accounts(id BIGSERIAL PRIMARY KEY,name TEXT NOT NULL,country TEXT,domain TEXT,status TEXT NOT NULL DEFAULT 'lead',notes TEXT,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS opportunities(id BIGSERIAL PRIMARY KEY,account_id BIGINT REFERENCES accounts(id) ON DELETE SET NULL,company_name TEXT NOT NULL,source_url TEXT,signal TEXT,score INTEGER NOT NULL DEFAULT 0,stage TEXT NOT NULL DEFAULT 'new',estimated_value DOUBLE PRECISION NOT NULL DEFAULT 0,currency TEXT NOT NULL DEFAULT 'SAR',owner TEXT,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS opportunity_intelligence(id BIGSERIAL PRIMARY KEY,opportunity_id BIGINT UNIQUE NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,priority TEXT NOT NULL,intent TEXT NOT NULL,services TEXT,evidence TEXT,next_action TEXT,proposal_draft TEXT,follow_up_status TEXT NOT NULL DEFAULT 'draft',generated_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS shipments(id BIGSERIAL PRIMARY KEY,account_id BIGINT REFERENCES accounts(id) ON DELETE SET NULL,reference TEXT UNIQUE NOT NULL,service_type TEXT NOT NULL,origin TEXT,destination TEXT,status TEXT NOT NULL DEFAULT 'new',revenue DOUBLE PRECISION NOT NULL DEFAULT 0,cost DOUBLE PRECISION NOT NULL DEFAULT 0,currency TEXT NOT NULL DEFAULT 'SAR',created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS approvals(id BIGSERIAL PRIMARY KEY,kind TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id BIGINT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',requested_by BIGINT,decided_by BIGINT,notes TEXT,created_at TIMESTAMPTZ NOT NULL,decided_at TIMESTAMPTZ)''',
    '''CREATE TABLE IF NOT EXISTS outbound_messages(id BIGSERIAL PRIMARY KEY,opportunity_id BIGINT REFERENCES opportunities(id) ON DELETE CASCADE,channel TEXT NOT NULL DEFAULT 'email',recipient TEXT,subject TEXT,body TEXT NOT NULL,proposal_text TEXT,status TEXT NOT NULL DEFAULT 'draft',approval_id BIGINT REFERENCES approvals(id) ON DELETE SET NULL,provider TEXT,provider_message_id TEXT,last_error TEXT,created_by BIGINT,approved_by BIGINT,created_at TIMESTAMPTZ NOT NULL,approved_at TIMESTAMPTZ,sent_at TIMESTAMPTZ,updated_at TIMESTAMPTZ NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS activity(id BIGSERIAL PRIMARY KEY,user_id BIGINT,action TEXT NOT NULL,entity_type TEXT,entity_id BIGINT,summary TEXT,created_at TIMESTAMPTZ NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS source_watches(id BIGSERIAL PRIMARY KEY,name TEXT NOT NULL,url TEXT UNIQUE NOT NULL,source_type TEXT NOT NULL DEFAULT 'web',enabled INTEGER NOT NULL DEFAULT 1,last_status TEXT,last_checked_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS discovered_signals(id BIGSERIAL PRIMARY KEY,source_watch_id BIGINT REFERENCES source_watches(id) ON DELETE SET NULL,title TEXT,url TEXT UNIQUE NOT NULL,company_name TEXT,excerpt TEXT,score INTEGER NOT NULL DEFAULT 0,matched_terms TEXT,status TEXT NOT NULL DEFAULT 'new',opportunity_id BIGINT REFERENCES opportunities(id) ON DELETE SET NULL,discovered_at TIMESTAMPTZ NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS email_connections(id BIGSERIAL PRIMARY KEY,user_id BIGINT UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,provider TEXT NOT NULL,sender_email TEXT,refresh_token_enc TEXT NOT NULL,scope TEXT,status TEXT NOT NULL DEFAULT 'connected',connected_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS sales_contacts(id BIGSERIAL PRIMARY KEY,opportunity_id BIGINT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,name TEXT,job_title TEXT,email TEXT,phone TEXT,source_url TEXT,verified INTEGER NOT NULL DEFAULT 0,notes TEXT,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS sales_followups(id BIGSERIAL PRIMARY KEY,opportunity_id BIGINT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,kind TEXT NOT NULL DEFAULT 'follow_up',due_at TIMESTAMPTZ NOT NULL,status TEXT NOT NULL DEFAULT 'open',notes TEXT,created_by BIGINT,created_at TIMESTAMPTZ NOT NULL,completed_at TIMESTAMPTZ)''',
    '''CREATE TABLE IF NOT EXISTS sales_outcomes(id BIGSERIAL PRIMARY KEY,opportunity_id BIGINT UNIQUE NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,outcome TEXT NOT NULL,reason TEXT,realized_value DOUBLE PRECISION NOT NULL DEFAULT 0,currency TEXT NOT NULL DEFAULT 'SAR',recorded_by BIGINT,recorded_at TIMESTAMPTZ NOT NULL)''']
    with db() as c:
        for sql in ddl:c.execute(sql)
        row=c.execute('SELECT id FROM users WHERE email=%s',(admin_email,)).fetchone()
        if not row:c.execute('INSERT INTO users(email,name,password_hash,role,created_at) VALUES(%s,%s,%s,%s,%s)',(admin_email,'Afaaq Tuwaiq Admin',hash_password(admin_password),'admin',utcnow()))
        for name,url,source_type in OFFICIAL_DISCOVERY_SOURCES:c.execute('''INSERT INTO source_watches(name,url,source_type,enabled,last_status,last_checked_at,created_at) VALUES(%s,%s,%s,1,'seeded',NULL,%s) ON CONFLICT(url) DO UPDATE SET name=EXCLUDED.name,source_type=EXCLUDED.source_type,enabled=1''',(name,url,source_type,utcnow()))
def cleanup_sessions():
    with db() as c:c.execute('DELETE FROM sessions WHERE expires_at<%s',(utcnow(),))
def create_session(user_id,hours=12):
    sid=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24);exp=utcnow()+datetime.timedelta(hours=hours)
    with db() as c:c.execute('INSERT INTO sessions(id,user_id,csrf,expires_at,created_at) VALUES(%s,%s,%s,%s,%s)',(sid,user_id,csrf,exp,utcnow()))
    return sid,csrf,exp.isoformat()
def get_session(sid):
    if not sid:return None
    with db() as c:
        r=c.execute('SELECT s.*,u.email,u.name,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=%s AND s.expires_at>%s',(sid,utcnow())).fetchone();return dict(r) if r else None
def delete_session(sid):
    with db() as c:c.execute('DELETE FROM sessions WHERE id=%s',(sid,))
def authenticate(email,password):
    with db() as c:
        r=c.execute('SELECT * FROM users WHERE email=%s',(email,)).fetchone();return dict(r) if r and verify_password(password,r['password_hash']) else None
def _sql(sql):return sql.replace('?', '%s')
def rows(sql,args=()):
    with db() as c:return [dict(r) for r in c.execute(_sql(sql),args).fetchall()]
def one(sql,args=()):
    with db() as c:r=c.execute(_sql(sql),args).fetchone();return dict(r) if r else None
def execute(sql,args=()):
    sql=_sql(sql)
    with db() as c:
        if sql.lstrip().upper().startswith('INSERT INTO') and ' RETURNING ' not in sql.upper():
            cur=c.execute(sql+' RETURNING id',args);r=cur.fetchone();return r['id'] if r else None
        c.execute(sql,args);return None
def log(user_id,action,entity_type=None,entity_id=None,summary=''):execute('INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at) VALUES(?,?,?,?,?,?)',(user_id,action,entity_type,entity_id,summary,utcnow()))
