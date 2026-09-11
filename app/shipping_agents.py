import datetime
import html
import os
import urllib.parse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.gmail_oauth import connection, send_gmail
from app.storage import db, execute, get_session, log, one, rows, utcnow


router = APIRouter()
SOURCE = "إيميلات وكلاء جدة محدثه - 2026-04-16.pdf"


AGENTS = [
    ("ONE Line", "https://www.one-line.com/en", [("D/O & invoice", "impcsv.jed@haaco.com", ""), ("Detention", "cntrcontrol@haaco.com", "")]),
    ("FOLK & ASYAD", "", [("General", "hcs@haaco.com", "0564821469")]),
    ("COSCO Line", "", [("Invoice & D/O", "coscojedimport@coscon.com", "0126472237"), ("Invoice & D/O", "alghaal@coscon.com", ""), ("Invoice & D/O", "alrehkh@coscon.com", ""), ("Dammam Import", "cosdmmimport@coscon.com", ""), ("Detention", "coscoksadet@coscon.com", "")]),
    ("Emarat Line", "", [("Operations", "a.naqi@globeksa.com", "")]),
    ("FMC", "", [("Customer service", "jedcsr@fmc-glo.com", "0532704085"), ("General", "saudi@fmc-glo.com", ""), ("Documents", "jeddoc@fmc-glo.com", ""), ("Contact - Irfan", "irfan@fmc-glo.com", "")]),
    ("GAC - Al Ghaleej Al Qusaibi", "", [("Operations", "shahul.haj@gac.com", "0506357500"), ("Operations", "abubakar.asqhar@gac.com", ""), ("Operations", "hassan.saleh@gac.com", "")]),
    ("Al Barak Line", "", [("Equipment", "eqc2.jed@smclogistic.com", ""), ("Operations", "nazeer.jed@smclogistic.com", ""), ("Operations", "opr6.jed@smclogistic.com", "")]),
    ("OOCL Line", "", [("eD/O", "eDO-JED@oocl.com", "")]),
    ("Hapag-Lloyd", "https://online.odexglobal.com/", [("D/O", "saudiarabia@service.hlag.com", "0115102716")]),
    ("FOLK Maritime", "", [("Import", "sa.import@folkmaritime.com", "0596464196"), ("Export", "sa.export@folkmaritime.com", "0596464196")]),
    ("International Link", "", [("Operations", "operations@international-link.com", "")]),
    ("Emirates Line", "", [("Customer support", "customersupport@globeksa.com", ""), ("Contact - Mohamed Hanifa", "mmglad@emiratesline.com.sa", ""), ("Operations", "ops-esl@emiratesline.com.sa", ""), ("Contact - Ali Hilal", "a.ahmed@globeksa.com", ""), ("D/O", "imports@emiratesline.com.sa", "")]),
    ("Pride Shipping Co. Ltd", "", [("EDI", "edi@pridejeddah.com", "+966560594662"), ("Cashier", "cashier@pridejeddah.com", ""), ("Documents", "docs@pridejeddah.com", ""), ("Customer service", "cs@pridejeddah.com", ""), ("Import", "tsl.imp@pridejeddah.com", ""), ("Documents", "tsl.doc@pridejeddah.com", ""), ("Operations", "mohan@pridejeddah.com", ""), ("Supervisor", "tsl.sup@pridejeddah.com", ""), ("Contact - Irfan", "irfan@pridejeddah.com", "")]),
    ("PIL", "", [("Invoice", "PILSA.INV@sau.pilship.com", ""), ("D/O", "PILSA.DO@sau.pilship.com", ""), ("Operations", "ali.alhirani@sau.pilship.com", ""), ("Operations", "ahmed.mubarak@sau.pilship.com", ""), ("Operations", "habeeb.maqdoud@sau.pilship.com", ""), ("Operations", "mohd.ekhwan@sau.pilship.com", ""), ("Operations", "abdullah.aldamin@sau.pilship.com", ""), ("Operations", "hani.almarshood@sau.pilship.com", "")]),
    ("Maersk Line", "https://www.maersk.com", [("Detention", "JEDDAH.DECOUNTER@maersk.com", ""), ("D/O", "sa.import@maersk.com", "")]),
    ("ONE Hi / WWS", "", [("Invoice", "a.mohideen@wwsksa.com", ""), ("Operations", "a.sharef@wwsksa.com", ""), ("Advice", "advice-jed@wwsksa.com", ""), ("D/O", "t.ahmed@globeksa.com", ""), ("Extension", "conseils-jed@wwsksa.com", "")]),
    ("ILPA - Cordelia NVOCC", "", [("Import", "jedimp@ilparabia.com", "+966555578027"), ("Operations", "a.raed@ilparabia.com", ""), ("Operations", "aragab@marsa-ss.com", "+966503067258"), ("Contact", "Y.Mohamed@ilpegypt.com", "")]),
    ("Kanoo Line", "", [("Operations", "netra.thapa@kanoo.com", ""), ("Operations", "abdulaziz.alaslani@kanoo.com", "")]),
    ("DSV / Panalpina", "", [("General", "info.saudiarabia@panalpina.com", ""), ("Operations", "akareem@dsv.com", "")]),
    ("Globe Marine", "", [("Operations", "amerk@globeksa.com", ""), ("Operations", "r.qazi@globeksa.com", ""), ("Operations", "a.naqi@globeksa.com", "")]),
    ("ECU Worldwide", "", [("Operations", "Imran.Butt@ecuworldwide.com", ""), ("Operations", "AbdulSamad2@ecuworldwide.com", ""), ("Operations", "Salems@ecuworldwide.com", "")]),
    ("SeaLead Line", "", [("D/O", "csdimpjed@sea-lead.com", ""), ("Arrival & invoice", "invoicejed@sea-lead.com", ""), ("Container updates", "ahmed.lari@sea-lead.com", "")]),
    ("Munawla Cargo Co", "", [("Operations", "adilsultan@munawlacargo.com.sa", "0504826796"), ("Operations", "ameen@munawlacargo.com.sa", "0502034511 / 0504265683")]),
    ("CMA CGM", "https://mycustomerservice.cma-cgm.com/", []),
    ("MSC", "", [("Customer service", "SAU-ex-cs.localwest@msc.com", "")]),
    ("SMC Logistics / Al Bahri", "", [("Operations", "opr6.jed@smclogistic.com", ""), ("Operations", "opr1.jed@smclogistic.com", ""), ("Import", "imp1.jed@smclogistic.com", ""), ("Manifest", "mfst1.jed@absaco.com", "")]),
    ("DB Schenker", "", [("Invoice", "sa.dl.jed.saairimppa@dbschenker.com", ""), ("LCL Import", "sa.dl.jed.ocean.lcl.import@dbschenker.com", "")]),
    ("Globe Link", "", [("D/O & invoice", "deliveryorder.jed@glweststarsaudi.com", ""), ("Operations", "hamid.ali@glweststarsaudi.com", "")]),
    ("TWC Team", "", [("Invoice", "Accounts2.jed@twc.sa.com", ""), ("Invoice", "Accounts3.jed@twc.sa.com", ""), ("D/O", "Exp1.jed@twc.sa.com", ""), ("D/O", "Imports.jed@twc.sa.com", ""), ("D/O", "Do.jed@twc.sa.com", "")]),
    ("Trident Freight", "", [("Invoice", "IMPJED@trident-freight.com", ""), ("Documents", "doc2jed@trident-freight.com", ""), ("Operations", "marwan@trident-freight.com", ""), ("Extension", "sreekumar.g@trident-freight.com", "")]),
    ("DHL", "", [("Operations", "wajd.althobaiti@dhl.com", "")]),
    ("Amass / Future Network", "", [("Import documents", "impdoc1.sa@dxb.amassfreight.com", ""), ("Operations", "navil.sa@dxb.amassfreight.com", "")]),
    ("Sharaf Shipping Agency", "", [("Invoice", "invdesk@ssajeddah.com", ""), ("Operations", "mariah@ssajeddah.com", ""), ("Operations", "ops3@ssajeddah.com", ""), ("D/O", "dodesk@ssajeddah.com", ""), ("Equipment", "eqc01@ssajeddah.com", "")]),
    ("Macnels", "", [("Operations", "muhammed@macnelsksa.com", ""), ("Operations", "sanju@macnelsksa.com", ""), ("Operations", "thoufeeq@macnelsksa.com", ""), ("Operations", "vishnu@macnelsksa.com", ""), ("Operations", "anaz@macnelsksa.com", ""), ("Operations", "rishan@macnelsksa.com", "")]),
    ("UTC / الفنية", "", [("Invoice", "invoice@utc.com.sa", ""), ("D/O", "b.dossary@globeksa.com", ""), ("Empty return", "Akiburrahman.b@globeksa.com", "")]),
    ("Gevo Maritime / الجزائرية", "", [("Operations", "mchengoden@gevomaritime.com", "+966125810244"), ("Operations", "malharbi@gevomaritime.com", ""), ("Customer service", "sa.cs@gevomaritime.com", "")]),
    ("Messina Line / التكامل", "", [("General", "info@messinaline.com.sa", ""), ("Operations", "yohannes@messinaline.com.sa", ""), ("Credit recovery", "Jed.creditrecoverol@messinaline.com.sa", "")]),
    ("Goodrich", "", [("Operations", "goodrich.jed@goodricharabia.com", "")]),
    ("Evergreen", "", [("Operations", "areej.alnashri@evergreen-shipping.com.sa", ""), ("Operations", "aminah.abdullah@evergreen-shipping.com.sa", ""), ("Operations", "fahad.almoulad@evergreen-shipping.com.sa", ""), ("Operations", "haitham.altayeb@evergreen-shipping.com.sa", "")]),
]


