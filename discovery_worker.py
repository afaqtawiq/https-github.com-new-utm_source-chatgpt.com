from app.storage import init_db,rows,execute,utcnow
from app.discovery import fetch_public
import os

init_db(os.getenv('ADMIN_EMAIL','admin@afaaqtuwaiq.local'),os.getenv('ADMIN_PASSWORD','ChangeMe-Now-2026!'))

def run():
    scanned=new_signals=new_opportunities=0
    for source in rows('SELECT * FROM source_watches WHERE enabled=1 ORDER BY id'):
        scanned+=1
        try:
            result=fetch_public(source['url']);now=utcnow()
            execute('UPDATE source_watches SET last_status=?,last_checked_at=? WHERE id=?',('ok',now,source['id']))
            existing=rows('SELECT id FROM discovered_signals WHERE url=?',(result['url'],))
            if not existing and result['score']>=25:
                signal_id=execute('INSERT INTO discovered_signals(source_watch_id,title,url,company_name,excerpt,score,matched_terms,status,discovered_at) VALUES(?,?,?,?,?,?,?,?,?)',(source['id'],result['title'],result['url'],result['title'],result['excerpt'],result['score'],', '.join(result['matched_terms']),'new',now));new_signals+=1
                if result['score']>=60:
                    oid=execute('INSERT INTO opportunities(company_name,source_url,signal,score,stage,estimated_value,currency,owner,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(result['title'],result['url'],result['excerpt'],result['score'],'research',0,'SAR','Discovery Worker',now,now))
                    execute('UPDATE discovered_signals SET status=?,opportunity_id=? WHERE id=?',('promoted',oid,signal_id));new_opportunities+=1
        except Exception:
            execute('UPDATE source_watches SET last_status=?,last_checked_at=? WHERE id=?',('scan_error',utcnow(),source['id']))
    print('scanned=',scanned,'new_signals=',new_signals,'new_opportunities=',new_opportunities)

if __name__=='__main__':run()
