"""Persistent, authenticated operational visibility; never performs external actions."""
from datetime import datetime, timezone
import json
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

router = APIRouter()
_ready = False


def ensure_schema():
    global _ready
    if _ready:
        return
    from app.storage import db
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(73002027)')
        c.execute('''CREATE TABLE IF NOT EXISTS agent_runs (
          id BIGSERIAL PRIMARY KEY, status TEXT NOT NULL, step TEXT NOT NULL,
          completed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
          result TEXT NOT NULL DEFAULT '{}', started_at TIMESTAMPTZ NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ)''')
    _ready = True


def start_run():
    from app.storage import execute, utcnow
    ensure_schema()
    now = utcnow()
    return execute("INSERT INTO agent_runs(status,step,started_at,updated_at) VALUES(?,?,?,?)",
                   ('running', 'بدء دورة البحث', now, now))


def update_run(run_id, step, completed=0, total=0, result=None, status='running'):
    if run_id is None:
        return
    from app.storage import execute, log, utcnow
    now = utcnow()
    execute('UPDATE agent_runs SET status=?,step=?,completed=?,total=?,result=?,updated_at=?,finished_at=? WHERE id=?',
            (status, step, completed, total, json.dumps(result or {}, ensure_ascii=False), now,
             None if status == 'running' else now, run_id))
    log(None, 'agent_progress', 'agent_run', run_id, step)


def run_view(run, now=None):
    if not run:
        return {'status': 'idle', 'label': 'لا توجد دورة بحث مسجلة بعد'}
    run = dict(run)
    now = now or datetime.now(timezone.utc)
    stamp = run['updated_at']
    if isinstance(stamp, str):
        stamp = datetime.fromisoformat(stamp)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    if run['status'] == 'running' and (now - stamp).total_seconds() > 300:
        run['status'] = 'stale'
    run['label'] = {'running': 'البحث جارٍ', 'completed': 'اكتمل البحث',
                    'partial': 'اكتمل البحث مع تعذر بعض المصادر', 'failed': 'تعطل البحث',
                    'stale': 'تأخر تحديث التنفيذ — الحالة غير مؤكدة'}.get(run['status'], run['status'])
    run['result'] = json.loads(run.get('result') or '{}')
    return run


ACTION_LABELS = {
    'create_outbound_draft': 'تجهيز مسودة — لم ترسل',
    'request_send_approval': 'بانتظار اعتماد الإرسال',
    'approve_external_send': 'اعتماد الرسالة — ليس إثبات إرسال',
    'send_approved_message': 'قبل مزود البريد الرسالة — التسليم غير مؤكد',
    'freight_owner_contact_submitted': 'قبل مزود الاتصال طلب التواصل مع صاحب الحمولة',
    'freight_driver_offer_prepared': 'تجهيز عرض للسائق — لم يرسل',
    'run': 'طلب تشغيل البحث',
}


def snapshot():
    from app.storage import rows, one, utcnow
    ensure_schema()
    latest = run_view(one('SELECT * FROM agent_runs ORDER BY id DESC LIMIT 1'))
    events = []
    for e in rows('SELECT id,action,entity_type,entity_id,summary,created_at FROM activity ORDER BY id DESC LIMIT 100'):
        if e['action'] == 'agent_progress':
            label = e['summary']
        elif e['action'] in ACTION_LABELS:
            label = ACTION_LABELS[e['action']]
        else:
            continue
        events.append({'id': e['id'], 'label': label, 'entity_id': e['entity_id'],
                       'entity_type': e['entity_type'], 'at': e['created_at']})
    messages = rows('SELECT status,COUNT(*) count FROM outbound_messages GROUP BY status')
    sources = rows('SELECT name,last_status,last_checked_at FROM source_watches WHERE enabled=1 ORDER BY id')
    signals = rows("SELECT id,title,status FROM discovered_signals WHERE opportunity_id IS NULL AND status<>'new' ORDER BY id DESC LIMIT 10")
    return {'run': latest, 'events': events[:30], 'messages': messages,
            'sources': sources, 'signals': signals, 'updated_at': utcnow()}


@router.get('/api/agent-monitor')
def monitor_api(request: Request):
    from app.storage import get_session
    if not get_session(request.cookies.get('gla_session')):
        raise HTTPException(401, 'يلزم تسجيل الدخول')
    return JSONResponse(jsonable_encoder(snapshot()), headers={'Cache-Control': 'no-store'})