def init_storage():
    statements = [
        """CREATE TABLE IF NOT EXISTS shipping_agents(id BIGSERIAL PRIMARY KEY,name TEXT UNIQUE NOT NULL,country TEXT NOT NULL DEFAULT 'السعودية',city TEXT NOT NULL DEFAULT 'جدة',port TEXT NOT NULL DEFAULT 'ميناء جدة الإسلامي',website TEXT,status TEXT NOT NULL DEFAULT 'active',source TEXT,notes TEXT,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS shipping_agent_contacts(id BIGSERIAL PRIMARY KEY,agent_id BIGINT NOT NULL REFERENCES shipping_agents(id) ON DELETE CASCADE,purpose TEXT NOT NULL,email TEXT,phone TEXT,contact_name TEXT,is_verified INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'active',created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,UNIQUE(agent_id,email,purpose))""",
        """CREATE TABLE IF NOT EXISTS shipping_agent_cases(id BIGSERIAL PRIMARY KEY,agent_id BIGINT NOT NULL REFERENCES shipping_agents(id),shipment_id BIGINT REFERENCES shipments(id) ON DELETE SET NULL,case_type TEXT NOT NULL,reference TEXT,subject TEXT,details TEXT,status TEXT NOT NULL DEFAULT 'new',due_at TIMESTAMPTZ,created_by BIGINT REFERENCES users(id),created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS shipping_agent_messages(id BIGSERIAL PRIMARY KEY,case_id BIGINT NOT NULL REFERENCES shipping_agent_cases(id) ON DELETE CASCADE,contact_id BIGINT REFERENCES shipping_agent_contacts(id) ON DELETE SET NULL,recipient TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',approval_id BIGINT REFERENCES approvals(id) ON DELETE SET NULL,provider_message_id TEXT,last_error TEXT,created_by BIGINT REFERENCES users(id),approved_by BIGINT REFERENCES users(id),approved_at TIMESTAMPTZ,sent_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)""",
    ]
    now = utcnow()
    with db() as c:
        for statement in statements:
            c.execute(statement)
        for name, website, contacts in AGENTS:
            agent = c.execute("""INSERT INTO shipping_agents(name,website,source,created_at,updated_at) VALUES(%s,%s,%s,%s,%s)
                ON CONFLICT(name) DO UPDATE SET website=COALESCE(NULLIF(EXCLUDED.website,''),shipping_agents.website),source=EXCLUDED.source,updated_at=EXCLUDED.updated_at RETURNING id""",
                (name, website, SOURCE, now, now)).fetchone()
            for purpose, email, phone in contacts:
                c.execute("""INSERT INTO shipping_agent_contacts(agent_id,purpose,email,phone,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(agent_id,email,purpose) DO UPDATE SET phone=COALESCE(NULLIF(EXCLUDED.phone,''),shipping_agent_contacts.phone),updated_at=EXCLUDED.updated_at""",
                    (agent["id"], purpose, email.lower().replace(" ", ""), phone, now, now))


