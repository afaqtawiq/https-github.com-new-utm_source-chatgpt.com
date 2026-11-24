"""Cinematic video desk on isolated PostgreSQL. MOCK level: the storyboard model, fal pricing and the advert-studio
generation are simulated; the real advert_jobs/advert_exports tables, «نفذ» codes and team-video store are used.
Nothing is generated, paid, published or sent."""
from decimal import Decimal
import json
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GOOD = {'title': 'رحلة شحنتك من جدة', 'caption': 'شحنتك وصلت الميناء؟\nنخلصها وننقلها لمستودعك.\nراسلنا واتساب\n#تخليص_جمركي #آفاق_طويق',
        'scenes': [{'text': 'شحنتك وصلت؟', 'voice': 'شُحْنَتُكَ وَصَلَتِ المِينَاءَ؟',
                    'image': 'Low wide shot of a navy tractor-trailer carrying a forty foot container leaving a Jeddah container terminal at golden hour, gantry cranes behind, 35mm lens, warm rim light',
                    'motion': 'Slow ground-level tracking alongside the truck as it drives forward in its lane, wheels rotating with real road contact, no sudden turns'}] * 4,
        'end_text': 'اطلب عرض سعر لشحنتك', 'end_voice': 'آفَاقُ طُوَيْق... اطْلُبْ عَرْضَ سِعْرٍ لِشَحْنَتِكَ الآن.'}


