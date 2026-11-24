"""Owner, 24 Nov 2026: «كم العدد» must answer from the reading that just finished, not start another one."""
import json, os, secrets, sys
from pathlib import Path
from urllib.parse import quote, urlencode
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run():
    from app import agent_runner as ar
    from app.storage import db, utcnow
    ar.init()
    p = {'which': 'import', 'party': 'سلة', 'since': '2026-11-01', 'pages': 20, 'purpose': 'count', 'month': '2026-11'}
    csv = 'رقم المرجع,رقم البيان,التاريخ,التفاصيل\n1,422961,04/11/2026,x\n2,422999,05/11/2026,y\n3,400000,30/10/2026,z\n'
    with db() as c:
        tid = c.execute("INSERT INTO runner_tasks(kind,params_json,status,created_at) VALUES('fasah_declarations',%s,'running',%s) RETURNING id",
                        (json.dumps(p, ensure_ascii=False), utcnow())).fetchone()['id']
    assert ar.recent_count('سلة', '2026-11') == ('running', tid)
    with db() as c:
        c.execute("UPDATE runner_tasks SET status='done' WHERE id=%s", (tid,))
        c.execute("INSERT INTO runner_files(task_id,name,mime,size,sha256,verified,data,created_at) VALUES(%s,'f.csv','text/csv',1,'x',TRUE,%s,%s)",
                  (tid, csv.encode('utf-8-sig'), utcnow()))
    state, text = ar.recent_count('سلة', '2026-11')
    assert state == 'done' and ': 2 بيان' in text and '422961' in text and f'#{tid}' in text, text
    assert ar.recent_count('سلة', '2026-10') is None
    print('fasah count reuse: OK')


def main():
    import psycopg
    from psycopg import sql
    url = os.environ['AFAAQ_TEST_DATABASE_URL']
    schema = 'count_reuse_' + secrets.token_hex(4)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        os.environ['DATABASE_URL'] = url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote)
        run()
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    main()