init_storage()


def esc(value): return html.escape(str(value or ""))
def parse(raw): return {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode(), keep_blank_values=True).items()}
def auth(request):
    session = get_session(request.cookies.get("gla_session"))
    if not session: raise HTTPException(401, "Login required")
    return session


def page(title, body):
    return f"""<!doctype html><html lang=ar dir=rtl><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{esc(title)}</title><style>
    body{{font-family:Arial;background:#07131f;color:#eef6fb;margin:0;padding:24px}}a{{color:#86efac}}.wrap{{max-width:1250px;margin:auto}}.card{{background:#102536;padding:20px;margin:14px 0;border-radius:16px;overflow:auto}}.nav{{display:flex;gap:8px;flex-wrap:wrap}}.btn,button{{display:inline-block;background:#ff7900;color:white;border:0;border-radius:9px;padding:11px 14px;text-decoration:none;font-weight:bold;cursor:pointer}}input,select,textarea{{width:100%;box-sizing:border-box;padding:11px;margin:6px 0;border:1px solid #36586e;border-radius:8px;background:#081925;color:white}}textarea{{min-height:130px}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:right;padding:10px;border-bottom:1px solid #28475d;vertical-align:top}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}}.kpi{{background:#0b1d2b;padding:16px;border-radius:12px}}.kpi b{{font-size:25px;display:block}}.muted{{color:#9fb4c4}}.warn{{color:#fde68a}}.good{{color:#86efac}}.danger{{background:#ef4444}}</style><div class=wrap>{body}</div></html>"""