def run():
    from app import advert_studio, transport_desk, video_director as vd, video_publish
    from app.storage import db
    video_publish.init(); vd.init()
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS whatsapp_voice_pending(token TEXT PRIMARY KEY, sender TEXT, conversation_id TEXT,
            command TEXT, expires_at TIMESTAMPTZ, consumed BOOLEAN NOT NULL DEFAULT FALSE)''')
        uid = c.execute('SELECT id FROM users ORDER BY id LIMIT 1').fetchone()['id']

    # 1) Storyboard guard: a clean plan becomes 4 generated scenes + the branded end card in the studio's format.
    plan = vd.clean_storyboard(GOOD, 'x')
    assert len(plan['scenes']) == 5 and plan['scenes'][4]['image'] == '' and plan['scenes'][0]['image'].startswith('Low wide')
    assert plan['scenes'][4]['text'] == 'اطلب عرض سعر لشحنتك' and plan['caption'].startswith('شحنتك')
    # Prices, digits, guarantees, Latin text in Arabic lines, Arabic in prompts or too few scenes are refused.
    for broken in ({**GOOD, 'scenes': [{**GOOD['scenes'][0], 'voice': 'نضمن لك الفسح'}] * 4},
                   {**GOOD, 'scenes': [{**GOOD['scenes'][0], 'text': 'خصم 20 بالمية'}] * 4},
                   {**GOOD, 'scenes': [{**GOOD['scenes'][0], 'image': 'شاحنة في الميناء ' * 10}] * 4},
                   {**GOOD, 'scenes': GOOD['scenes'][:3]}, None):
        assert vd.clean_storyboard(broken, 'x') is None
    # An unsafe caption is replaced by the approved one; a bad end line falls back to the approved end card.
    safe = vd.clean_storyboard({**GOOD, 'caption': 'أرخص سعر 1500 ريال', 'end_text': 'نضمن'}, 'x')
    from app.advert_spec import SCENES as APPROVED
    assert '1500' not in safe['caption'] and safe['scenes'][4]['voice'] == APPROVED[4]['voice']
    # Without the model the approved default commercial is used — still vertical and tagged as a WhatsApp order.
    with patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}):
        fallback, used = vd.storyboard('فيديو عن جدة')
    assert used and fallback['ratios'] == ['9:16'] and fallback['origin'] == vd.ORIGIN

    # 2) Request → priced draft + «نفذ» for the spend; nothing paid submitted.
    def prepare(plan, user_id):
        with db() as c:
            return c.execute('''INSERT INTO advert_jobs(status,plan_json,total_cost,credential_version,quote_expires_at,created_by,created_at,updated_at)
                VALUES('draft',%s,3.20,NOW(),NOW()+INTERVAL '15 minutes',%s,NOW(),NOW()) RETURNING id''',
                (json.dumps(plan, ensure_ascii=False), user_id)).fetchone()['id']
    with patch.object(vd, 'storyboard', lambda topic, ratios: ({**plan, 'ratios': list(ratios), 'origin': vd.ORIGIN}, False)), \
         patch.object(advert_studio, 'prepare_plan', prepare), patch.object(vd, '_system_user', lambda: uid), \
         patch.object(transport_desk, 'manager_chat', lambda c: ('966500000001', 'conv-m')):
        text = vd.start('فيديو احترافي عن التخليص في ميناء جدة', 'المدير', 'both')
        again = None
        with db() as c:
            job = c.execute('SELECT job_id FROM video_director_jobs').fetchone()['job_id']
            action = json.loads(c.execute('SELECT command FROM whatsapp_voice_pending').fetchone()['command'].partition(':')[2])
            ratios = json.loads(c.execute('SELECT plan_json FROM advert_jobs WHERE id=%s', (job,)).fetchone()['plan_json'])['ratios']
    assert '3.20 دولار' in text and 'نفذ ' in text and 'شحنتك وصلت؟' in text and 'أفقي 16:9' in text, text
    assert action == {'tool': 'cinematic_approve', 'job_id': job} and ratios == ['9:16', '16:9']

    # 3) «نفذ» refreshes the quote and approves it once; a price jump over 25% stops before any spend.
    calls = []
    def requote(job_id, user_id, new=Decimal('3.30')):
        with db() as c:
            c.execute("UPDATE advert_jobs SET total_cost=%s,quote_expires_at=NOW()+INTERVAL '15 minutes' WHERE id=%s", (new, job_id))
    def approve(job_id, user_id, stamp):
        calls.append(stamp)
        with db() as c:
            c.execute("UPDATE advert_jobs SET status='running',approved_by=%s WHERE id=%s", (user_id, job_id))
    with patch.object(vd, '_system_user', lambda: uid), patch.object(advert_studio, 'approve', approve), \
         patch.object(advert_studio, 'requote', lambda j, u: requote(j, u, Decimal('9.00'))):
        jumped = vd.approve(job)
    assert 'ارتفعت تكلفة' in jumped and not calls
    with db() as c:
        c.execute("UPDATE advert_jobs SET total_cost=3.20 WHERE id=%s", (job,))
    with patch.object(vd, '_system_user', lambda: uid), patch.object(advert_studio, 'approve', approve), \
         patch.object(advert_studio, 'requote', requote):
        ok = vd.approve(job)
        twice = vd.approve(job)
    assert '✅ بدأ إنتاج' in ok and '3.30' in ok and len(calls) == 1 and 'لم يتغير شيء' in twice
    with patch.object(vd, 'storyboard', lambda *a: (_ for _ in ()).throw(AssertionError('no new job while one runs'))):
        assert 'قيد الإنتاج' in vd.start('فيديو ثاني')

    # 4) Finished → stored as a team video, manager gets preview + a separate publish «نفذ» (and the 16:9 link), once.
    with db() as c:
        c.execute("UPDATE advert_jobs SET status='complete' WHERE id=%s", (job,))
        for ratio, token in (('9:16', 'v' * 48), ('16:9', 'h' * 48)):
            c.execute('''INSERT INTO advert_exports(token,job_id,ratio,payload,duration,width,height,created_at)
                VALUES(%s,%s,%s,%s,25,1080,1920,NOW())''', (token, job, ratio, b'mp4-' + ratio.encode()))
    sent = []
    with patch.object(vd, '_deliver', sent.append), patch.object(transport_desk, 'manager_chat', lambda c: ('966500000001', 'conv-m')):
        vd.sweep(); vd.sweep()
    assert len(sent) == 1 and '/media/team-video/' in sent[0] and '/media-exports/' + 'h' * 48 in sent[0] and 'نفذ ' in sent[0]
    with db() as c:
        row = c.execute('SELECT d.team_video_id, t.video, t.caption FROM video_director_jobs d JOIN team_videos t ON t.id=d.team_video_id').fetchone()
        codes = [json.loads(r['command'].partition(':')[2]) for r in c.execute('SELECT command FROM whatsapp_voice_pending').fetchall()]
    assert bytes(row['video']) == b'mp4-9:16' and '0507665873' in row['caption']
    assert {'tool': 'publish_video', 'video_id': row['team_video_id']} in codes
    assert any('سينمائي' in line and 'جاهز' in line for line in vd.status_lines())

    # 5) A stuck job is reported once with its reason; nothing is regenerated.
    with db() as c:
        stuck = c.execute('''INSERT INTO advert_jobs(status,plan_json,total_cost,credential_version,quote_expires_at,created_by,last_error,created_at,updated_at)
            VALUES('needs_review','{}',2,NOW(),NOW(),%s,'انقطع تأكيد طلب مدفوع',NOW(),NOW()) RETURNING id''', (uid,)).fetchone()['id']
        c.execute('INSERT INTO video_director_jobs(job_id,topic,created_at) VALUES(%s,%s,NOW())', (stuck, 'x'))
    sent.clear()
    with patch.object(vd, '_deliver', sent.append):
        vd.sweep(); vd.sweep()
    assert len(sent) == 1 and 'انقطع تأكيد طلب مدفوع' in sent[0]

    # 6) The GM tool: only the manager orders a paid video.
    from app import command_agent
    assert any(t['name'] == 'cinematic_video' for t in command_agent.TOOLS) and 'cinematic_video' in command_agent.HANDLERS
    with patch.object(command_agent, '_member', lambda: {'name': 'موظف', 'manager': False}):
        assert 'المدير فقط' in command_agent.tool_cinematic_video(None, {'topic': 'x'})
    from app import virtual_office
    assert 'cinematic_video' in virtual_office.DEPARTMENTS['sales']['tools']


def main():
    import psycopg
    from psycopg import sql
    url = os.environ.get('AFAAQ_TEST_DATABASE_URL', '')
    t = urlsplit(url)
    if t.scheme not in ('postgres', 'postgresql') or t.hostname not in ('localhost', '127.0.0.1') or t.path != '/afaaq_test' or t.query:
        raise RuntimeError('Requires local disposable afaaq_test')
    schema = 'video_director_' + secrets.token_hex(5)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        env = {'DATABASE_URL': url + '?' + urlencode({'options': '-c search_path=' + schema}, quote_via=quote),
               'DISCOVERY_AUTO_ENABLED': '0', 'ENABLE_EXTERNAL_ACTIONS': '0', 'ANTHROPIC_API_KEY': '',
               'TOKEN_ENCRYPTION_KEY': secrets.token_urlsafe(32), 'ADMIN_EMAIL': 'bootstrap@fixture.invalid',
               'ADMIN_PASSWORD': secrets.token_urlsafe(32), 'BROWSER_COOKIE_SECURE': '0'}
        with patch.dict(os.environ, env):
            import app.main  # noqa: F401  full schema (users, activity, social_content, advert tables)
            run()
    finally:
        with psycopg.connect(url, autocommit=True) as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print('PASS: cinematic video — storyboard guarded, cost approved once by «نفذ», preview + separate publish code, nothing paid or published.')


if __name__ == '__main__':
    main()
