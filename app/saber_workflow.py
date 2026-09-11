import datetime
import hashlib
import html
import re
import subprocess
import tempfile
import urllib.parse
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app.shipping_agents import extract_document_text
from app.storage import db, execute, get_session, log, one, rows, utcnow


router = APIRouter()


def init_storage():
    statements = [
        """CREATE TABLE IF NOT EXISTS saber_cases(id BIGSERIAL PRIMARY KEY,case_reference TEXT UNIQUE NOT NULL,shipment_id BIGINT REFERENCES shipments(id) ON DELETE SET NULL,account_id BIGINT REFERENCES accounts(id) ON DELETE SET NULL,importer_name TEXT,commercial_registration TEXT,invoice_number TEXT,invoice_date DATE,country_of_origin TEXT,supplier_name TEXT,submission_type TEXT NOT NULL DEFAULT 'shipment_certificate',regulatory_route TEXT NOT NULL DEFAULT 'unknown',status TEXT NOT NULL DEFAULT 'draft',saber_request_number TEXT,certificate_number TEXT,certificate_url TEXT,notes TEXT,approval_id BIGINT REFERENCES approvals(id) ON DELETE SET NULL,submitted_at TIMESTAMPTZ,issued_at TIMESTAMPTZ,due_at TIMESTAMPTZ,created_by BIGINT REFERENCES users(id),created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS saber_products(id BIGSERIAL PRIMARY KEY,case_id BIGINT NOT NULL REFERENCES saber_cases(id) ON DELETE CASCADE,description TEXT NOT NULL,hs_code TEXT,brand TEXT,model TEXT,manufacturer TEXT,quantity DOUBLE PRECISION,unit TEXT,country_of_origin TEXT,technical_regulation TEXT,conformity_status TEXT NOT NULL DEFAULT 'needs_review',notes TEXT,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS saber_documents(id BIGSERIAL PRIMARY KEY,case_id BIGINT NOT NULL REFERENCES saber_cases(id) ON DELETE CASCADE,document_type TEXT NOT NULL,filename TEXT NOT NULL,media_type TEXT NOT NULL,file_size BIGINT NOT NULL,file_sha256 TEXT NOT NULL,content BYTEA,extracted_text TEXT,extraction_status TEXT NOT NULL DEFAULT 'processed',created_by BIGINT REFERENCES users(id),created_at TIMESTAMPTZ NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS saber_followups(id BIGSERIAL PRIMARY KEY,case_id BIGINT NOT NULL REFERENCES saber_cases(id) ON DELETE CASCADE,kind TEXT NOT NULL,title TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',due_at TIMESTAMPTZ,notes TEXT,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)""",
    ]
    with db() as c:
        for statement in statements: c.execute(statement)


init_storage()


def esc(value): return html.escape(str(value or ""))
def parse(raw): return {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode(), keep_blank_values=True).items()}
def auth(request):
    current = get_session(request.cookies.get("gla_session"))
    if not current: raise HTTPException(401, "Login required")
    return current


def page(title, body):
    return f"""<!doctype html><html lang=ar dir=rtl><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{esc(title)}</title><style>body{{font-family:Arial;background:#07131f;color:#eef6fb;margin:0;padding:24px}}.wrap{{max-width:1250px;margin:auto}}a{{color:#86efac}}.nav{{display:flex;gap:8px;flex-wrap:wrap}}.btn,button{{display:inline-block;background:#ff7900;color:white;border:0;border-radius:9px;padding:11px 14px;text-decoration:none;font-weight:bold;cursor:pointer}}.card{{background:#102536;padding:20px;margin:14px 0;border-radius:16px;overflow:auto}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}}.kpi{{background:#0b1d2b;padding:16px;border-radius:12px}}.kpi b{{font-size:24px;display:block}}input,select,textarea{{width:100%;box-sizing:border-box;padding:11px;margin:6px 0;border:1px solid #36586e;border-radius:8px;background:#081925;color:white}}textarea{{min-height:110px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;text-align:right;border-bottom:1px solid #28475d;vertical-align:top}}.good{{color:#86efac}}.warn{{color:#fde68a}}.bad{{color:#fca5a5}}label{{display:block;margin-top:8px;font-weight:bold}}pre{{white-space:pre-wrap}}</style><div class=wrap>{body}</div></html>"""


