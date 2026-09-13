from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title='Shawahid Alhadaf Dashboard')

PAGES = {
    'overview': ('نظرة عامة', 'ملخص أداء الوكيل، أهم الفرص، التنبيهات والإجراءات المطلوبة.'),
    'discover': ('اكتشاف الفرص', 'بحث وتصنيف فرص العملاء، الأفلييت، المحتوى والشراكات.'),
    'score': ('تقييم الفرص', 'تقييم الفرص من 100 حسب الربحية والسرعة والمنافسة وقابلية الأتمتة.'),
    'content': ('استديو المحتوى', 'إنشاء محتوى English-only ليوتيوب وإنستغرام وتيك توك.'),
    'calendar': ('تقويم النشر', 'جدولة ومتابعة المحتوى على المنصات المرتبطة.'),
    'approvals': ('صندوق الموافقات', 'مراجعة واعتماد ما يحتاج قرار الإدارة قبل التنفيذ.'),
    'campaigns': ('الحملات والعروض', 'العروض التسويقية، الحملات، ومسارات الربح الجاهزة.'),
    'customers': ('خدمة العملاء', 'البريد الوارد، الردود، التصنيف، وتصعيد الحالات للإدارة.'),
    'comms': ('سجل التواصل', 'سجل موحد لمحادثات العملاء والردود والإجراءات.'),
    'performance': ('الأداء', 'مؤشرات الأداء، النشر، العملاء المحتملون، والنتائج.'),
}