def nav(): return "<div class=nav><a class=btn href=/dashboard>الرئيسية</a><a class=btn href=/shipping-agents>وكلاء الملاحة</a><a class=btn href=/shipments>الشحنات</a><a class=btn href=/settings/email>إعداد البريد</a></div>"


@router.get("/shipping-agents", response_class=HTMLResponse)
def agents_home(request: Request, q: str = ""):
    auth(request); term = "%" + q.strip() + "%"
    agents = rows("""SELECT a.*,COUNT(DISTINCT c.id) contacts,COUNT(DISTINCT x.id) cases
        FROM shipping_agents a LEFT JOIN shipping_agent_contacts c ON c.agent_id=a.id LEFT JOIN shipping_agent_cases x ON x.agent_id=a.id
        WHERE a.name ILIKE %s OR COALESCE(c.email,'') ILIKE %s GROUP BY a.id ORDER BY a.name""", (term, term))
    totals = one("SELECT COUNT(*) agents,(SELECT COUNT(*) FROM shipping_agent_contacts) contacts,(SELECT COUNT(*) FROM shipping_agent_cases WHERE status NOT IN ('closed','cancelled')) open_cases FROM shipping_agents")
    table = "".join(f"<tr><td><a href='/shipping-agents/{x['id']}'>{esc(x['name'])}</a></td><td>{esc(x['port'])}</td><td>{x['contacts']}</td><td>{x['cases']}</td><td>{esc(x['status'])}</td></tr>" for x in agents)
    body = nav() + "<h1>وكلاء الملاحة - ميناء جدة</h1><p class=muted>دليل تشغيلي مستورد من الملف المحدث. لا يتم أي إرسال دون اعتماد بشري.</p>" + f"<div class=grid><div class=kpi>الوكلاء<b>{totals['agents']}</b></div><div class=kpi>جهات الاتصال<b>{totals['contacts']}</b></div><div class=kpi>المعاملات المفتوحة<b>{totals['open_cases']}</b></div></div><div class=card><form><input name=q value='{esc(q)}' placeholder='ابحث باسم الوكيل أو البريد'><button>بحث</button></form></div><div class=card><table><tr><th>الوكيل</th><th>الميناء</th><th>جهات الاتصال</th><th>المعاملات</th><th>الحالة</th></tr>{table}</table></div>"
    return HTMLResponse(page("وكلاء الملاحة", body))