def nav(): return "<div class=nav><a class=btn href=/dashboard>الرئيسية</a><a class=btn href=/saber>طلبات سابر</a><a class=btn href=/saber/new>طلب جديد</a><a class=btn href=/shipments>الشحنات</a><a class=btn href=/approvals>الموافقات</a><a class=btn href=https://saber.sa/ target=_blank>منصة سابر الرسمية</a></div>"


def readiness(case_id):
    case = one("SELECT * FROM saber_cases WHERE id=?", (case_id,)); products = rows("SELECT * FROM saber_products WHERE case_id=?", (case_id,)); docs = rows("SELECT document_type FROM saber_documents WHERE case_id=?", (case_id,))
    if not case: return None, [], ["الطلب غير موجود"]
    missing = []
    for key, label in (("importer_name", "اسم المستورد"), ("commercial_registration", "السجل التجاري"), ("invoice_number", "رقم الفاتورة"), ("invoice_date", "تاريخ الفاتورة"), ("country_of_origin", "بلد المنشأ"), ("supplier_name", "المورد")):
        if not case.get(key): missing.append(label)
    if case.get("regulatory_route") == "unknown": missing.append("قرار الخضوع للائحة الفنية")
    if not products: missing.append("منتج واحد على الأقل")
    for index, product in enumerate(products, 1):
        if not re.fullmatch(r"\d{6,12}", re.sub(r"\D", "", product.get("hs_code") or "")): missing.append(f"رمز HS للمنتج {index}")
        if product.get("conformity_status") == "needs_review": missing.append(f"مراجعة المطابقة للمنتج {index}")
    types = {x["document_type"] for x in docs}
    if "commercial_invoice" not in types: missing.append("الفاتورة التجارية")
    if "bill_of_lading" not in types: missing.append("بوليصة الشحن")
    return case, products, list(dict.fromkeys(missing))


@router.get("/saber", response_class=HTMLResponse)
def saber_home(request: Request):
    auth(request); cases = rows("""SELECT x.*,s.reference shipment_reference,a.name account_name,
        (SELECT COUNT(*) FROM saber_products p WHERE p.case_id=x.id) products,
        (SELECT COUNT(*) FROM saber_documents d WHERE d.case_id=x.id) documents
        FROM saber_cases x LEFT JOIN shipments s ON s.id=x.shipment_id LEFT JOIN accounts a ON a.id=x.account_id ORDER BY x.id DESC""")
    counts = one("""SELECT COUNT(*) total,COUNT(*) FILTER(WHERE status='draft') drafts,COUNT(*) FILTER(WHERE status='pending_approval') pending,COUNT(*) FILTER(WHERE status IN ('submitted','under_review')) active,COUNT(*) FILTER(WHERE status='issued') issued FROM saber_cases""")
    table = "".join(f"<tr><td><a href='/saber/{x['id']}'>{esc(x['case_reference'])}</a></td><td>{esc(x.get('shipment_reference'))}</td><td>{esc(x.get('account_name') or x.get('importer_name'))}</td><td>{x['products']}</td><td>{x['documents']}</td><td>{esc(x['regulatory_route'])}</td><td>{esc(x['status'])}</td></tr>" for x in cases)
    body = nav() + f"<h1>مركز تجهيز ومتابعة سابر</h1><p class=warn>النظام يجهز ويتابع. التقديم الرسمي يتم بواسطة مستخدم مخول في منصة سابر بعد الاعتماد.</p><div class=grid><div class=kpi>الإجمالي<b>{counts['total']}</b></div><div class=kpi>مسودات<b>{counts['drafts']}</b></div><div class=kpi>بانتظار الاعتماد<b>{counts['pending']}</b></div><div class=kpi>قيد الإجراء<b>{counts['active']}</b></div><div class=kpi>صادرة<b>{counts['issued']}</b></div></div><div class=card><table><tr><th>الطلب</th><th>الشحنة</th><th>المستورد</th><th>المنتجات</th><th>المستندات</th><th>المسار التنظيمي</th><th>الحالة</th></tr>{table or '<tr><td colspan=7>لا توجد طلبات.</td></tr>'}</table></div>"
    return HTMLResponse(page("طلبات سابر", body))