HTML = r'''<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>شواهد الهدف — محرك الفرص</title>
<style>
:root{--navy:#071d37;--navy2:#0c2b4a;--gold:#d9a526;--bg:#f3f6f9;--card:#fff;--text:#152033;--muted:#748094;--line:#e4e9ef;--ok:#14845f;--warn:#b57600}
*{box-sizing:border-box}body{margin:0;background:var(--bg);font-family:Tahoma,Arial,sans-serif;color:var(--text)}
.app{display:flex;min-height:100vh}.sidebar{width:280px;background:linear-gradient(180deg,var(--navy),#0a2744);color:#fff;padding:24px 16px;position:fixed;right:0;top:0;bottom:0;overflow:auto}.brand{font-size:23px;font-weight:800}.brand small{display:block;font-size:11px;letter-spacing:1px;color:#d9b963;margin-top:4px}.nav{margin-top:24px}.nav button{display:flex;align-items:center;gap:10px;width:100%;padding:12px 14px;margin:4px 0;border:0;border-radius:10px;background:transparent;color:#d9e5f1;font-size:14px;text-align:right;cursor:pointer}.nav button:hover,.nav button.active{background:#173d62;color:#fff}.nav button.active{box-shadow:inset -3px 0 0 var(--gold)}
.main{margin-right:280px;width:calc(100% - 280px);padding:26px 30px}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:22px}.top h1{margin:0;font-size:25px}.sub{color:var(--muted);font-size:13px;margin-top:7px}.pill{background:#eef8f3;color:var(--ok);padding:8px 11px;border-radius:999px;font-size:12px;font-weight:700}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px}.stat .label{font-size:12px;color:var(--muted)}.stat .num{font-size:29px;font-weight:800;margin:8px 0}.delta{font-size:11px;color:var(--ok)}.layout{display:grid;grid-template-columns:1.45fr 1fr;gap:16px;margin-top:16px}.card h2{font-size:16px;margin:0 0 15px}.btn{border:1px solid var(--line);background:#fff;padding:9px 13px;border-radius:9px;cursor:pointer}.btn.primary{background:var(--navy2);color:#fff;border-color:var(--navy2)}.btn.gold{background:var(--gold);color:#1b1b1b;border-color:var(--gold);font-weight:700}.toolbar{display:flex;gap:8px;flex-wrap:wrap}.table{width:100%;border-collapse:collapse}.table th,.table td{padding:12px;border-bottom:1px solid var(--line);font-size:12px;text-align:right}.badge{padding:5px 8px;border-radius:999px;font-size:11px;background:#eef2f7}.score{font-weight:800;color:var(--ok)}.notice{padding:13px;border-radius:11px;background:#fff7df;border:1px solid #f1d886;color:#7b5a00;margin-bottom:12px}.empty{padding:30px;text-align:center;color:var(--muted)}.actions{display:flex;gap:8px;flex-wrap:wrap}.toast{position:fixed;left:24px;bottom:24px;background:#10273f;color:white;padding:13px 17px;border-radius:10px;display:none;box-shadow:0 8px 24px #0003;z-index:10}.page{display:none}.page.active{display:block}.section-title{display:flex;align-items:center;justify-content:space-between;margin-bottom:15px}.status-row{display:flex;gap:8px;flex-wrap:wrap}.status-chip{padding:7px 10px;border-radius:8px;background:#f0f4f8;font-size:12px}.status-chip.ok{background:#e8f6ef;color:#117154}.status-chip.wait{background:#fff3d6;color:#855c00}
@media(max-width:980px){.grid{grid-template-columns:repeat(2,1fr)}.layout{grid-template-columns:1fr}.sidebar{width:230px}.main{margin-right:230px;width:calc(100% - 230px)}}
@media(max-width:720px){.sidebar{position:relative;width:100%;height:auto}.app{display:block}.main{margin:0;width:100%;padding:16px}.grid{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}
</style>
</head><body>
<div class="app">
<aside class="sidebar">
<div class="brand">شواهد الهدف<small>SHAWAHID ALHADAF</small></div>
<div class="nav" id="nav">
<button data-page="overview" class="active">⌂ نظرة عامة</button>
<button data-page="discover">⌕ اكتشاف الفرص</button>
<button data-page="score">◎ تقييم الفرص</button>
<button data-page="content">✦ استديو المحتوى</button>
<button data-page="calendar">▣ تقويم النشر</button>
<button data-page="approvals">✓ صندوق الموافقات</button>
<button data-page="campaigns">◇ الحملات والعروض</button>
<button data-page="customers">◉ خدمة العملاء</button>
<button data-page="comms">↔ سجل التواصل</button>
<button data-page="performance">▥ الأداء</button>
</div>
</aside>
<main class="main">
<div class="top"><div><h1 id="pageTitle">نظرة عامة</h1><div id="pageSub" class="sub">ملخص أداء الوكيل، أهم الفرص، التنبيهات والإجراءات المطلوبة.</div></div><div class="pill">● النظام يعمل</div></div>

<section id="overview" class="page active">
<div class="notice"><b>مطلوب من الإدارة:</b> مراجعة الفرص ذات الدرجة 75+ قبل أي تسجيل مدفوع أو تواصل تجاري.</div>
<div class="grid">
<div class="card stat"><div class="label">فرص نشطة</div><div class="num">4</div><div class="delta">+3 هذا الأسبوع</div></div>
<div class="card stat"><div class="label">متوسط التقييم</div><div class="num">85</div><div class="delta">من 100</div></div>
<div class="card stat"><div class="label">الربح المتوقع</div><div class="num">18.4K</div><div class="delta">ريال / شهر</div></div>
<div class="card stat"><div class="label">حملات جاهزة</div><div class="num">1</div><div class="delta">بانتظار الإطلاق</div></div>
</div>
<div class="layout">
<div class="card"><div class="section-title"><h2>أفضل الفرص المكتشفة</h2><button class="btn primary action" data-action="scan">اكتشاف فرص جديدة</button></div>
<table class="table"><thead><tr><th>الفرصة</th><th>النوع</th><th>السوق</th><th>التقييم</th><th>الحالة</th></tr></thead><tbody>
<tr><td>قالب إدارة مصروفات المتاجر</td><td>منتج رقمي</td><td>السعودية</td><td class="score">92/100</td><td><span class="badge">قيد المراجعة</span></td></tr>
<tr><td>برنامج أفلييت لأداة إنشاء المتاجر</td><td>أفلييت</td><td>الخليج</td><td class="score">87/100</td><td><span class="badge">جديدة</span></td></tr>
<tr><td>خدمة صناعة محتوى للعيادات</td><td>خدمة رقمية</td><td>الرياض</td><td class="score">84/100</td><td><span class="badge">معتمدة</span></td></tr>
</tbody></table></div>
<div class="card"><h2>حالة التشغيل</h2><div class="status-row"><span class="status-chip ok">البريد: نشط</span><span class="status-chip ok">اكتشاف الفرص: نشط</span><span class="status-chip ok">YouTube: مربوط</span><span class="status-chip wait">Instagram: بانتظار الربط</span><span class="status-chip wait">TikTok: بانتظار الربط</span></div><div style="margin-top:16px" class="actions"><button class="btn gold" data-page-jump="approvals">فتح الموافقات</button><button class="btn" data-page-jump="content">فتح استديو المحتوى</button></div></div>
</div></section>

<section id="discover" class="page"><div class="card"><div class="section-title"><h2>اكتشاف الفرص</h2><button class="btn primary action" data-action="scan">تشغيل بحث جديد</button></div><p>المسارات: عملاء خدمات التسويق، Affiliate، Content Monetization، Partnerships.</p><div class="actions"><button class="btn action" data-action="filter">تصفية 75+</button><button class="btn action" data-action="export">تصدير النتائج</button></div></div></section>
<section id="score" class="page"><div class="card"><h2>تقييم الفرص</h2><p>يتم احتساب الدرجة وفق الربحية، الإلحاح، قوة الدليل، سرعة التنفيذ، المنافسة، وقابلية الأتمتة.</p><table class="table"><tr><th>العامل</th><th>الوزن</th></tr><tr><td>الربحية</td><td>25%</td></tr><tr><td>قوة الدليل</td><td>20%</td></tr><tr><td>سرعة أول دخل</td><td>20%</td></tr><tr><td>قابلية الأتمتة</td><td>15%</td></tr><tr><td>المنافسة</td><td>10%</td></tr><tr><td>الإلحاح</td><td>10%</td></tr></table></div></section>
<section id="content" class="page"><div class="card"><div class="section-title"><h2>استديو المحتوى</h2><button class="btn gold action" data-action="content">إنشاء محتوى جديد</button></div><p><b>قاعدة شواهد الهدف:</b> English-only public content.</p><div class="status-row"><span class="status-chip ok">YouTube Shorts</span><span class="status-chip wait">Instagram Reels</span><span class="status-chip wait">TikTok</span></div></div></section>
<section id="calendar" class="page"><div class="card"><h2>تقويم النشر</h2><p>لا توجد منشورات مجدولة بعد في هذه النسخة التجريبية.</p><button class="btn primary action" data-action="schedule">جدولة منشور</button></div></section>
<section id="approvals" class="page"><div class="card"><h2>صندوق الموافقات</h2><div class="notice">3 عناصر تحتاج قرار الإدارة.</div><div class="actions"><button class="btn gold action" data-action="approve">اعتماد المحدد</button><button class="btn action" data-action="reject">استبعاد</button></div></div></section>
<section id="campaigns" class="page"><div class="card"><h2>الحملات والعروض</h2><p>المسار: فرصة → عرض قيمة → محتوى → CTA → نشر/تواصل → قياس.</p><button class="btn primary action" data-action="campaign">إنشاء حملة</button></div></section>
<section id="customers" class="page"><div class="layout"><div class="card"><h2>صندوق خدمة العملاء</h2><p>البريد المركزي يوجّه الرسائل بين آفاق طويق وشواهد الهدف ويمنع الرد على الإعلانات والتنبيهات.</p><div class="actions"><button class="btn primary action" data-action="refresh-mail">تحديث البريد</button><button class="btn action" data-action="management">تدخل الإدارة</button></div></div><div class="card"><h2>الحالة</h2><div class="status-row"><span class="status-chip ok">Email Router: نشط</span><span class="status-chip ok">تصنيف الرسائل: نشط</span><span class="status-chip wait">WhatsApp: مؤجل</span></div></div></div></section>
<section id="comms" class="page"><div class="card"><h2>سجل التواصل</h2><div class="empty">سيظهر هنا سجل الرسائل والردود بعد ربط البيانات المباشرة.</div></div></section>
<section id="performance" class="page"><div class="grid"><div class="card stat"><div class="label">فرص 75+</div><div class="num">3</div></div><div class="card stat"><div class="label">محتوى جاهز</div><div class="num">1</div></div><div class="card stat"><div class="label">رسائل مصنفة</div><div class="num">—</div></div><div class="card stat"><div class="label">دخل متتبع</div><div class="num">—</div></div></div></section>
</main></div><div class="toast" id="toast"></div>
<script>
const meta={overview:['نظرة عامة','ملخص أداء الوكيل، أهم الفرص، التنبيهات والإجراءات المطلوبة.'],discover:['اكتشاف الفرص','البحث عن فرص خدمات، أفلييت، محتوى وشراكات.'],score:['تقييم الفرص','تقييم كل فرصة بدرجة من 100.'],content:['استديو المحتوى','إنشاء وتجهيز محتوى English-only للنشر.'],calendar:['تقويم النشر','جدولة ومتابعة المنشورات.'],approvals:['صندوق الموافقات','العناصر التي تحتاج قرار الإدارة.'],campaigns:['الحملات والعروض','بناء عروض وحملات من الفرص المعتمدة.'],customers:['خدمة العملاء','البريد، الردود، التصعيد وسجل العملاء.'],comms:['سجل التواصل','تاريخ الرسائل والإجراءات.'],performance:['الأداء','قياس النتائج ومؤشرات الأداء.']};
function showPage(id){document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));document.querySelectorAll('#nav button').forEach(x=>x.classList.remove('active'));const p=document.getElementById(id);if(!p)return;p.classList.add('active');const b=document.querySelector(`#nav button[data-page="${id}"]`);if(b)b.classList.add('active');document.getElementById('pageTitle').textContent=meta[id][0];document.getElementById('pageSub').textContent=meta[id][1];location.hash=id;}
document.querySelectorAll('#nav button').forEach(b=>b.addEventListener('click',()=>showPage(b.dataset.page)));
document.querySelectorAll('[data-page-jump]').forEach(b=>b.addEventListener('click',()=>showPage(b.dataset.pageJump)));
function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.style.display='block';setTimeout(()=>t.style.display='none',2600)}
document.querySelectorAll('.action').forEach(b=>b.addEventListener('click',()=>{const m={scan:'تم تشغيل البحث التجريبي عن الفرص.',filter:'تم تطبيق فلتر الفرص 75+.',export:'تم تجهيز أمر التصدير.',content:'تم فتح مسار إنشاء محتوى جديد.',schedule:'تم فتح أمر الجدولة.',approve:'تم تسجيل الاعتماد التجريبي.',reject:'تم تسجيل الاستبعاد التجريبي.',campaign:'تم فتح منشئ الحملة.', 'refresh-mail':'تم تشغيل تحديث صندوق البريد.',management:'تم فتح قائمة تدخل الإدارة.'};toast(m[b.dataset.action]||'تم تنفيذ الأمر.')}));
const h=location.hash.replace('#','');if(meta[h])showPage(h);
</script></body></html>'''

@app.get('/', response_class=HTMLResponse)
def home():
    return HTML

@app.get('/health')
def health():
    return JSONResponse({'ok': True, 'app': 'shawahid-ui-fix'})
