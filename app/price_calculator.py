"""Public instant price calculator + lead capture (owner request, Nov 2026).

/price shows Afaq's APPROVED prices only (clearance per container by containers per bill of lading, listed transport
routes). The visitor sees the estimate instantly; leaving a name and number records a lead, alerts the manager, and
opens WhatsApp with the request pre-written — the customer writes to us first, so the agent's normal conversation
continues from there. Nothing is sent to the visitor automatically.
"""
import asyncio
import hashlib
import html
import json
import re
import urllib.parse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.storage import db, utcnow

router = APIRouter()
WHATSAPP = '966507665873'


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS price_leads(id BIGSERIAL PRIMARY KEY, company TEXT NOT NULL, phone TEXT NOT NULL,
            service TEXT NOT NULL, route TEXT, containers INTEGER NOT NULL, total INTEGER NOT NULL, source TEXT,
            ip_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)''')


def prices():
    from app.prospect_replies import price_table
    tiers, routes = price_table()
    return {'tiers': tiers, 'routes': routes}


def compute(service, route, containers):
    p = prices()
    n = max(1, min(int(containers), 200))
    clearance = 0
    if service in ('clearance', 'both'):
        rate = p['tiers'][1] if n <= 1 else p['tiers'][2] if n <= 5 else p['tiers'][6]
        clearance = n * rate
    transport = n * p['routes'][route] if service in ('transport', 'both') and route in p['routes'] else 0
    return n, clearance, transport


def phone_ok(value):
    d = re.sub(r'\D', '', str(value or ''))
    if d.startswith('00'):
        d = d[2:]
    if d.startswith('05') and len(d) == 10:
        d = '966' + d[1:]
    return d if 11 <= len(d) <= 15 else ''


def ip_hash(request):
    ip = (request.headers.get('x-forwarded-for') or (request.client.host if request.client else '')).split(',')[0].strip()
    return hashlib.sha256((ip + '|price').encode()).hexdigest()[:20]


@router.post('/price/lead')
async def lead(request: Request):
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(400)
    if not isinstance(data, dict) or data.get('website'):  # honeypot
        raise HTTPException(400)
    if data.get('scope') == 'land_export':
        return JSONResponse({'error': 'أجور تخليص الصادر البري 200 ريال لكل بوليصة أو شحنة تريلا واحدة، تكلفة التخليص فقط، ولا تشمل أي رسوم أو تكاليف أخرى. تواصل مع الفريق لتأكيد العدد وعرض الصادر.'}, status_code=400)
    company = ' '.join(str(data.get('company') or '').split())[:120]
    phone = phone_ok(data.get('phone'))
    service = data.get('service') if data.get('service') in ('clearance', 'transport', 'both') else None
    route = str(data.get('route') or '')
    try:
        containers = int(data.get('containers') or 1)
    except (TypeError, ValueError):
        containers = 1
    if len(company) < 2 or not phone or not service:
        return JSONResponse({'error': 'اكتب اسم الشركة ورقم جوال صحيح.'}, status_code=400)
    if service != 'clearance' and route not in prices()['routes']:
        route = ''
    n, clearance, transport = compute(service, route, containers)
    total = clearance + transport
    init()
    who = ip_hash(request)
    with db() as c:
        recent = c.execute("SELECT COUNT(*) n FROM price_leads WHERE ip_hash=%s AND created_at > NOW()-INTERVAL '1 hour'", (who,)).fetchone()['n']
        if recent >= 5:
            return JSONResponse({'error': 'تم استلام طلباتك؛ تواصل معنا على واتساب.'}, status_code=429)
        lid = c.execute('''INSERT INTO price_leads(company,phone,service,route,containers,total,source,ip_hash,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                        (company, phone, service, route, n, total, str(data.get('source') or '')[:40], who, utcnow())).fetchone()['id']
    label = {'clearance': 'تخليص جمركي', 'transport': 'نقل بري', 'both': 'تخليص ونقل'}[service]
    lines = [f'طلب عرض سعر من حاسبة آفاق (#{lid})', f'الشركة: {company}', f'الخدمة: {label} — {n} حاوية']
    if route:
        lines.append('المسار: ' + route)
    if total:
        lines.append(f'الإجمالي التقديري: {total:,} ريال')
    text = '\n'.join(lines)
    try:
        from app.owner_briefing import deliver
        asyncio.get_running_loop().create_task(deliver('🧮 عميل جديد من حاسبة الأسعار\n' + text + f'\nجواله: +{phone}\nسيتواصل معنا على واتساب؛ والوكيل يرد عليه.'))
    except Exception:
        pass
    return {'ok': True, 'whatsapp': 'https://wa.me/' + WHATSAPP + '?text=' + urllib.parse.quote(text)}