@router.get("/saber/new", response_class=HTMLResponse)
def new_case_page(request: Request):
    current = auth(request); shipments = rows("SELECT id,reference,origin,destination FROM shipments ORDER BY id DESC LIMIT 300"); accounts = rows("SELECT id,name FROM accounts ORDER BY name")
    ship_opts = "<option value=''>بدون شحنة</option>" + "".join(f"<option value='{x['id']}'>{esc(x['reference'])} - {esc(x['origin'])} إلى {esc(x['destination'])}</option>" for x in shipments)
    account_opts = "<option value=''>بدون عميل</option>" + "".join(f"<option value='{x['id']}'>{esc(x['name'])}</option>" for x in accounts)
    form = f"""<div class=card><h1>إنشاء ملف سابر</h1><form method=post action=/saber><input type=hidden name=csrf value='{esc(current['csrf'])}'><div class=grid><select name=shipment_id>{ship_opts}</select><select name=account_id>{account_opts}</select><input name=case_reference required placeholder='مرجع داخلي مثل SAB-2026-001'><select name=submission_type><option value=shipment_certificate>شهادة إرسالية</option><option value=product_certificate>شهادة مطابقة منتج</option><option value=both>الاثنتان</option></select><input name=due_at type=date></div><textarea name=notes placeholder='ملاحظات أولية'></textarea><button>إنشاء ملف التجهيز</button></form></div>"""
    return HTMLResponse(page("طلب سابر جديد", nav() + form))


