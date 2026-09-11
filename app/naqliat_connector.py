import hashlib
import hmac
import html
import os
import re

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.storage import db, get_session, log, rows, utcnow


router = APIRouter()


def _init_schema():
    with db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS naqliat_loads(
                id BIGSERIAL PRIMARY KEY,
                fingerprint TEXT UNIQUE NOT NULL,
                origin TEXT NOT NULL,
                destination TEXT NOT NULL,
                distance_km INTEGER,
                weight_tons DOUBLE PRECISION,
                vehicle_type TEXT,
                description TEXT,
                owner_phone TEXT,
                age_text TEXT,
                raw_text TEXT,
                capture_method TEXT NOT NULL DEFAULT 'android_accessibility',
                status TEXT NOT NULL DEFAULT 'new',
                captured_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )"""
        )


_init_schema()


def _session(request: Request):
    session = get_session(request.cookies.get("gla_session"))
    if not session:
        raise HTTPException(401, "Login required")
    return session


def _esc(value):
    return html.escape(str(value or ""))


def _page(title, body):
    style = """<style>
    body{font-family:Arial;background:#07131f;color:#eef6fb;margin:0}*{box-sizing:border-box}
    .wrap{max-width:1250px;margin:auto;padding:24px}.card{background:#102536;border:1px solid #28475d;border-radius:16px;padding:20px;margin:14px 0}
    .nav{display:flex;gap:8px;flex-wrap:wrap}.nav a,.btn{display:inline-block;padding:10px 14px;border:0;border-radius:10px;background:#18384d;color:#fff;font-weight:700;text-decoration:none;cursor:pointer}
    .btn{background:#ff7900}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.kpi{background:#0b1d2b;padding:18px;border-radius:12px}.kpi b{display:block;font-size:26px;margin-top:8px}
    input,textarea{width:100%;padding:12px;margin:6px 0;border:1px solid #36586e;border-radius:9px;background:#081925;color:#fff}textarea{min-height:100px}table{width:100%;border-collapse:collapse}th,td{text-align:right;padding:10px;border-bottom:1px solid #28475d}.scroll{overflow:auto}.muted{color:#9fb4c4}.good{color:#54e28b}
    </style>"""
    return '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+_esc(title)+'</title>'+style+'<body><div class="wrap">'+body+'</div></body></html>'


def _nav():
    return '<div class="nav"><a href="/dashboard">الرئيسية</a><a href="/naqliat">شحنات نقليات</a><a href="/drivers">السائقون</a><a href="/commands">مساعد الأوامر</a></div>'


def _clean_phone(value):
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        digits = "966" + digits[1:]
    return "+" + digits if digits else ""


def _fingerprint(origin, destination, weight_tons, vehicle_type, description, owner_phone):
    normalized = "|".join(
        re.sub(r"\s+", " ", str(v or "").strip().lower())
        for v in (origin, destination, weight_tons, vehicle_type, description, owner_phone)
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class NaqliatLoad(BaseModel):
    origin: str = Field(min_length=2, max_length=120)
    destination: str = Field(min_length=2, max_length=120)
    distance_km: int | None = Field(default=None, ge=0, le=20000)
    weight_tons: float | None = Field(default=None, ge=0, le=1000)
    vehicle_type: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=3000)
    owner_phone: str = Field(default="", max_length=40)
    age_text: str = Field(default="", max_length=100)
    raw_text: str = Field(default="", max_length=10000)
    capture_method: str = Field(default="android_accessibility", max_length=60)

class NaqliatOcr(BaseModel):
    raw_text: str = Field(min_length=5, max_length=10000)


def _save(payload: NaqliatLoad):
    phone = _clean_phone(payload.owner_phone)
    fingerprint = _fingerprint(payload.origin, payload.destination, payload.weight_tons, payload.vehicle_type, payload.description, phone)
    now = utcnow()
    with db() as c:
        saved = c.execute(
            """INSERT INTO naqliat_loads(fingerprint,origin,destination,distance_km,weight_tons,vehicle_type,description,owner_phone,age_text,raw_text,capture_method,status,captured_at,created_at)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'new',%s,%s)
               ON CONFLICT(fingerprint) DO NOTHING RETURNING id""",
            (fingerprint, payload.origin.strip(), payload.destination.strip(), payload.distance_km, payload.weight_tons,
             payload.vehicle_type.strip(), payload.description.strip(), phone, payload.age_text.strip(),
             payload.raw_text.strip(), payload.capture_method, now, now),
        ).fetchone()
        created = saved is not None
        if not saved:
            # A capture may already exist from the connector version that only
            # stored rows in naqliat_loads. Reuse it and still promote it to the
            # operational shipments queue instead of silently stopping here.
            saved = c.execute(
                "SELECT id FROM naqliat_loads WHERE fingerprint=%s",
                (fingerprint,),
            ).fetchone()
            if not saved:
                return None

        # Promote every accepted capture to the operational shipments queue.
        # The old flow only populated naqliat_loads, which made the capture
        # invisible on /shipments and in the operations control center.
        load_id = saved["id"]
        reference = "NQ-" + str(load_id)
        shipment = c.execute("SELECT id FROM shipments WHERE reference=%s", (reference,)).fetchone()
        if not shipment:
            shipment = c.execute(
                """INSERT INTO shipments(reference,service_type,origin,destination,status,revenue,cost,currency,created_at,updated_at)
                   VALUES(%s,'Transport',%s,%s,'new',0,0,'SAR',%s,%s) RETURNING id""",
                (reference, payload.origin.strip(), payload.destination.strip(), now, now),
            ).fetchone()
            c.execute(
                """INSERT INTO shipment_operations(shipment_id,stage,notes,created_at,updated_at)
                   VALUES(%s,'new',%s,%s,%s)
                   ON CONFLICT(shipment_id) DO NOTHING""",
                (shipment["id"], "مصدر الحمولة: نقليات | سجل الالتقاط: " + str(load_id), now, now),
            )
        c.execute(
            """INSERT INTO freight_negotiations(shipment_id,naqliat_load_id,owner_phone,weight_tons,status,created_at,updated_at)
               VALUES(%s,%s,%s,%s,'ready_to_contact',%s,%s)
               ON CONFLICT(shipment_id) DO UPDATE SET
                 naqliat_load_id=COALESCE(freight_negotiations.naqliat_load_id,EXCLUDED.naqliat_load_id),
                 owner_phone=COALESCE(NULLIF(freight_negotiations.owner_phone,''),EXCLUDED.owner_phone),
                 weight_tons=COALESCE(freight_negotiations.weight_tons,EXCLUDED.weight_tons),
                 updated_at=EXCLUDED.updated_at""",
            (shipment["id"], load_id, phone, payload.weight_tons, now, now),
        )
        return load_id, created, shipment["id"]


@router.get("/naqliat", response_class=HTMLResponse)
def naqliat_home(request: Request):
    session = _session(request)
    data = rows("SELECT * FROM naqliat_loads ORDER BY captured_at DESC,id DESC LIMIT 300")
    total = len(data)
    fresh = sum(1 for item in data if item["status"] == "new")
    with_phone = sum(1 for item in data if item.get("owner_phone"))
    table = "".join(
        "<tr><td>"+_esc(x["captured_at"])+"</td><td>"+_esc(x["origin"])+"</td><td>"+_esc(x["destination"])+"</td><td>"+_esc(x["distance_km"])+"</td><td>"+_esc(x["weight_tons"])+"</td><td>"+_esc(x["vehicle_type"])+"</td><td dir='ltr'>"+_esc(x["owner_phone"])+"</td><td>"+_esc(x["status"])+"</td></tr>"
        for x in data
    )
    form = """<div class="card"><h2>إضافة حمولة تجريبية</h2><p class="muted">تُستخدم لاختبار المطابقة قبل تركيب تطبيق الهاتف.</p>
    <form method="post" action="/naqliat/manual"><div class="grid"><input name="origin" placeholder="المنشأ" required><input name="destination" placeholder="الوجهة" required><input name="distance_km" type="number" placeholder="المسافة كم"><input name="weight_tons" type="number" step="0.01" placeholder="الوزن طن"><input name="vehicle_type" placeholder="نوع المركبة"><input name="owner_phone" dir="ltr" placeholder="رقم صاحب الحمولة"></div><textarea name="description" placeholder="وصف الحمولة"></textarea><button class="btn">حفظ للاختبار</button></form></div>"""
    body = _nav()+"<h1>شحنات نقليات</h1><p class='muted'>المستخدم: "+_esc(session["email"])+"</p><div class='grid'><div class='kpi'>إجمالي الالتقاطات<b>"+str(total)+"</b></div><div class='kpi'>حمولات جديدة<b>"+str(fresh)+"</b></div><div class='kpi'>بها رقم تواصل<b>"+str(with_phone)+"</b></div></div>"+form+"<div class='card scroll'><table><tr><th>وقت الالتقاط</th><th>المنشأ</th><th>الوجهة</th><th>كم</th><th>طن</th><th>المركبة</th><th>التواصل</th><th>الحالة</th></tr>"+table+"</table></div>"
    return HTMLResponse(_page("شحنات نقليات", body))


@router.post("/naqliat/manual")
async def naqliat_manual(request: Request):
    session = _session(request)
    form = await request.form()
    payload = NaqliatLoad(
        origin=str(form.get("origin", "")), destination=str(form.get("destination", "")),
        distance_km=int(form["distance_km"]) if form.get("distance_km") else None,
        weight_tons=float(form["weight_tons"]) if form.get("weight_tons") else None,
        vehicle_type=str(form.get("vehicle_type", "")), description=str(form.get("description", "")),
        owner_phone=str(form.get("owner_phone", "")), capture_method="manual_test",
    )
    saved = _save(payload)
    item_id = saved[0] if saved else None
    if saved and saved[1]:
        log(session["user_id"], "capture", "naqliat_load", item_id, payload.origin+" → "+payload.destination)
    return RedirectResponse("/naqliat", 303)


@router.post("/api/v7/naqliat/loads")
def ingest_naqliat_load(payload: NaqliatLoad, request: Request, background_tasks: BackgroundTasks):
    expected = os.getenv("NAQLIAT_CONNECTOR_TOKEN", "")
    provided = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(401, "Connector authorization failed")
    saved = _save(payload)
    if saved:
        from app.freight_workflow import contact_owner
        background_tasks.add_task(contact_owner, saved[2])
    return {"ok": True, "created": bool(saved and saved[1]), "id": saved[0] if saved else None,
            "promoted": saved is not None}

@router.post("/api/v7/naqliat/ocr")
def ingest_naqliat_ocr(payload: NaqliatOcr, request: Request, background_tasks: BackgroundTasks):
    expected = os.getenv("NAQLIAT_CONNECTOR_TOKEN", "")
    provided = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(401, "Connector authorization failed")
    raw = payload.raw_text.replace("\u00a0", " ")
    route = re.search(r"(?:مطلوب\s+من|من)\s*:?\s*([^\n،]+?)\s*(?:إلى|الى|إلي|الي)\s*:?\s*(.+?)(?=\s+(?:الحمولة|نوع الشاحنة|سعر|طريقة الدفع|الدفع)\s*:|[\n،.]|$)", raw)
    phone = re.search(r"(?:\+|00)?966\s*5(?:[\s-]*\d){8}", raw)
    weight = re.search(r"([0-9٠-٩]+(?:[.,][0-9٠-٩]+)?)\s*(?:\+\s*)?طن", raw)
    if not route:
        raise HTTPException(422, "Could not detect shipment route")
    digits = lambda value: str(value).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    item = NaqliatLoad(origin=route.group(1).strip(), destination=route.group(2).strip(),
        weight_tons=float(digits(weight.group(1)).replace(",", ".")) if weight else None,
        description=raw[:3000], owner_phone=phone.group(0) if phone else "", raw_text=raw,
        capture_method="android_ocr")
    saved = _save(item)
    if saved:
        from app.freight_workflow import contact_owner
        background_tasks.add_task(contact_owner, saved[2])
    return {"ok": True, "created": bool(saved and saved[1]), "id": saved[0] if saved else None,
            "promoted": saved is not None,
            "origin": item.origin, "destination": item.destination, "owner_phone": _clean_phone(item.owner_phone)}


@router.get("/api/v7/naqliat/loads")
def list_naqliat_loads(request: Request, limit: int = 200):
    _session(request)
    limit = max(1, min(limit, 500))
    return rows("SELECT * FROM naqliat_loads ORDER BY captured_at DESC,id DESC LIMIT %s", (limit,))
