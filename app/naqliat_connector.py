import hashlib
import hmac
import html
import os
import re

from fastapi import APIRouter, HTTPException, Request
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
    return saved["id"] if saved else None


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
    item_id = _save(payload)
    if item_id:
        log(session["user_id"], "capture", "naqliat_load", item_id, payload.origin+" → "+payload.destination)
    return RedirectResponse("/naqliat", 303)


@router.post("/api/v7/naqliat/loads")
def ingest_naqliat_load(payload: NaqliatLoad, request: Request):
    expected = os.getenv("NAQLIAT_CONNECTOR_TOKEN", "")
    provided = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(401, "Connector authorization failed")
    item_id = _save(payload)
    return {"ok": True, "created": item_id is not None, "id": item_id}

@router.post("/api/v7/naqliat/ocr")
def ingest_naqliat_ocr(payload: NaqliatOcr, request: Request):
    expected = os.getenv("NAQLIAT_CONNECTOR_TOKEN", "")
    provided = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(401, "Connector authorization failed")
    raw = payload.raw_text.replace("\u00a0", " ")
    route = re.search(r"(?:من|مطلوب من:)\s*([^\n،]+?)\s*(?:إلى|الى|إلي|الي:)\s*([^\n،.]+)", raw)
    phone = re.search(r"(?:\+|00)?966\s*5(?:[\s-]*\d){8}", raw)
    weight = re.search(r"([0-9٠-٩]+(?:[.,][0-9٠-٩]+)?)\s*(?:\+\s*)?طن", raw)
    if not route:
        raise HTTPException(422, "Could not detect shipment route")
    digits = lambda value: str(value).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    item = NaqliatLoad(origin=route.group(1).strip(), destination=route.group(2).strip(),
        weight_tons=float(digits(weight.group(1)).replace(",", ".")) if weight else None,
        description=raw[:3000], owner_phone=phone.group(0) if phone else "", raw_text=raw,
        capture_method="android_ocr")
    item_id = _save(item)
    return {"ok": True, "created": item_id is not None, "id": item_id,
            "origin": item.origin, "destination": item.destination, "owner_phone": _clean_phone(item.owner_phone)}


@router.get("/api/v7/naqliat/loads")
def list_naqliat_loads(request: Request, limit: int = 200):
    _session(request)
    limit = max(1, min(limit, 500))
    return rows("SELECT * FROM naqliat_loads ORDER BY captured_at DESC,id DESC LIMIT %s", (limit,))
