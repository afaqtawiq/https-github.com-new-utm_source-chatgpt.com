"""One official-mail delivery report after confirmed social publication."""
import json
from app.storage import db, rows, utcnow
from app import spacemail

with db() as c:
    c.execute('''CREATE TABLE IF NOT EXISTS publication_mail_reports(
        content_id BIGINT PRIMARY KEY REFERENCES social_content(id),user_id BIGINT NOT NULL,
        status TEXT NOT NULL,message_id TEXT,created_at TIMESTAMPTZ NOT NULL)''')


def tick():
    from app.production_monitor import sender_ready
    from app import social_publishing as publishing
    # Read existing provider receipts only; never create or repeat a post.
    for pending in rows("""SELECT p.* FROM social_publications p JOIN spacemail_connections m ON m.user_id=p.approved_by
        WHERE p.status IN ('scheduled','publishing') AND p.provider_post_id IS NOT NULL
        AND m.enabled=TRUE AND p.scheduled_at<=? ORDER BY p.id LIMIT 10""", (utcnow(),)):
        if not sender_ready(pending['approved_by'],spacemail.ADDRESS):
            continue
        try:
            key,_=publishing.connection()
            result=publishing.provider_request(key,'GET','/posts/'+publishing.identifier(pending['provider_post_id']))
            pid,state,results=publishing.publication_result(result,json.loads(pending['payload_json'])['platforms'])
            if pid==pending['provider_post_id']:
                publishing.save_result(pending['content_id'],pid,state,results)
        except publishing.PublishingError:
            continue
    for row in rows('''SELECT p.content_id,p.approved_by,p.results_json,c.title FROM social_publications p
        JOIN social_content c ON c.id=p.content_id
        JOIN spacemail_connections m ON m.user_id=p.approved_by
        WHERE p.status='published' AND c.status='published' AND m.enabled=TRUE AND p.updated_at>=m.updated_at
        AND NOT EXISTS(SELECT 1 FROM publication_mail_reports r WHERE r.content_id=p.content_id)
        ORDER BY p.id LIMIT 10'''):
        uid=row['approved_by']
        if not sender_ready(uid,spacemail.ADDRESS):
            continue
        results=json.loads(row['results_json'])
        if not results or any(r.get('status')!='published' or not r.get('url') for r in results):
            continue
        with db() as c:
            claim=c.execute("INSERT INTO publication_mail_reports(content_id,user_id,status,created_at) VALUES(%s,%s,'sending',%s) ON CONFLICT DO NOTHING RETURNING content_id",
                            (row['content_id'],uid,utcnow())).fetchone()
        if not claim:
            continue
        body='تم تأكيد نشر المحتوى التالي على الحسابات المدرجة:\n'+row['title']+'\n\n'
        body+='\n'.join(str(r['platform'])+': '+r['url'] for r in results)
        body+='\n\nهذا التقرير يؤكد النشر فقط، ولا يدل على عدد المشاهدات أو نتائج التسويق.'
        try:
            mid=spacemail.send(uid,spacemail.ADDRESS,'آفاق طويق — تقرير اكتمال النشر',body)
            status='accepted'
        except Exception:
            mid,status=None,'uncertain'
        with db() as c:
            c.execute('UPDATE publication_mail_reports SET status=%s,message_id=%s WHERE content_id=%s',(status,mid,row['content_id']))
    with db() as c:
        c.execute("""UPDATE publication_mail_reports r SET status='received' WHERE status='accepted'
            AND EXISTS(SELECT 1 FROM spacemail_inbox i WHERE i.user_id=r.user_id AND i.message_id=r.message_id)""")