@router.post("/saber")
async def create_case(request: Request):
    current = auth(request); data = parse(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    reference = re.sub(r"\s+", "-", data.get("case_reference", "").strip().upper())
    if len(reference) < 4: raise HTTPException(400, "المرجع قصير")
    now = utcnow(); shipment_id = int(data["shipment_id"]) if data.get("shipment_id") else None; account_id = int(data["account_id"]) if data.get("account_id") else None
    account = one("SELECT * FROM accounts WHERE id=?", (account_id,)) if account_id else None
    try:
        case_id = execute("""INSERT INTO saber_cases(case_reference,shipment_id,account_id,importer_name,submission_type,status,notes,due_at,created_by,created_at,updated_at) VALUES(?,?,?,?,?,'draft',?,?,?,?,?)""", (reference, shipment_id, account_id, account.get("name") if account else "", data.get("submission_type"), data.get("notes"), data.get("due_at") or now + datetime.timedelta(days=3), current["user_id"], now, now))
    except Exception: raise HTTPException(409, "مرجع الطلب مستخدم مسبقًا")
    log(current["user_id"], "saber_case_created", "saber_case", case_id, reference)
    return RedirectResponse(f"/saber/{case_id}", 303)


@router.get("/saber/{case_id}", response_class=HTMLResponse)
def case_detail(case_id: int, request: Request):
    current = auth(request); case, products, missing = readiness(case_id)
    if not case: raise HTTPException(404)
    docs = rows("SELECT id,document_type,filename,file_size,extraction_status,created_at FROM saber_documents WHERE case_id=? ORDER BY id DESC", (case_id,)); follows = rows("SELECT * FROM saber_followups WHERE case_id=? ORDER BY due_at", (case_id,))
    ready = not missing; checklist = "".join(f"<li class=bad>{esc(x)}</li>" for x in missing) if missing else "<li class=good>ملف التجهيز مكتمل وجاهز لطلب الاعتماد.</li>"
    product_rows = "".join(f"<tr><td>{esc(x['description'])}</td><td>{esc(x['hs_code'])}</td><td>{esc(x['brand'])}</td><td>{esc(x['model'])}</td><td>{esc(x['quantity'])} {esc(x['unit'])}</td><td>{esc(x['conformity_status'])}</td></tr>" for x in products)
    doc_rows = "".join(f"<tr><td>{esc(x['document_type'])}</td><td>{esc(x['filename'])}</td><td>{round(x['file_size']/1024)} KB</td><td>{esc(x['extraction_status'])}</td></tr>" for x in docs)
    follow_rows = "".join(f"<tr><td>{esc(x['title'])}</td><td>{esc(x['due_at'])}</td><td>{esc(x['status'])}</td></tr>" for x in follows)
    edit = f"""<div class=card><h2>بيانات الطلب</h2><form method=post action='/saber/{case_id}/update'><input type=hidden name=csrf value='{esc(current['csrf'])}'><div class=grid><input name=importer_name required placeholder='اسم المستورد' value='{esc(case.get('importer_name'))}'><input name=commercial_registration required placeholder='السجل التجاري' value='{esc(case.get('commercial_registration'))}'><input name=invoice_number required placeholder='رقم الفاتورة' value='{esc(case.get('invoice_number'))}'><input name=invoice_date type=date required value='{esc(case.get('invoice_date'))}'><input name=country_of_origin required placeholder='بلد المنشأ' value='{esc(case.get('country_of_origin'))}'><input name=supplier_name required placeholder='اسم المورد' value='{esc(case.get('supplier_name'))}'><select name=regulatory_route><option value=unknown {'selected' if case['regulatory_route']=='unknown' else ''}>يحتاج مراجعة مختص</option><option value=regulated {'selected' if case['regulatory_route']=='regulated' else ''}>خاضع للائحة فنية</option><option value=unregulated {'selected' if case['regulatory_route']=='unregulated' else ''}>غير خاضع للائحة فنية</option></select></div><textarea name=notes>{esc(case.get('notes'))}</textarea><button>حفظ بيانات الطلب</button></form></div>"""
    upload = f"""<div class=card><h2>رفع المستندات والاستخراج الآلي</h2><form method=post action='/saber/{case_id}/documents' enctype=multipart/form-data><input type=hidden name=csrf value='{esc(current['csrf'])}'><select name=document_type><option value=commercial_invoice>الفاتورة التجارية</option><option value=bill_of_lading>بوليصة الشحن</option><option value=certificate_of_origin>شهادة المنشأ</option><option value=product_certificate>شهادة المنتج</option><option value=test_report>تقرير اختبار</option><option value=other>مستند آخر</option></select><input type=file name=file accept='image/jpeg,image/png,image/webp,application/pdf' required><button>رفع واستخراج البيانات</button></form><table><tr><th>النوع</th><th>الملف</th><th>الحجم</th><th>الاستخراج</th></tr>{doc_rows or '<tr><td colspan=4>لا توجد مستندات.</td></tr>'}</table></div>"""
    product_form = f"""<div class=card><h2>المنتجات والبنود</h2><form method=post action='/saber/{case_id}/products'><input type=hidden name=csrf value='{esc(current['csrf'])}'><div class=grid><input name=description required placeholder='وصف المنتج'><input name=hs_code required placeholder='رمز HS من 6 إلى 12 رقمًا'><input name=brand placeholder='العلامة'><input name=model placeholder='الموديل'><input name=manufacturer placeholder='المصنع'><input name=quantity type=number min=.001 step=.001 placeholder='الكمية'><input name=unit placeholder='الوحدة'><select name=conformity_status><option value=needs_review>يحتاج مراجعة</option><option value=product_certificate_ready>شهادة المنتج جاهزة</option><option value=not_required>غير مطلوبة بقرار المختص</option></select></div><button>إضافة المنتج</button></form><table><tr><th>المنتج</th><th>HS</th><th>العلامة</th><th>الموديل</th><th>الكمية</th><th>المطابقة</th></tr>{product_rows or '<tr><td colspan=6>لا توجد منتجات.</td></tr>'}</table></div>"""
    approval = ""
    if case["status"] == "draft": approval = f"<form method=post action='/saber/{case_id}/request-approval'><input type=hidden name=csrf value='{esc(current['csrf'])}'><button {'disabled' if not ready else ''}>طلب اعتماد التقديم النهائي</button></form>"
    elif case["status"] == "pending_approval" and current.get("role") == "admin": approval = f"<form method=post action='/saber/{case_id}/approve'><input type=hidden name=csrf value='{esc(current['csrf'])}'><button>اعتماد الملف للتقديم في سابر</button></form>"
    elif case["status"] == "approved": approval = f"""<form method=post action='/saber/{case_id}/submitted'><input type=hidden name=csrf value='{esc(current['csrf'])}'><input name=saber_request_number required placeholder='رقم الطلب الصادر من منصة سابر'><button>تسجيل أنه تم التقديم رسميًا</button></form>"""
    elif case["status"] in ("submitted", "under_review"): approval = f"""<form method=post action='/saber/{case_id}/issued'><input type=hidden name=csrf value='{esc(current['csrf'])}'><input name=certificate_number required placeholder='رقم الشهادة'><input name=certificate_url placeholder='رابط الشهادة إن وجد'><button>تسجيل صدور الشهادة</button></form>"""
    body = nav() + f"<h1>{esc(case['case_reference'])}</h1><div class=grid><div class=kpi>الحالة<b>{esc(case['status'])}</b></div><div class=kpi>نوع الطلب<b>{esc(case['submission_type'])}</b></div><div class=kpi>رقم طلب سابر<b>{esc(case.get('saber_request_number') or '-')}</b></div><div class=kpi>الشهادة<b>{esc(case.get('certificate_number') or '-')}</b></div></div><div class=card><h2>فحص الجاهزية</h2><ul>{checklist}</ul>{approval}</div>{edit}{upload}{product_form}<div class=card><h2>المتابعات</h2><table><tr><th>المهمة</th><th>الاستحقاق</th><th>الحالة</th></tr>{follow_rows or '<tr><td colspan=3>لا توجد متابعات.</td></tr>'}</table></div>"
    return HTMLResponse(page(case["case_reference"], body))


@router.post("/saber/{case_id}/update")
async def update_case(case_id: int, request: Request):
    current = auth(request); data = parse(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    if not one("SELECT id FROM saber_cases WHERE id=?", (case_id,)): raise HTTPException(404)
    execute("""UPDATE saber_cases SET importer_name=?,commercial_registration=?,invoice_number=?,invoice_date=?,country_of_origin=?,supplier_name=?,regulatory_route=?,notes=?,updated_at=? WHERE id=?""", (data.get("importer_name"), data.get("commercial_registration"), data.get("invoice_number"), data.get("invoice_date") or None, data.get("country_of_origin"), data.get("supplier_name"), data.get("regulatory_route"), data.get("notes"), utcnow(), case_id))
    log(current["user_id"], "saber_case_updated", "saber_case", case_id, "Preparation data updated")
    return RedirectResponse(f"/saber/{case_id}", 303)


def extract_invoice_fields(text):
    upper = re.sub(r"[ \t]+", " ", text.upper())
    def first(patterns):
        for pattern in patterns:
            match = re.search(pattern, upper, re.I)
            if match: return match.group(1).strip(" :#.-")
        return ""
    invoice = first([r"(?:COMMERCIAL\s+)?INVOICE\s*(?:NO\.?|NUMBER|#)\s*[:#.-]?\s*([A-Z0-9/-]{3,40})", r"INV(?:OICE)?\s*#\s*([A-Z0-9/-]{3,40})"])
    date = first([r"INVOICE\s+DATE\s*[:#.-]?\s*(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4})"])
    origin = first([r"COUNTRY\s+OF\s+ORIGIN\s*[:#.-]?\s*([A-Z][A-Z ]{2,40})"])
    hs_codes = sorted(set(re.findall(r"\b\d{6,12}\b", upper)))
    return invoice, date, origin.title(), hs_codes[:30]


def normalized_date(value):
    match = re.fullmatch(r"(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})", value or "")
    if not match: return None
    a, b, c = (int(x) for x in match.groups())
    year, month, day = (a, b, c) if a > 1900 else (c, b, a)
    try: return datetime.date(year, month, day)
    except ValueError: return None


@router.post("/saber/{case_id}/documents")
async def upload_document(request: Request, case_id: int, csrf: str = Form(...), document_type: str = Form(...), file: UploadFile = File(...)):
    current = auth(request)
    if csrf != current["csrf"]: raise HTTPException(403)
    if not one("SELECT id FROM saber_cases WHERE id=?", (case_id,)): raise HTTPException(404)
    allowed = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}; media = (file.content_type or "").lower()
    if media not in allowed: raise HTTPException(400, "ارفع PDF أو صورة JPG/PNG/WEBP")
    content = await file.read(10 * 1024 * 1024 + 1)
    if not content or len(content) > 10 * 1024 * 1024: raise HTTPException(400, "الحد الأقصى 10 MB")
    signatures = {"application/pdf": content.startswith(b"%PDF-"), "image/jpeg": content.startswith(b"\xff\xd8\xff"), "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"), "image/webp": len(content)>12 and content[:4]==b"RIFF" and content[8:12]==b"WEBP"}
    if not signatures.get(media): raise HTTPException(400, "محتوى الملف لا يطابق نوعه")
    with tempfile.TemporaryDirectory(prefix="saber-doc-") as tmp:
        path = Path(tmp) / ("document" + allowed[media]); path.write_bytes(content)
        try: text = extract_document_text(path, media)
        except (subprocess.TimeoutExpired, RuntimeError) as exc: raise HTTPException(422, str(exc))
    now = utcnow(); did = execute("""INSERT INTO saber_documents(case_id,document_type,filename,media_type,file_size,file_sha256,content,extracted_text,extraction_status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (case_id, document_type, (file.filename or "document")[:240], media, len(content), hashlib.sha256(content).hexdigest(), content, text[:50000], "processed", current["user_id"], now))
    invoice, date, origin, hs_codes = extract_invoice_fields(text)
    if document_type == "commercial_invoice":
        execute("""UPDATE saber_cases SET invoice_number=COALESCE(NULLIF(invoice_number,''),?),invoice_date=COALESCE(invoice_date,?),country_of_origin=COALESCE(NULLIF(country_of_origin,''),?),updated_at=? WHERE id=?""", (invoice, normalized_date(date), origin, now, case_id))
        for hs in hs_codes:
            if not one("SELECT id FROM saber_products WHERE case_id=? AND hs_code=?", (case_id, hs)):
                execute("""INSERT INTO saber_products(case_id,description,hs_code,country_of_origin,conformity_status,notes,created_at,updated_at) VALUES(?,?,?,?,'needs_review',?,?,?)""", (case_id, "منتج مستخرج من الفاتورة - راجع الوصف", hs, origin, "استخراج آلي يحتاج مراجعة مختص", now, now))
    log(current["user_id"], "saber_document_processed", "saber_document", did, f"{document_type}; extracted {len(text)} chars")
    return RedirectResponse(f"/saber/{case_id}", 303)


@router.post("/saber/{case_id}/products")
async def add_product(case_id: int, request: Request):
    current = auth(request); data = parse(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    hs = re.sub(r"\D", "", data.get("hs_code", ""))
    if not re.fullmatch(r"\d{6,12}", hs): raise HTTPException(400, "رمز HS يجب أن يكون من 6 إلى 12 رقمًا")
    now = utcnow(); pid = execute("""INSERT INTO saber_products(case_id,description,hs_code,brand,model,manufacturer,quantity,unit,country_of_origin,conformity_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (case_id, data.get("description"), hs, data.get("brand"), data.get("model"), data.get("manufacturer"), float(data["quantity"]) if data.get("quantity") else None, data.get("unit"), data.get("country_of_origin"), data.get("conformity_status"), now, now))
    log(current["user_id"], "saber_product_added", "saber_product", pid, hs)
    return RedirectResponse(f"/saber/{case_id}", 303)


@router.post("/saber/{case_id}/request-approval")
async def request_approval(case_id: int, request: Request):
    current = auth(request); data = parse(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    case, products, missing = readiness(case_id)
    if missing: raise HTTPException(409, "الملف غير مكتمل: " + "، ".join(missing))
    if case["status"] != "draft": raise HTTPException(409)
    aid = execute("INSERT INTO approvals(kind,entity_type,entity_id,status,requested_by,notes,created_at) VALUES(?,?,?,?,?,?,?)", ("saber_submission", "saber_case", case_id, "pending", current["user_id"], "اعتماد دقة بيانات الطلب والبنود والمستندات قبل التقديم الرسمي في سابر", utcnow()))
    execute("UPDATE saber_cases SET status='pending_approval',approval_id=?,updated_at=? WHERE id=?", (aid, utcnow(), case_id))
    return RedirectResponse(f"/saber/{case_id}", 303)


@router.post("/saber/{case_id}/approve")
async def approve_case(case_id: int, request: Request):
    current = auth(request); data = parse(await request.body())
    if data.get("csrf") != current["csrf"] or current.get("role") != "admin": raise HTTPException(403)
    case = one("SELECT * FROM saber_cases WHERE id=?", (case_id,))
    if not case or case["status"] != "pending_approval": raise HTTPException(409)
    now = utcnow(); execute("UPDATE approvals SET status='approved',decided_by=?,decided_at=? WHERE id=?", (current["user_id"], now, case["approval_id"])); execute("UPDATE saber_cases SET status='approved',updated_at=? WHERE id=?", (now, case_id))
    log(current["user_id"], "saber_case_approved", "saber_case", case_id, "Approved for authorized manual submission")
    return RedirectResponse(f"/saber/{case_id}", 303)


@router.post("/saber/{case_id}/submitted")
async def mark_submitted(case_id: int, request: Request):
    current = auth(request); data = parse(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    case = one("SELECT * FROM saber_cases WHERE id=?", (case_id,))
    if not case or case["status"] != "approved": raise HTTPException(409, "يلزم الاعتماد أولًا")
    number = data.get("saber_request_number", "").strip()
    if len(number) < 4: raise HTTPException(400, "أدخل رقم طلب سابر")
    now = utcnow(); execute("UPDATE saber_cases SET status='submitted',saber_request_number=?,submitted_at=?,updated_at=? WHERE id=?", (number, now, now, case_id)); execute("INSERT INTO saber_followups(case_id,kind,title,status,due_at,notes,created_at,updated_at) VALUES(?,?,?,'open',?,?,?,?)", (case_id, "saber_status", "متابعة حالة الطلب في منصة سابر", now + datetime.timedelta(days=1), number, now, now))
    log(current["user_id"], "saber_case_submitted_recorded", "saber_case", case_id, number)
    return RedirectResponse(f"/saber/{case_id}", 303)


@router.post("/saber/{case_id}/issued")
async def mark_issued(case_id: int, request: Request):
    current = auth(request); data = parse(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    case = one("SELECT * FROM saber_cases WHERE id=?", (case_id,))
    if not case or case["status"] not in ("submitted", "under_review"): raise HTTPException(409)
    number = data.get("certificate_number", "").strip()
    if len(number) < 4: raise HTTPException(400, "أدخل رقم الشهادة")
    now = utcnow(); execute("UPDATE saber_cases SET status='issued',certificate_number=?,certificate_url=?,issued_at=?,updated_at=? WHERE id=?", (number, data.get("certificate_url"), now, now, case_id)); execute("UPDATE saber_followups SET status='closed',updated_at=? WHERE case_id=? AND status='open'", (now, case_id))
    log(current["user_id"], "saber_certificate_issued", "saber_case", case_id, number)
    return RedirectResponse(f"/saber/{case_id}", 303)


@router.get("/api/v7/saber")
def saber_api(request: Request):
    auth(request); return {"cases": rows("SELECT * FROM saber_cases ORDER BY id DESC"), "policy": {"official_submission": "authorized_user_only", "human_approval_required": True}}
