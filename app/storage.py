import os, sqlite3, hashlib, hmac, secrets, datetime
from contextlib import contextmanager

DB_PATH=os.getenv('DATA_PATH','/data/gulf_logistics_ai.db')

def utcnow(): return datetime.datetime.now(datetime.timezone.utc).isoformat()

def ensure_parent():
    parent=os.path.dirname(DB_PATH)
    if parent: os.makedirs(parent,exist_ok=True)

@contextmanager
def db():
    ensure_parent(); c=sqlite3.connect(DB_PATH,timeout=30); c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        yield c; c.commit()
    finally: c.close()

def hash_password(password,salt=None):
    salt=salt or secrets.token_bytes(16)
    dk=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,210000)
    return salt.hex()+':'+dk.hex()

def verify_password(password,stored):
    try:
        sh,dh=stored.split(':',1); salt=bytes.fromhex(sh)
        got=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,210000).hex()
        return hmac.compare_digest(got,dh)
    except Exception: return False

def init_db(admin_email,admin_password):
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,name TEXT NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'admin',created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,csrf TEXT NOT NULL,expires_at TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,country TEXT,domain TEXT,status TEXT NOT NULL DEFAULT 'lead',notes TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS opportunities(id INTEGER PRIMARY KEY AUTOINCREMENT,account_id INTEGER,company_name TEXT NOT NULL,source_url TEXT,signal TEXT,score INTEGER NOT NULL DEFAULT 0,stage TEXT NOT NULL DEFAULT 'new',estimated_value REAL NOT NULL DEFAULT 0,currency TEXT NOT NULL DEFAULT 'SAR',owner TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE SET NULL);
        CREATE TABLE IF NOT EXISTS shipments(id INTEGER PRIMARY KEY AUTOINCREMENT,account_id INTEGER,reference TEXT UNIQUE NOT NULL,service_type TEXT NOT NULL,origin TEXT,destination TEXT,status TEXT NOT NULL DEFAULT 'new',revenue REAL NOT NULL DEFAULT 0,cost REAL NOT NULL DEFAULT 0,currency TEXT NOT NULL DEFAULT 'SAR',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE SET NULL);
        CREATE TABLE IF NOT EXISTS approvals(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',requested_by INTEGER,decided_by INTEGER,notes TEXT,created_at TEXT NOT NULL,decided_at TEXT);
        CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,action TEXT NOT NULL,entity_type TEXT,entity_id INTEGER,summary TEXT,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_watches(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,url TEXT UNIQUE NOT NULL,source_type TEXT NOT NULL DEFAULT 'web',enabled INTEGER NOT NULL DEFAULT 1,last_status TEXT,last_checked_at TEXT,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS discovered_signals(id INTEGER PRIMARY KEY AUTOINCREMENT,source_watch_id INTEGER,title TEXT,url TEXT UNIQUE NOT NULL,company_name TEXT,excerpt TEXT,score INTEGER NOT NULL DEFAULT 0,matched_terms TEXT,status TEXT NOT NULL DEFAULT 'new',opportunity_id INTEGER,discovered_at TEXT NOT NULL,FOREIGN KEY(source_watch_id) REFERENCES source_watches(id) ON DELETE SET NULL,FOREIGN KEY(opportunity_id) REFERENCES opportunities(id) ON DELETE SET NULL);
        ''')
        row=c.execute('SELECT id FROM users WHERE email=?',(admin_email,)).fetchone()
        if not row:
            c.execute('INSERT INTO users(email,name,password_hash,role,created_at) VALUES(?,?,?,?,?)',(admin_email,'Afaaq Tuwaiq Admin',hash_password(admin_password),'admin',utcnow()))

def cleanup_sessions():
    with db() as c: c.execute('DELETE FROM sessions WHERE expires_at<?',(utcnow(),))

def create_session(user_id,hours=12):
    sid=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(24)
    exp=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=hours)).isoformat()
    with db() as c: c.execute('INSERT INTO sessions(id,user_id,csrf,expires_at,created_at) VALUES(?,?,?,?,?)',(sid,user_id,csrf,exp,utcnow()))
    return sid,csrf,exp

def get_session(sid):
    if not sid: return None
    with db() as c:
        r=c.execute('SELECT s.*,u.email,u.name,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.expires_at>?',(sid,utcnow())).fetchone()
        return dict(r) if r else None

def delete_session(sid):
    with db() as c: c.execute('DELETE FROM sessions WHERE id=?',(sid,))

def authenticate(email,password):
    with db() as c:
        r=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
        return dict(r) if r and verify_password(password,r['password_hash']) else None

def rows(sql,args=()):
    with db() as c: return [dict(r) for r in c.execute(sql,args).fetchall()]

def one(sql,args=()):
    with db() as c:
        r=c.execute(sql,args).fetchone(); return dict(r) if r else None

def execute(sql,args=()):
    with db() as c:
        cur=c.execute(sql,args); return cur.lastrowid

def log(user_id,action,entity_type=None,entity_id=None,summary=''):
    execute('INSERT INTO activity(user_id,action,entity_type,entity_id,summary,created_at) VALUES(?,?,?,?,?,?)',(user_id,action,entity_type,entity_id,summary,utcnow()))