@router.get('/price', response_class=HTMLResponse)
def page(src: str = ''):
    p = prices()
    data = json.dumps({'tiers': p['tiers'], 'routes': p['routes']}, ensure_ascii=False)
    options = ''.join(f'<option value="{html.escape(k)}"{" selected" if k == "من ميناء جدة الإسلامي إلى الرياض" else ""}>{html.escape(k)}</option>'
                      for k in p['routes'])
    source = html.escape(re.sub(r'[^\w-]', '', src)[:40])
    return HTMLResponse(PAGE.replace('__ROUTES__', options).replace('__DATA__', data).replace('__SRC__', source),
                        headers={'Cache-Control': 'no-store'})


PAGE = '''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>حاسبة أسعار آفاق طويق — التخليص الجمركي والنقل</title>
<meta name="description" content="احسب سعر التخليص الجمركي والنقل البري لحاوياتك فورًا بالأسعار المعتمدة من آفاق طويق.">
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;800&display=swap" rel="stylesheet">
<style>
:root{--bg:#06222a;--card:#0b3440;--line:#1d5563;--text:#eef7f8;--muted:#9fc0c6;--gold:#d7a640;--teal:#14a3a3}
*{box-sizing:border-box}body{margin:0;font-family:Cairo,Tahoma,sans-serif;background:radial-gradient(circle at 80% -10%,#0f4c58,var(--bg) 55%);color:var(--text);min-height:100vh}
.w{max-width:760px;margin:auto;padding:28px 16px 60px}h1{font-size:28px;margin:6px 0}.sub{color:var(--muted);margin:0 0 20px}
.brand{color:var(--gold);font-weight:800;letter-spacing:.5px}.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:20px;margin:14px 0}
label{display:block;font-weight:600;margin:12px 0 6px}select,input{width:100%;padding:12px;border-radius:12px;border:1px solid var(--line);background:#062a33;color:var(--text);font:inherit}
.seg{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.seg button{padding:12px 6px;border-radius:12px;border:1px solid var(--line);background:#062a33;color:var(--text);font:inherit;cursor:pointer}
.seg button.on{background:var(--teal);border-color:var(--teal);color:#032;font-weight:800}
.total{font-size:34px;font-weight:800;color:var(--gold);margin:6px 0}.row{display:flex;justify-content:space-between;color:var(--muted);margin:4px 0}
.note{font-size:13px;color:var(--muted);line-height:1.8}.cta{width:100%;margin-top:14px;padding:14px;border:0;border-radius:14px;background:var(--gold);color:#231800;font:inherit;font-weight:800;font-size:17px;cursor:pointer}
.err{color:#ffb4a8;margin-top:8px;min-height:20px}.hp{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none;overflow:hidden}html,body{overflow-x:hidden}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media(max-width:520px){.grid{grid-template-columns:1fr}.seg{grid-template-columns:1fr}}
</style></head><body><div class="w">
<div class="brand">آفاق طويق | AFAQ TWIQ</div><h1>احسب سعر شحنتك الآن</h1>
<p class="sub">حاسبة أجور الحاويات والنقل للمسارات المذكورة. لا تُستخدم نتائج هذه الحاسبة لتخليص الصادر عبر المنافذ البرية.</p>
<div class="card">
<label for="scope">نوع حساب السعر</label><select id="scope"><option value="containers">أجور الحاويات والنقل (لا يشمل الصادر البري)</option><option value="land_export">تخليص صادر بري</option></select>
<div id="containerOptions"><label>الخدمة</label><div class="seg" id="svc"><button data-v="both" class="on">تخليص + نقل</button><button data-v="clearance">تخليص فقط</button><button data-v="transport">نقل فقط</button></div>
<div class="grid"><div><label for="n">عدد الحاويات في البوليصة</label><input id="n" type="number" min="1" max="200" value="1"></div>
<div id="routeBox"><label for="route">المسار</label><select id="route">__ROUTES__</select></div></div>
</div>
</div>
<div class="card" id="containerResult"><div class="row"><span>التخليص الجمركي</span><span id="c">—</span></div><div class="row"><span>النقل البري</span><span id="t">—</span></div>
<div class="total" id="tot">—</div>
<p class="note">الأسعار معتمدة وصالحة 15 يومًا، الشاحنة حتى 27 طن. لا تشمل الرسوم الجمركية وضريبة الاستيراد والرسوم الحكومية وأجور الموانئ والخط الملاحي؛ يتحملها المستورد حسب فواتيرها. لتخليص الصادر البري سعر مستقل: 200 ريال لكل بوليصة أو شحنة تريلا واحدة، تكلفة التخليص فقط، ولا تشمل أي رسوم أو تكاليف أخرى. اطلب عرض الصادر من الفريق؛ وللنقل من منافذ ومسارات أخرى (الدمام، المنافذ البرية، المطارات…) يرسل الفريق عرضًا خاصًا.</p></div>
<div class="card" id="exportResult" hidden><div class="total">200 ريال</div><p>أجور تخليص الصادر عبر المنافذ البرية لكل بوليصة أو شحنة تريلا واحدة، تكلفة التخليص فقط، ولا تشمل أي رسوم أو تكاليف أخرى.</p><p class="note">لتأكيد عدد البوالص أو شحنات التريلا وإعداد العرض، تواصل مع فريق آفاق. هذا السعر لا ينطبق على الصادر البحري أو الجوي.</p><a class="cta" href="https://wa.me/966507665873">اطلب عرض تخليص الصادر عبر واتساب</a></div>
<div class="card" id="leadForm"><label for="co">اسم الشركة</label><input id="co" autocomplete="organization" placeholder="مثال: مؤسسة النخبة للتجارة">
<label for="ph">رقم الجوال (واتساب)</label><input id="ph" inputmode="tel" autocomplete="tel" placeholder="05xxxxxxxx">
<input class="hp" id="website" tabindex="-1" autocomplete="off">
<button class="cta" id="go">احصل على العرض الرسمي عبر واتساب</button><div class="err" id="err"></div>
<p class="note">قبل ما تشتري؟ <a href="/check" style="color:var(--gold)">افحص أصناف عرض المورد مجانًا</a> — البند الجمركي والرسوم واشتراطات سابر.</p>
<p class="note">رخصة التخليص الجمركي 2513 — رخصة النقل 11/00098402 — نعمل 24/7.</p></div>
</div><script>
const D=__DATA__;let svc='both';const f=x=>x.toLocaleString('en-US')+' ريال';
function calc(){const landExport=document.getElementById('scope').value==='land_export';
['containerOptions','containerResult','leadForm'].forEach(i=>document.getElementById(i).hidden=landExport);document.getElementById('exportResult').hidden=!landExport;if(landExport)return;
const n=Math.max(1,Math.min(200,parseInt(document.getElementById('n').value)||1));const r=document.getElementById('route').value;
let c=0,t=0;if(svc!=='transport'){c=n*(n<=1?D.tiers[1]:n<=5?D.tiers[2]:D.tiers[6]);}if(svc!=='clearance'&&D.routes[r]){t=n*D.routes[r];}
document.getElementById('c').textContent=svc==='transport'?'—':f(c)+' ('+n+' × '+(c/n)+')';document.getElementById('t').textContent=svc==='clearance'?'—':f(t);
document.getElementById('tot').textContent=f(c+t);document.getElementById('routeBox').style.display=svc==='clearance'?'none':'block';}
document.querySelectorAll('#svc button').forEach(b=>b.onclick=()=>{document.querySelectorAll('#svc button').forEach(x=>x.classList.remove('on'));b.classList.add('on');svc=b.dataset.v;calc();});
['n','route','scope'].forEach(i=>document.getElementById(i).oninput=calc);calc();
document.getElementById('go').onclick=async()=>{const e=document.getElementById('err');e.textContent='';
const body={scope:document.getElementById('scope').value,company:document.getElementById('co').value,phone:document.getElementById('ph').value,service:svc,route:document.getElementById('route').value,
containers:document.getElementById('n').value,website:document.getElementById('website').value,source:'__SRC__'};
try{const r=await fetch('/price/lead',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const j=await r.json();
if(!r.ok){e.textContent=j.error||'تعذر الإرسال';return;}location.href=j.whatsapp;}catch(x){e.textContent='تعذر الإرسال، حاول مرة أخرى.';}};
</script></body></html>'''
