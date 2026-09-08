from fastapi import APIRouter,Request,HTTPException
from app.storage import get_session,rows,one
from discovery_worker import run

router=APIRouter()

def admin(request:Request):
    session=get_session(request.cookies.get('gla_session'))
    if not session or session.get('role')!='admin':
        raise HTTPException(status_code=403,detail='admin session required')
    return session

@router.post('/api/v7/admin/discovery/verify')
def verify_discovery(request:Request):
    admin(request)
    scan=run()
    sources=rows('SELECT id,name,url,last_status,last_checked_at FROM source_watches WHERE enabled=1 ORDER BY id')
    signals=rows('SELECT id,source_watch_id,title,url,score,status,opportunity_id,discovered_at FROM discovered_signals ORDER BY id DESC LIMIT 20')
    opportunities=rows("SELECT id,company_name,source_url,score,stage,owner,created_at FROM opportunities WHERE owner='Discovery Worker' ORDER BY id DESC LIMIT 20")
    return {
        'ok':True,
        'scan':scan,
        'counts':{
            'sources':one('SELECT COUNT(*) n FROM source_watches WHERE enabled=1')['n'],
            'signals':one('SELECT COUNT(*) n FROM discovered_signals')['n'],
            'opportunities':one('SELECT COUNT(*) n FROM opportunities')['n'],
            'worker_opportunities':one("SELECT COUNT(*) n FROM opportunities WHERE owner='Discovery Worker'")['n'],
        },
        'sources':sources,
        'signals':signals,
        'worker_opportunities':opportunities,
    }