def monitor_widget():
    return '''
<style>
#agent-watch{border:1px solid #d5ad52;border-radius:16px;background:#102b3e;padding:14px 18px;margin:16px 0;color:#f3f7fa}
#agent-watch summary{cursor:pointer;display:flex;gap:12px;align-items:center;flex-wrap:wrap;font-weight:700}
#agent-watch summary:before{content:'◉';color:#e7b64b}#aw-state{color:#ffd978}#aw-step{margin:14px 0 6px}
#agent-watch progress{width:100%;height:12px;accent-color:#e7b64b}#aw-feed{max-height:270px;overflow-y:auto;padding:0;list-style:none}
#aw-feed li{border-bottom:1px solid #355064;padding:9px 0}#aw-feed time{color:#a7bdcb;margin-left:10px;font-size:12px}
#aw-sources{max-height:200px;overflow:auto}#aw-sources p{border-bottom:1px solid #355064;padding:8px 0;margin:0}
#aw-stamp{font-size:12px;color:#bdd0dd}#agent-watch a{color:#ffd978}#aw-result,#aw-messages{line-height:1.9}
</style>
<details id="agent-watch" open>
<summary><span>ماذا يفعل الوكيل؟</span><span id="aw-state" role="status">جارٍ جلب الحالة…</span><span id="aw-stamp"></span></summary>
<p id="aw-step"></p><progress id="aw-progress" value="0" max="1" aria-label="المصادر المنتهية"></progress>
<p id="aw-result"></p><p id="aw-messages"></p>
<p id="aw-signals"></p>
<details><summary>حالة المصادر وأسباب التعثر</summary><div id="aw-sources"></div></details>
<h3>آخر أحداث التنفيذ</h3><ul id="aw-feed"></ul>
<a href="/activity">فتح سجل النشاط الكامل</a> · <a href="/outbound">متابعة الرسائل</a>
</details>
<script>
(()=>{
const el=id=>document.getElementById(id), txt=(id,v)=>el(id).textContent=v;
const fmt=v=>v?new Date(v).toLocaleString('ar-SA',{timeZone:'Asia/Riyadh'}):'—';
const labels={draft:'مسودة',pending_approval:'بانتظار الاعتماد',approved:'معتمدة ولم ترسل',sent:'مقبولة من مزود البريد',failed:'فشل الإرسال',sending:'جارٍ الإرسال'};
const reasons={prospect:'جهة محتملة وليست طلبًا',listing:'صفحة عامة',closed:'طلب مغلق',recruitment:'إعلان توظيف',provider:'عرض مقدم خدمة',unverified:'طلب غير موثق',needs_verification:'تعذر التحقق من المصدر'};
async function refresh(){
try{
const res=await fetch('/api/agent-monitor',{cache:'no-store',signal:AbortSignal.timeout(10000)});
if(!res.ok)throw new Error(res.status===401?'انتهت الجلسة — سجّل الدخول':'تعذر تحديث الحالة');
const d=await res.json(),r=d.run,s=r.result||{};
txt('aw-state',r.label);txt('aw-stamp','آخر قراءة: '+fmt(d.updated_at));
txt('aw-step',(r.step||'بانتظار تشغيل البحث')+(r.updated_at?' · آخر حدث: '+fmt(r.updated_at):''));
el('aw-progress').max=Math.max(1,r.total||0);el('aw-progress').value=r.completed||0;
txt('aw-result','مصادر منتهية: '+(r.completed||0)+' / '+(r.total||0)+' · إشارات جديدة: '+(s.signals||0)+' · فرص اجتازت التحقق: '+((s.opportunities||0)+(s.external_opportunities||0))+' · مصادر تعذر فحصها: '+(s.errors||0));
txt('aw-messages','حالة رسائل البريد المسجلة (إجمالي): '+(d.messages.map(m=>(labels[m.status]||m.status)+': '+m.count).join(' · ')||'لا توجد رسائل')+' — لا يعني قبول المزود وصول الرسالة أو موافقة العميل.');
txt('aw-signals','آخر نتائج التأهيل غير المحولة: '+(d.signals.map(s=>s.title+' ('+(reasons[s.status]||s.status)+')').join('؛ ')||'لا توجد نتائج مسجلة'));
el('aw-feed').replaceChildren();
for(const e of d.events){const li=document.createElement('li'),t=document.createElement('time');t.textContent=fmt(e.at);li.append(t,document.createTextNode(e.label+(e.entity_id?' · #'+e.entity_id:'')));el('aw-feed').append(li);}
el('aw-sources').replaceChildren();
for(const s of d.sources){const p=document.createElement('p');p.textContent=s.name+' — '+(s.last_status||'لم يفحص بعد')+' · '+fmt(s.last_checked_at);el('aw-sources').append(p);}
}catch(e){txt('aw-state',e.message==='انتهت الجلسة — سجّل الدخول'?e.message:'تعذر تحديث الحالة — البيانات المعروضة قديمة');}
finally{setTimeout(refresh,5000);}}
refresh();
})();
</script>'''