@router.get("/shipping-agents/{agent_id}", response_class=HTMLResponse)
def agent_detail(agent_id: int, request: Request):
    current = auth(request); agent = one("SELECT * FROM shipping_agents WHERE id=?", (agent_id,))
    if not agent: raise HTTPException(404)
    contacts = rows("SELECT * FROM shipping_agent_contacts WHERE agent_id=? ORDER BY purpose,email", (agent_id,))
    cases = rows("""SELECT x.*,s.reference shipment_reference FROM shipping_agent_cases x LEFT JOIN shipments s ON s.id=x.shipment_id
        WHERE x.agent_id=? ORDER BY x.id DESC""", (agent_id,))
    shipments = rows("SELECT id,reference,origin,destination FROM shipments ORDER BY id DESC LIMIT 300")
    contact_rows = "".join(f"<tr><td>{esc(x['purpose'])}</td><td dir=ltr>{esc(x['email'])}</td><td dir=ltr>{esc(x['phone'])}</td><td>{'موثق' if x['is_verified'] else 'من الملف - يحتاج تحقق عند الاستخدام'}</td></tr>" for x in contacts)
    case_rows = "".join(f"<tr><td><a href='/shipping-agent-cases/{x['id']}'>{esc(x['reference'] or ('CASE-'+str(x['id'])))}</a></td><td>{esc(x['case_type'])}</td><td>{esc(x.get('shipment_reference'))}</td><td>{esc(x['status'])}</td><td>{esc(x['due_at'])}</td></tr>" for x in cases)
    ship_opts = "<option value=''>بدون ربط بشحنة</option>" + "".join(f"<option value='{x['id']}'>{esc(x['reference'])} - {esc(x['origin'])} إلى {esc(x['destination'])}</option>" for x in shipments)
    form = f"""<div class=card><h2>إنشاء معاملة جديدة</h2><form method=post action='/shipping-agents/{agent_id}/cases'><input type=hidden name=csrf value='{esc(current['csrf'])}'><div class=grid><select name=shipment_id>{ship_opts}</select><select name=case_type><option>إذن تسليم</option><option>فاتورة</option><option>غرامات وتأخير</option><option>إعادة حاوية فارغة</option><option>تحديث وصول</option><option>مستندات استيراد</option><option>مستندات تصدير</option><option>طلب عام</option></select><input name=reference placeholder='مرجع المعاملة أو البوليصة' required><input name=due_at type=datetime-local></div><input name=subject placeholder='عنوان الطلب' required><textarea name=details placeholder='التفاصيل والمستندات المطلوبة' required></textarea><button>إنشاء المعاملة وتجهيز المراسلة</button></form></div>"""
    body = nav() + f"<h1>{esc(agent['name'])}</h1><p>{esc(agent['port'])} | <a href='{esc(agent['website'])}' target=_blank>{esc(agent['website'])}</a></p><div class=card><h2>جهات الاتصال المصنفة</h2><table><tr><th>الغرض</th><th>البريد</th><th>الهاتف</th><th>التحقق</th></tr>{contact_rows or '<tr><td colspan=4>لا يوجد بريد في الملف؛ استخدم الموقع.</td></tr>'}</table></div>{form}<div class=card><h2>سجل المعاملات</h2><table><tr><th>المرجع</th><th>النوع</th><th>الشحنة</th><th>الحالة</th><th>موعد المتابعة</th></tr>{case_rows or '<tr><td colspan=5>لا توجد معاملات.</td></tr>'}</table></div>"
    return HTMLResponse(page(agent["name"], body))


