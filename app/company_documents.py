"""Private immutable company archive. No OCR, AI, external calls or public files."""
import hashlib
import hmac
import html
import io
import os
import re
import subprocess
import tempfile
import warnings
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from PIL import Image
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from python_multipart.exceptions import MultipartParseError

router = APIRouter()
ENABLED = os.getenv('COMPANY_DOCUMENTS_ENABLED', '0') == '1'
MAX_BYTES = 10 * 1024 * 1024
KINDS = {'transport_license':'رخصة النقل','customs_license':'رخصة التخليص','commercial_registration':'السجل التجاري','national_address':'العنوان الوطني','tax_certificate':'شهادة الضريبة','other':'مستند شركة آخر'}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS company_documents (
 id UUID PRIMARY KEY, name TEXT NOT NULL CHECK(length(name) BETWEEN 2 AND 120),
 kind TEXT NOT NULL CHECK(kind IN ('transport_license','customs_license','commercial_registration','national_address','tax_certificate','other')),
 issued_on DATE, expires_on DATE, status TEXT NOT NULL DEFAULT 'archived_copy' CHECK(status='archived_copy'),
 media_type TEXT NOT NULL CHECK(media_type IN ('application/pdf','image/png','image/jpeg')),
 sha256 TEXT NOT NULL UNIQUE CHECK(length(sha256)=64), byte_count INTEGER NOT NULL CHECK(byte_count BETWEEN 1 AND 10485760),
 content BYTEA NOT NULL CHECK(octet_length(content)=byte_count),
 created_by BIGINT NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CHECK(issued_on IS NULL OR expires_on IS NULL OR expires_on>=issued_on)
);
CREATE TABLE IF NOT EXISTS company_document_audit (
 id BIGSERIAL PRIMARY KEY, document_id UUID REFERENCES company_documents(id), actor_id BIGINT NOT NULL REFERENCES users(id),
 action TEXT NOT NULL CHECK(action IN ('upload','duplicate','download','list')), created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION company_archive_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Company archive rows are immutable'; END $$;
DROP TRIGGER IF EXISTS company_archive_immutable ON company_documents;
CREATE TRIGGER company_archive_immutable BEFORE UPDATE OR DELETE ON company_documents FOR EACH ROW EXECUTE FUNCTION company_archive_immutable();
DROP TRIGGER IF EXISTS company_archive_audit_immutable ON company_document_audit;
CREATE TRIGGER company_archive_audit_immutable BEFORE UPDATE OR DELETE ON company_document_audit FOR EACH ROW EXECUTE FUNCTION company_archive_immutable();
'''
HEADERS = {'Cache-Control':'no-store, private','Pragma':'no-cache','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"}


def database():
    # Reuse production's shared PostgreSQL connection; never a local disk archive.
    from app.storage import db
    return db()


def init_storage():
    with database() as c:
        c.execute('SELECT pg_advisory_xact_lock(73002091)')
        c.execute(SCHEMA)


def admin(request):
    if not ENABLED: raise HTTPException(404)
    sid=request.cookies.get('gla_session')
    if not sid: raise HTTPException(401)
    with database() as c:
        actor=c.execute('''SELECT s.id,s.csrf,s.user_id,u.role,u.is_active,u.must_change_password
          FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=%s AND s.expires_at>now()''',(sid,)).fetchone()
    if not actor: raise HTTPException(401)
    if actor['role']!='admin' or not actor['is_active'] or actor['must_change_password']: raise HTTPException(403)
    return actor


def audit(c,actor,action,document_id=None):
    # Do not log document names, filenames, hashes, bytes, dates or identifiers within documents.
    c.execute('INSERT INTO company_document_audit(document_id,actor_id,action) VALUES(%s,%s,%s)',(document_id,actor['user_id'],action))


def check_file(data,media,filename):
    suffix={'application/pdf':'.pdf','image/png':'.png','image/jpeg':'.jpg'}.get(media)
    if not suffix or not data or len(data)>MAX_BYTES: raise HTTPException(415,'PDF وPNG وJPEG فقط، حتى 10MB')
    if not filename or len(filename)>200 or re.search(r'[/\\\x00-\x1f\x7f]',filename) or filename in ('.','..'): raise HTTPException(400,'اسم الملف غير صالح')
    if media=='application/pdf':
        if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-1024:]: raise HTTPException(415,'PDF غير صالح')
        with tempfile.TemporaryDirectory(prefix='afaq-company-') as folder:
            path=Path(folder)/'source.pdf';path.write_bytes(data)
            try:result=subprocess.run(['pdfinfo',str(path)],capture_output=True,timeout=5,check=False)
            except (OSError,subprocess.TimeoutExpired):raise HTTPException(422,'تعذر فحص الملف محليًا') from None
        if result.returncode or not re.search(rb'^Pages:\s*[1-9][0-9]*\s*$',result.stdout,re.M) or re.search(rb'^Encrypted:\s*yes',result.stdout,re.M):raise HTTPException(422,'PDF تالف أو مشفر')
    else:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as picture:
                    if picture.format!=('PNG' if media=='image/png' else 'JPEG') or picture.width*picture.height>20000000:raise ValueError()
                    picture.verify()
        except (OSError,ValueError,Image.DecompressionBombWarning,Image.DecompressionBombError):raise HTTPException(415,'الصورة غير صالحة') from None
    return suffix


async def upload_form(request,actor):
    if request.headers.get('content-type','').split(';')[0].strip().lower()!='multipart/form-data':raise HTTPException(415)
    total=0
    async def bounded():
        nonlocal total
        async for chunk in request.stream():
            total+=len(chunk)
            if total>MAX_BYTES+65536:raise MultiPartException('Size limit')
            yield chunk
    parser=MultiPartParser(request.headers,bounded(),max_files=1,max_fields=5,max_part_size=2048)
    form=None
    try:
        form=await parser.parse()
        if set(form)!={'csrf','name','kind','issued_on','expires_on','file'} or any(len(form.getlist(k))!=1 for k in form):raise HTTPException(400)
        if not isinstance(form['csrf'],str) or not hmac.compare_digest(form['csrf'],actor['csrf']):raise HTTPException(403)
        name=str(form['name']).strip();kind=str(form['kind'])
        if not 2<=len(name)<=120 or re.search(r'[\x00-\x1f\x7f]',name) or kind not in KINDS:raise HTTPException(422,'راجع اسم المستند ونوعه')
        try:issued=date.fromisoformat(form['issued_on']) if form['issued_on'] else None;expires=date.fromisoformat(form['expires_on']) if form['expires_on'] else None
        except (ValueError,TypeError):raise HTTPException(422,'تاريخ غير صالح') from None
        if issued and expires and expires<issued:raise HTTPException(422,'الانتهاء قبل الإصدار')
        file=form['file']
        if not isinstance(file,UploadFile):raise HTTPException(400)
        data=await file.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:raise HTTPException(413)
        await run_in_threadpool(check_file,data,file.content_type,file.filename)
        return name,kind,issued,expires,file.content_type,data
    except (MultiPartException,MultipartParseError):raise HTTPException(413,'نموذج غير صالح أو تجاوز الحجم') from None
    finally:
        try:
            if form is not None:await form.close()
        finally:
            for file in parser._files_to_close_on_error:file.close()


@router.get('/company-documents',response_class=HTMLResponse)
def index(request:Request):
    actor=admin(request)
    with database() as c:
        # This table contains company records only; never query customer document stores.
        records=c.execute('SELECT id,name,kind,issued_on,expires_on,status,sha256,byte_count,created_at FROM company_documents ORDER BY created_at DESC LIMIT 200').fetchall()
        audit(c,actor,'list')
    e=lambda value:html.escape(str(value or '—'))
    options=''.join(f'<option value="{k}">{v}</option>' for k,v in KINDS.items())
    entries=''.join(f'<tr><td>{e(r["name"])}</td><td>{e(KINDS[r["kind"]])}</td><td>{e(r["issued_on"])}</td><td>{e(r["expires_on"])}</td><td>نسخة أرشيفية غير متحقق منها</td><td><a href="/company-documents/{r["id"]}/download">تنزيل الأصل</a><details><summary>البصمة والحجم</summary><code>{e(r["sha256"])}</code><p>{r["byte_count"]} bytes</p></details></td></tr>' for r in records)
    body=f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مستندات الشركة</title><style>body{{font-family:Arial;max-width:1100px;margin:auto;padding:24px;background:#07131f;color:#eef6fb}}a{{color:#86efac}}label{{display:block;margin:12px 0}}input,select,button{{padding:10px;max-width:100%;box-sizing:border-box}}.table{{overflow:auto}}td,th{{padding:12px;border-bottom:1px solid #456}}code{{overflow-wrap:anywhere}}</style><a href="/dashboard">لوحة التشغيل</a><h1>مستندات الشركة</h1><p>أرشيف خاص للإدارة. لا مشاركة أو إرسال أو تحليل آلي. الحفظ ليس تحققًا من صحة المستند أو سريانه. لا ترفع مستندات العملاء هنا.</p><form method="post" enctype="multipart/form-data" action="/company-documents"><input type="hidden" name="csrf" value="{e(actor['csrf'])}"><label>اسم المستند<input name="name" minlength="2" maxlength="120" required></label><label>نوع المستند<select name="kind">{options}</select></label><label>تاريخ الإصدار<input type="date" name="issued_on"></label><label>تاريخ الانتهاء<input type="date" name="expires_on"></label><label>الملف الأصلي — حتى 10MB<input type="file" name="file" accept="application/pdf,image/png,image/jpeg" required></label><button>حفظ نسخة أرشيفية</button></form><p>الملف المطابق لبصمة محفوظة لا يُكرر، ولا تُستبدل بيانات الأصل. النسخة المختلفة تُحفظ كسجل جديد. أحدث 200 سجل:</p><div class="table"><table><tr><th>المستند</th><th>النوع</th><th>الإصدار</th><th>الانتهاء</th><th>الحالة</th><th>الأصل</th></tr>{entries}</table></div></html>'''
    return HTMLResponse(body,headers=HEADERS)


@router.post('/company-documents')
async def upload(request:Request):
    actor=admin(request)
    name,kind,issued,expires,media,data=await upload_form(request,actor)
    current=admin(request)
    if current['user_id']!=actor['user_id']:raise HTTPException(403)
    sha=hashlib.sha256(data).hexdigest()
    with database() as c:
        new=c.execute('''INSERT INTO company_documents(id,name,kind,issued_on,expires_on,media_type,sha256,byte_count,content,created_by)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(sha256) DO NOTHING RETURNING id''',
          (uuid4(),name,kind,issued,expires,media,sha,len(data),data,actor['user_id'])).fetchone()
        found=new or c.execute('SELECT id FROM company_documents WHERE sha256=%s',(sha,)).fetchone()
        audit(c,actor,'upload' if new else 'duplicate',found['id'])
    return RedirectResponse('/company-documents',303,headers=HEADERS)


@router.get('/company-documents/{document_id}/download')
def download(document_id:UUID,request:Request):
    actor=admin(request)
    with database() as c:
        row=c.execute('SELECT media_type,content,sha256 FROM company_documents WHERE id=%s',(document_id,)).fetchone()
        if not row:raise HTTPException(404)
        data=bytes(row['content'])
        if hashlib.sha256(data).hexdigest()!=row['sha256']:raise HTTPException(409,'تعذر التحقق من سلامة الأصل')
        audit(c,actor,'download',document_id)
    suffix={'application/pdf':'pdf','image/png':'png','image/jpeg':'jpg'}[row['media_type']]
    return Response(data,media_type=row['media_type'],headers={**HEADERS,'Content-Disposition':f'attachment; filename="company-document-{document_id}.{suffix}"'})
