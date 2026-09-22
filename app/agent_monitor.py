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
    # Update the current step in place; retain only the terminal result in activity.
    if status != 'running':
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


def snapshot(compact=False):
    from app.storage import rows, one, utcnow
    ensure_schema()
    latest = run_view(one('SELECT * FROM agent_runs ORDER BY id DESC LIMIT 1'))
    if compact:
        event = one("SELECT action,entity_id,created_at FROM activity WHERE action IN ('create_outbound_draft','request_send_approval','approve_external_send','send_approved_message','freight_owner_contact_submitted','freight_driver_offer_prepared') ORDER BY id DESC LIMIT 1")
        return {'run': latest, 'latest_event': ({'label': ACTION_LABELS[event['action']], 'at': event['created_at'], 'entity_id': event['entity_id']} if event else None), 'updated_at': utcnow()}
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
    return JSONResponse(jsonable_encoder(snapshot(compact=True)), headers={'Cache-Control': 'no-store'})


def monitor_widget():
    return '''
<style>
#agent-watch{display:flex;align-items:center;gap:12px;position:relative;overflow:hidden;border:1px solid #b79042;border-radius:12px;background:#102b3e;padding:12px 14px;margin:12px 0;color:#f3f7fa;min-height:54px}
#aw-state{color:#ffd978;font-weight:700;flex-shrink:0;font-size:13px;max-width:35%}
#aw-window{min-width:0;flex:1;overflow:hidden}
#aw-line{width:max-content;white-space:nowrap;font-size:14px;color:#ff6666}
#aw-pause{flex-shrink:0;background:transparent;border:1px solid #496071;color:#dce8ef;border-radius:7px;padding:4px 8px;cursor:pointer}
#aw-progress{position:absolute;bottom:0;right:0;width:100%;height:3px;accent-color:#e7b64b;border:0}
@media(prefers-reduced-motion:reduce){#aw-window{overflow-x:auto}}
</style>
<div id="agent-watch" aria-label="متابعة الوكيل مباشرة">
<span id="aw-state" role="status">الوكيل</span>
<div id="aw-window"><div id="aw-line">جارٍ جلب الحالة…</div></div>
<button id="aw-pause" type="button" aria-label="إيقاف حركة الشريط" aria-pressed="false">إيقاف الحركة</button>
<progress id="aw-progress" value="0" max="1" aria-label="المصادر المنتهية"></progress>
</div>
<script>
(()=>{
const el=id=>document.getElementById(id), txt=(id,v)=>el(id).textContent=v;
const fmt=v=>v?new Date(v).toLocaleTimeString('ar-SA',{timeZone:'Asia/Riyadh'}):'';
let motion=null,paused=false,lastLine='';
const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
function animate(){
 if(motion)motion.cancel();
 motion=null;
 const distance=el('aw-line').scrollWidth-el('aw-window').clientWidth;
 if(distance>0&&!reduced.matches){
  motion=el('aw-line').animate([{transform:'translateX(0)'},{transform:'translateX('+distance+'px)'}],{duration:Math.max(12000,distance*45),iterations:Infinity,direction:'alternate',easing:'linear'});
  if(paused)motion.pause();
 }
}
function line(value){if(value!==lastLine){lastLine=value;txt('aw-line',value);animate();}}
el('aw-pause').onclick=()=>{
 paused=!paused;
 if(motion){if(paused)motion.pause();else motion.play();}
 el('aw-pause').setAttribute('aria-pressed',String(paused));
 el('aw-pause').setAttribute('aria-label',paused?'تشغيل حركة الشريط':'إيقاف حركة الشريط');
 txt('aw-pause',paused?'تشغيل الحركة':'إيقاف الحركة');
};
new ResizeObserver(animate).observe(el('aw-window'));
reduced.addEventListener('change',animate);
async function refresh(){
try{
const res=await fetch('/api/agent-monitor',{cache:'no-store',signal:AbortSignal.timeout(10000)});
if(!res.ok)throw new Error(res.status===401?'انتهت الجلسة — سجّل الدخول':'تعذر تحديث الحالة');
const d=await res.json(),r=d.run,s=r.result||{},e=d.latest_event;
const newer=e&&(!r.updated_at||new Date(e.at)>new Date(r.updated_at));
txt('aw-state',r.status==='running'?'● يعمل الآن':r.status==='stale'?'⚠ تأخر التحديث':r.status==='failed'?'⚠ تعطل التنفيذ':newer?'آخر إجراء':r.status==='partial'?'⚠ آخر نتيجة':'آخر نتيجة');
let message=r.step||r.label||'بانتظار مهمة';
if(newer&&r.status!=='running')message=e.label+(e.entity_id?' · #'+e.entity_id:'')+' · '+fmt(e.at);
else if(r.total)message+=' · '+r.completed+' من '+r.total+' مصادر · فرص موثقة: '+((s.opportunities||0)+(s.external_opportunities||0))+' · مصادر متعذرة: '+(s.errors||0)+' · '+fmt(r.updated_at);
line(message);
el('agent-watch').title='آخر قراءة: '+fmt(d.updated_at);
el('aw-progress').max=Math.max(1,r.total||0);el('aw-progress').value=r.completed||0;
}catch(e){txt('aw-state','⚠ الاتصال');line(e.message==='انتهت الجلسة — سجّل الدخول'?e.message:'تعذر تحديث الحالة — البيانات المعروضة قديمة');}
finally{setTimeout(refresh,5000);}}
refresh();
})();
</script>'''
