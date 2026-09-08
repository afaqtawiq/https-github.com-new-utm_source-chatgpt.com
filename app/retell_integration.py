import os, json, re, time, hmac, hashlib
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.storage import db, utcnow, log

router=APIRouter()
RETELL_API_KEY=os.getenv('RETELL_API_KEY','')
RETELL_WEBHOOK_KEY=os.getenv('RETELL_WEBHOOK_KEY','')

def _init():
    ddl=[
      '''CREATE TABLE IF NOT EXISTS retell_calls(id BIGSERIAL PRIMARY KEY,call_id TEXT UNIQUE NOT NULL,agent_id TEXT,opportunity_id BIGINT REFERENCES opportunities(id) ON DELETE SET NULL,event_type TEXT,status TEXT,direction TEXT,from_number TEXT,to_number TEXT,disconnection_reason TEXT,transcript TEXT,analysis_json TEXT,summary TEXT,outcome TEXT,interested TEXT,requested_service TEXT,preferred_follow_up TEXT,quote_requested INTEGER NOT NULL DEFAULT 0,callback_requested INTEGER NOT NULL DEFAULT 0,started_at TIMESTAMPTZ,ended_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)''',
      '''CREATE TABLE IF NOT EXISTS retell_webhook_events(id BIGSERIAL PRIMARY KEY,call_id TEXT,event_type TEXT NOT NULL,payload_json TEXT NOT NULL,received_at TIMESTAMPTZ NOT NULL)'''
    ]
    with db() as c:
        for q in ddl:c.execute(q)
_init()

def _verify(raw:bytes,sig:str)->bool:
    if not RETELL_WEBHOOK_KEY or not sig:return False
    m=re.fullmatch(r'v=(\d+),d=(.+)',sig.strip())
    if not m:return False
    ts,digest=m.groups()
    try:
        if abs(int(time.time()*1000)-int(ts))>300000:return False
    except Exception:return False
    expected=hmac.new(RETELL_WEBHOOK_KEY.encode(),raw+ts.encode(),hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,digest)

def _b(v):
    if isinstance(v,bool):return 1 if v else 0
    return 1 if str(v).lower() in ('true','yes','1') else 0

def _dt(ms):
    if not ms:return None
    import datetime
    try:return datetime.datetime.fromtimestamp(int(ms)/1000,datetime.timezone.utc)
    except Exception:return None

@router.post('/webhooks/retell')
async def retell_webhook(request:Request):
    raw=await request.body();sig=request.headers.get('x-retell-signature','')
    if not _verify(raw,sig):return JSONResponse({'detail':'invalid signature'},status_code=401)
    try:data=json.loads(raw)
    except Exception:return JSONResponse({'detail':'invalid json'},status_code=400)
    event=str(data.get('event') or 'unknown');call=data.get('call') or {};cid=str(call.get('call_id') or '')
    if not cid:return JSONResponse({'detail':'missing call_id'},status_code=400)
    analysis=call.get('call_analysis') or {};custom=analysis.get('custom_analysis_data') or {}
    metadata=call.get('metadata') or {};opp=metadata.get('opportunity_id')
    try:opp=int(opp) if opp is not None else None
    except Exception:opp=None
    summary=str(analysis.get('call_summary') or custom.get('call_summary') or '')[:4000]
    outcome=str(custom.get('call_outcome') or '')[:100]
    interested=str(custom.get('interested') or '')[:50]
    service=str(custom.get('requested_service') or '')[:300]
    follow=str(custom.get('preferred_follow_up') or '')[:50]
    now=utcnow()
    with db() as c:
        c.execute('INSERT INTO retell_webhook_events(call_id,event_type,payload_json,received_at) VALUES(%s,%s,%s,%s)',(cid,event,json.dumps(data,ensure_ascii=False),now))
        c.execute('''INSERT INTO retell_calls(call_id,agent_id,opportunity_id,event_type,status,direction,from_number,to_number,disconnection_reason,transcript,analysis_json,summary,outcome,interested,requested_service,preferred_follow_up,quote_requested,callback_requested,started_at,ended_at,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(call_id) DO UPDATE SET event_type=EXCLUDED.event_type,status=EXCLUDED.status,disconnection_reason=EXCLUDED.disconnection_reason,transcript=COALESCE(NULLIF(EXCLUDED.transcript,''),retell_calls.transcript),analysis_json=COALESCE(NULLIF(EXCLUDED.analysis_json,''),retell_calls.analysis_json),summary=COALESCE(NULLIF(EXCLUDED.summary,''),retell_calls.summary),outcome=COALESCE(NULLIF(EXCLUDED.outcome,''),retell_calls.outcome),interested=COALESCE(NULLIF(EXCLUDED.interested,''),retell_calls.interested),requested_service=COALESCE(NULLIF(EXCLUDED.requested_service,''),retell_calls.requested_service),preferred_follow_up=COALESCE(NULLIF(EXCLUDED.preferred_follow_up,''),retell_calls.preferred_follow_up),quote_requested=GREATEST(retell_calls.quote_requested,EXCLUDED.quote_requested),callback_requested=GREATEST(retell_calls.callback_requested,EXCLUDED.callback_requested),ended_at=COALESCE(EXCLUDED.ended_at,retell_calls.ended_at),updated_at=EXCLUDED.updated_at''',(cid,call.get('agent_id'),opp,event,call.get('call_status'),call.get('direction'),call.get('from_number'),call.get('to_number'),call.get('disconnection_reason'),call.get('transcript') or '',json.dumps(analysis,ensure_ascii=False) if analysis else '',summary,outcome,interested,service,follow,_b(custom.get('quote_requested')),_b(custom.get('callback_requested')),_dt(call.get('start_timestamp')),_dt(call.get('end_timestamp')),now,now))
        if event=='call_analyzed' and opp:
            if interested.lower() in ('interested','yes','true'):
                c.execute("UPDATE opportunities SET stage=CASE WHEN stage IN ('new','qualified','contacted') THEN 'contacted' ELSE stage END,updated_at=%s WHERE id=%s",(now,opp))
            if outcome in ('interested-transferred','quote-requested') or _b(custom.get('quote_requested')):
                c.execute("UPDATE opportunities SET stage=CASE WHEN stage IN ('new','qualified','contacted') THEN 'negotiation' ELSE stage END,updated_at=%s WHERE id=%s",(now,opp))
    if event=='call_analyzed' and opp:log(None,'retell_call_analyzed','opportunity',opp,'Retell call analyzed: '+(outcome or 'completed'))
    return JSONResponse({},status_code=204)

@router.get('/api/v7/retell/status')
def retell_status():
    return {
        'api_configured':bool(RETELL_API_KEY),
        'webhook_configured':bool(RETELL_WEBHOOK_KEY),
        'webhook':'/webhooks/retell',
        'signature_verification':True,
        'external_calls_automatic':False,
    }