@router.post("/shipping-agents/{agent_id}/cases")
async def create_case(agent_id: int, request: Request):
    current = auth(request); data = parse(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    agent = one("SELECT * FROM shipping_agents WHERE id=?", (agent_id,))
    if not agent: raise HTTPException(404)
    shipment_id = int(data["shipment_id"]) if data.get("shipment_id") else None
    due = data.get("due_at") or (utcnow() + datetime.timedelta(days=2))
    now = utcnow(); cid = execute("""INSERT INTO shipping_agent_cases(agent_id,shipment_id,case_type,reference,subject,details,status,due_at,created_by,created_at,updated_at)
        VALUES(?,?,?,?,?,?,'draft',?,?,?,?)""", (agent_id, shipment_id, data.get("case_type"), data.get("reference"), data.get("subject"), data.get("details"), due, current["user_id"], now, now))
    log(current["user_id"], "shipping_agent_case_created", "shipping_agent_case", cid, agent["name"])
    return RedirectResponse(f"/shipping-agent-cases/{cid}", 303)


def recommended_purpose(case_type):
    return {"إذن تسليم": "D/O", "فاتورة": "Invoice", "غرامات وتأخير": "Detention", "إعادة حاوية فارغة": "Empty", "تحديث وصول": "Arrival", "مستندات استيراد": "Import", "مستندات تصدير": "Export"}.get(case_type, "")


@router.get("/shipping-agent-cases/{case_id}", response_class=HTMLResponse)
def case_detail(case_id: int, request: Request):
    current = auth(request); case = one("""SELECT x.*,a.name agent_name,s.reference shipment_reference,s.origin,s.destination
        FROM shipping_agent_cases x JOIN shipping_agents a ON a.id=x.agent_id LEFT JOIN shipments s ON s.id=x.shipment_id WHERE x.id=?""", (case_id,))
    if not case: raise HTTPException(404)
    contacts = rows("SELECT * FROM shipping_agent_contacts WHERE agent_id=? AND email IS NOT NULL ORDER BY purpose,email", (case["agent_id"],))
    messages = rows("SELECT * FROM shipping_agent_messages WHERE case_id=? ORDER BY id DESC", (case_id,))
    hint = recommended_purpose(case["case_type"])
    opts = "".join(f"<option value='{x['id']}' {'selected' if hint and hint.lower() in x['purpose'].lower() else ''}>{esc(x['purpose'])} - {esc(x['email'])}</option>" for x in contacts)
    create = f"""<div class=card><h2>تجهيز مسودة مراسلة</h2><p class=warn>راجع وظيفة البريد قبل الاختيار. النظام لا يرسل من هذه الخطوة.</p><form method=post action='/shipping-agent-cases/{case_id}/draft'><input type=hidden name=csrf value='{esc(current['csrf'])}'><select name=contact_id required>{opts}</select><button>إنشاء مسودة قابلة للمراجعة</button></form></div>""" if contacts else "<div class=card>لا يوجد بريد لهذا الوكيل في الملف. راجع موقعه وأضف جهة اتصال موثقة.</div>"
    msg_rows = "".join(f"<tr><td>{esc(x['recipient'])}</td><td>{esc(x['subject'])}</td><td>{esc(x['status'])}</td><td><a href='/shipping-agent-messages/{x['id']}'>فتح</a></td></tr>" for x in messages)
    body = nav() + f"<h1>معاملة {esc(case['reference'])}</h1><div class=card><b>الوكيل:</b> {esc(case['agent_name'])}<br><b>النوع:</b> {esc(case['case_type'])}<br><b>الشحنة:</b> {esc(case.get('shipment_reference'))} {esc(case.get('origin'))} ← {esc(case.get('destination'))}<br><b>الموضوع:</b> {esc(case['subject'])}<p>{esc(case['details'])}</p><b>الحالة:</b> {esc(case['status'])}</div>{create}<div class=card><h2>المراسلات</h2><table><tr><th>إلى</th><th>الموضوع</th><th>الحالة</th><th></th></tr>{msg_rows or '<tr><td colspan=4>لم تُنشأ مسودة بعد.</td></tr>'}</table></div>"
    return HTMLResponse(page("معاملة وكيل", body))


@router.post("/shipping-agent-cases/{case_id}/draft")
async def create_draft(case_id: int, request: Request):
    current = auth(request); data = parse(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    case = one("""SELECT x.*,a.name agent_name,s.reference shipment_reference,s.origin,s.destination FROM shipping_agent_cases x
        JOIN shipping_agents a ON a.id=x.agent_id LEFT JOIN shipments s ON s.id=x.shipment_id WHERE x.id=?""", (case_id,))
    contact = one("SELECT * FROM shipping_agent_contacts WHERE id=? AND agent_id=?", (int(data.get("contact_id") or 0), case["agent_id"] if case else 0))
    if not case or not contact or not contact.get("email"): raise HTTPException(400, "جهة الاتصال غير صالحة")
    subject = f"{case['case_type']} - {case['reference']} - آفاق طويق"
    route = f"\nالشحنة: {case.get('shipment_reference') or '-'}\nالمسار: {case.get('origin') or '-'} إلى {case.get('destination') or '-'}\n" if case.get("shipment_id") else ""
    body = f"""السادة/ {case['agent_name']} المحترمين،

تحية طيبة،
نرجو التكرم بمساعدتنا بخصوص {case['case_type']}، المرجع: {case['reference']}.{route}
التفاصيل:
{case['details']}

نرجو تأكيد الاستلام وإفادتنا بالإجراء المطلوب والمدة المتوقعة.

مع التحية،
آفاق طويق للتخليص الجمركي والنقل والخدمات اللوجستية"""
    now = utcnow(); mid = execute("""INSERT INTO shipping_agent_messages(case_id,contact_id,recipient,subject,body,status,created_by,created_at,updated_at)
        VALUES(?,?,?,?,?,'draft',?,?,?)""", (case_id, contact["id"], contact["email"], subject, body, current["user_id"], now, now))
    execute("UPDATE shipping_agent_cases SET status='draft',updated_at=? WHERE id=?", (now, case_id))
    log(current["user_id"], "shipping_agent_draft_created", "shipping_agent_message", mid, "Draft only; not sent")
    return RedirectResponse(f"/shipping-agent-messages/{mid}", 303)


@router.get("/shipping-agent-messages/{message_id}", response_class=HTMLResponse)
def message_detail(message_id: int, request: Request):
    current = auth(request); msg = one("""SELECT m.*,x.reference case_reference,a.name agent_name FROM shipping_agent_messages m
        JOIN shipping_agent_cases x ON x.id=m.case_id JOIN shipping_agents a ON a.id=x.agent_id WHERE m.id=?""", (message_id,))
    if not msg: raise HTTPException(404)
    if msg["status"] == "draft":
        action = f"""<form method=post action='/shipping-agent-messages/{message_id}/update'><input type=hidden name=csrf value='{esc(current['csrf'])}'><input name=recipient type=email required value='{esc(msg['recipient'])}'><input name=subject required value='{esc(msg['subject'])}'><textarea name=body required>{esc(msg['body'])}</textarea><button>حفظ التعديلات</button></form><form method=post action='/shipping-agent-messages/{message_id}/request-approval'><input type=hidden name=csrf value='{esc(current['csrf'])}'><button>طلب اعتماد الإرسال</button></form>"""
    elif msg["status"] == "pending_approval":
        action = "<p class=warn>بانتظار اعتماد الإدارة.</p>" + (f"<form method=post action='/shipping-agent-messages/{message_id}/approve'><input type=hidden name=csrf value='{esc(current['csrf'])}'><button>اعتماد الرسالة</button></form>" if current.get("role") == "admin" else "")
    elif msg["status"] == "approved":
        ready = connection(current["user_id"]); enabled = os.getenv("ENABLE_EXTERNAL_ACTIONS", "0") == "1"
        action = (f"<form method=post action='/shipping-agent-messages/{message_id}/send'><input type=hidden name=csrf value='{esc(current['csrf'])}'><button>إرسال الرسالة المعتمدة الآن</button></form>" if ready and enabled else "<p class=warn>الرسالة معتمدة، لكن Gmail أو الإرسال الخارجي غير جاهز لهذا المستخدم.</p>")
    else: action = f"<p class=good>الحالة: {esc(msg['status'])}</p><p class=warn>{esc(msg.get('last_error'))}</p>"
    body = nav() + f"<h1>{esc(msg['agent_name'])}</h1><div class=card><b>إلى:</b> <span dir=ltr>{esc(msg['recipient'])}</span><br><b>الموضوع:</b> {esc(msg['subject'])}<pre style='white-space:pre-wrap'>{esc(msg['body'])}</pre><b>الحالة:</b> {esc(msg['status'])}</div><div class=card>{action}</div>"
    return HTMLResponse(page("مراسلة وكيل", body))


@router.post("/shipping-agent-messages/{message_id}/update")
async def update_message(message_id: int, request: Request):
    current = auth(request); data = parse(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    msg = one("SELECT * FROM shipping_agent_messages WHERE id=?", (message_id,))
    if not msg or msg["status"] != "draft": raise HTTPException(409)
    execute("UPDATE shipping_agent_messages SET recipient=?,subject=?,body=?,updated_at=? WHERE id=?", (data.get("recipient", "").strip().lower(), data.get("subject"), data.get("body"), utcnow(), message_id))
    log(current["user_id"], "shipping_agent_draft_updated", "shipping_agent_message", message_id, "Draft edited")
    return RedirectResponse(f"/shipping-agent-messages/{message_id}", 303)


@router.post("/shipping-agent-messages/{message_id}/request-approval")
async def request_approval(message_id: int, request: Request):
    current = auth(request); data = parse(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    msg = one("SELECT * FROM shipping_agent_messages WHERE id=?", (message_id,))
    if not msg or msg["status"] != "draft" or "@" not in msg.get("recipient", ""): raise HTTPException(409)
    aid = execute("INSERT INTO approvals(kind,entity_type,entity_id,status,requested_by,notes,created_at) VALUES(?,?,?,?,?,?,?)", ("shipping_agent_email", "shipping_agent_message", message_id, "pending", current["user_id"], "اعتماد المستلم والعنوان والنص قبل مراسلة وكيل الملاحة", utcnow()))
    execute("UPDATE shipping_agent_messages SET status='pending_approval',approval_id=?,updated_at=? WHERE id=?", (aid, utcnow(), message_id))
    return RedirectResponse(f"/shipping-agent-messages/{message_id}", 303)


@router.post("/shipping-agent-messages/{message_id}/approve")
async def approve_message(message_id: int, request: Request):
    current = auth(request); data = parse(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    if current.get("role") != "admin": raise HTTPException(403)
    msg = one("SELECT * FROM shipping_agent_messages WHERE id=?", (message_id,))
    if not msg or msg["status"] != "pending_approval": raise HTTPException(409)
    now = utcnow(); execute("UPDATE approvals SET status='approved',decided_by=?,decided_at=? WHERE id=?", (current["user_id"], now, msg["approval_id"]))
    execute("UPDATE shipping_agent_messages SET status='approved',approved_by=?,approved_at=?,updated_at=? WHERE id=?", (current["user_id"], now, now, message_id))
    log(current["user_id"], "shipping_agent_message_approved", "shipping_agent_message", message_id, "Exact email approved")
    return RedirectResponse(f"/shipping-agent-messages/{message_id}", 303)


@router.post("/shipping-agent-messages/{message_id}/send")
async def send_message(message_id: int, request: Request):
    current = auth(request); data = parse(await request.body())
    if data.get("csrf") != current["csrf"]: raise HTTPException(403)
    msg = one("SELECT * FROM shipping_agent_messages WHERE id=?", (message_id,))
    approval = one("SELECT * FROM approvals WHERE id=?", (msg.get("approval_id"),)) if msg else None
    if not msg or msg["status"] != "approved" or not approval or approval["status"] != "approved": raise HTTPException(409, "الرسالة غير معتمدة")
    try:
        provider_id = send_gmail(current["user_id"], msg["recipient"], msg["subject"], msg["body"]); now = utcnow()
        execute("UPDATE shipping_agent_messages SET status='sent',provider_message_id=?,sent_at=?,last_error=NULL,updated_at=? WHERE id=?", (provider_id, now, now, message_id))
        execute("UPDATE shipping_agent_cases SET status='awaiting_reply',updated_at=? WHERE id=?", (now, msg["case_id"]))
        log(current["user_id"], "shipping_agent_email_sent", "shipping_agent_message", message_id, "Approved Gmail sent")
    except Exception as exc:
        execute("UPDATE shipping_agent_messages SET last_error=?,updated_at=? WHERE id=?", (str(exc)[:500], utcnow(), message_id)); raise HTTPException(503, str(exc)[:500])
    return RedirectResponse(f"/shipping-agent-messages/{message_id}", 303)


@router.get("/api/v7/shipping-agents")
def agents_api(request: Request):
    auth(request)
    return {"agents": rows("SELECT * FROM shipping_agents ORDER BY name"), "contacts": rows("SELECT * FROM shipping_agent_contacts ORDER BY agent_id,purpose")}
