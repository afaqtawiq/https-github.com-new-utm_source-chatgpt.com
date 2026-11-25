"""Team video → social publishing (owner request, Nov 2026).

The manager sends a video on WhatsApp (the text with it becomes the post caption). The agent stores it at a public
URL and prepares «نفذ CODE». After confirmation it publishes to Facebook (page video), Instagram (Reels),
YouTube and TikTok (through Zernio) in the background and sends the manager the result of every platform.
"""
import json
import re
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.storage import db, utcnow

router = APIRouter()
VIDEO_TYPES = {'video/mp4', 'video/quicktime', 'video/3gpp', 'application/octet-stream', ''}
FOOTER = '\n\nآفاق طويق للتخليص الجمركي والنقل\nواتساب: 0507665873 — 0530130435'
DEFAULT = ('آفاق طويق — تخليص جمركي ونقل بري من الميناء إلى مستودعك، بخبرة وسرعة واحترافية.\n'
           '#تخليص_جمركي #نقل_بري #آفاق_طويق #السعودية')


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS team_videos(id BIGSERIAL PRIMARY KEY, video BYTEA NOT NULL, mime TEXT NOT NULL,
            caption TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ready', results_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('ALTER TABLE team_videos ADD COLUMN IF NOT EXISTS ai_generated BOOLEAN NOT NULL DEFAULT FALSE')


def video_index(message):
    for index, item in enumerate(message.get('attachments') or []):
        if isinstance(item, dict) and (str(item.get('type', '')).lower() == 'video' or str(item.get('mimeType', '')).lower().startswith('video/')):
            return index
    return None


def url(vid):
    from app.daily_poster import base_url
    return base_url() + '/media/team-video/' + str(vid) + '.mp4'


@router.api_route('/media/team-video/{name}', methods=['GET', 'HEAD'])  # platforms probe the file with HEAD before pulling it
def public_video(name: str):
    stem, _, ext = name.partition('.')
    if ext != 'mp4' or not stem.isdigit():
        raise HTTPException(404)
    with db() as c:
        row = c.execute('SELECT video,mime FROM team_videos WHERE id=%s', (int(stem),)).fetchone()
    if not row:
        raise HTTPException(404)
    return Response(bytes(row['video']), media_type='video/mp4', headers={'Cache-Control': 'public, max-age=86400'})


def caption_for(text):
    text = (text or '').strip()
    words = len(text.split())
    body = text if words >= 4 else DEFAULT
    from app.daily_poster import base_url
    return body + ('' if '0507665873' in body else FOOTER + '\n🧮 احسب تكلفة شحنتك: ' + base_url() + '/price?src=video')


def save(data, mime, text, actor, ai_generated=False):
    init()
    with db() as c:
        return c.execute('INSERT INTO team_videos(video,mime,caption,created_by,created_at,ai_generated) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id',
                         (data, mime or 'video/mp4', caption_for(text), actor, utcnow(), bool(ai_generated))).fetchone()['id']


# ---------- per-platform captions (publishing playbook) ----------

URL = re.compile(r'https?://\S+')
HASHTAG = re.compile(r'#[\w\u0600-\u06FF_]+')
LIMITS = {'twitter': 270, 'threads': 480, 'bluesky': 290, 'pinterest': 480, 'snapchat': 160, 'telegram': 1000, 'linkedin': 2900}


def adapt(platform, text):
    """One caption → the version each platform rewards: X/Bluesky short hook + WhatsApp + 2 tags and no links
    (X bills a post with a link ×13), Threads/Pinterest short with 3 tags, LinkedIn the full professional text."""
    text = (text or '').strip()
    if platform == 'linkedin':
        return text[:LIMITS['linkedin']]
    tags = HASHTAG.findall(text)
    body = [l.strip() for l in URL.sub('', HASHTAG.sub('', text)).split('\n') if l.strip() and not l.strip().startswith('🧮')]
    limit = LIMITS.get(platform, 480)
    keep = {'twitter': 2, 'bluesky': 2, 'snapchat': 1}.get(platform, 3)
    contact = 'واتساب: 0507665873'
    lines = [l for l in body if '0507665873' not in l and '0530130435' not in l and 'واتساب' not in l]
    out = []
    for line in lines:
        candidate = '\n'.join(out + [line, contact, ' '.join(tags[:keep])])
        if len(candidate) > limit:
            break
        out.append(line)
    if not out and lines:
        out = [lines[0][:max(20, limit - len(contact) - 40)]]
    return '\n'.join(out + [contact, ' '.join(tags[:keep])]).strip()[:limit]


# ---------- publishing ----------

def facebook(conn, video_url, text):
    from app.meta_connect import graph
    r = graph('POST', conn['page_id'] + '/videos', conn['token'], data={'file_url': video_url, 'description': text, 'published': 'true'})
    return 'https://www.facebook.com/' + str(r.get('id'))


def instagram(conn, video_url, text):
    from app.meta_connect import MetaError, graph
    if not conn.get('ig_id'):
        raise MetaError('لا يوجد حساب إنستغرام مرتبط.')
    creation = graph('POST', conn['ig_id'] + '/media', conn['token'],
                     data={'media_type': 'REELS', 'video_url': video_url, 'caption': text, 'share_to_feed': 'true'})['id']
    for _ in range(60):
        status = graph('GET', creation, conn['token'], params={'fields': 'status_code'}).get('status_code')
        if status == 'FINISHED':
            break
        if status in ('ERROR', 'EXPIRED'):
            raise MetaError('رفض إنستغرام معالجة الفيديو (المدة أو الصيغة).')
        time.sleep(5)
    media = graph('POST', conn['ig_id'] + '/media_publish', conn['token'], data={'creation_id': creation})['id']
    try:
        return graph('GET', media, conn['token'], params={'fields': 'permalink'}).get('permalink') or media
    except MetaError:
        return media


# ---------- every other connected Zernio account (LinkedIn, X, Threads, Pinterest, Bluesky, Telegram, Snapchat) ----------

EXTRA = {'linkedin': 'لينكدإن', 'twitter': 'إكس', 'threads': 'ثريدز', 'pinterest': 'بنترست', 'bluesky': 'بلوسكاي',
         'telegram': 'تيليجرام', 'snapchat': 'سناب شات'}
NOT_CONNECTED_HINT = {
    'linkedin': 'اربط صفحة الشركة في Zernio (مجاني ضمن الاشتراك)',
    'twitter': 'اربط @afaqtql0 في Zernio — يتطلب بطاقة في Zernio وX يحسب تقريبًا 0.015$ لكل منشور',
    'threads': 'اربط حساب ثريدز في Zernio',
    'snapchat': 'النشر الآلي لسناب غير متاح بعد في Zernio (بانتظار موافقة سناب) — انشره يدويًا من my.snapchat.com',
}


def extra_accounts(key):
    """Active, healthy accounts on the dedicated Afaq Zernio key, one per platform (the first that can post)."""
    from app.social_zernio import PublishingError, identifier, provider_request
    data = provider_request(key, 'GET', '/accounts')
    found = {}
    for a in data.get('accounts') or []:
        if not isinstance(a, dict) or a.get('platform') not in EXTRA or a.get('isActive') is not True or a.get('platform') in found:
            continue
        try:
            account_id = identifier(a.get('_id'))
            health = provider_request(key, 'GET', '/accounts/' + account_id + '/health')
        except PublishingError:
            continue
        if health.get('tokenStatus', {}).get('valid') is True and health.get('permissions', {}).get('canPost') is not False:
            found[a['platform']] = {'accountId': account_id, 'username': str(a.get('username') or '')}
    return found


def extra_platforms(vid, video_url, text, ai_generated=False):
    """One Zernio post to every other connected platform, each with its own caption. Returns {label: result}."""
    from app.social_publishing import connection, save_result
    from app.social_zernio import provider_request, publication_result
    key, _ = connection()
    accounts = extra_accounts(key)
    results = {}
    for platform, hint in NOT_CONNECTED_HINT.items():
        if platform not in accounts:
            results[EXTRA[platform]] = '⚪ غير مربوط — ' + hint
    if not accounts:
        return results
    title = ('آفاق طويق | ' + text.split('\n')[0])[:95]
    platforms = []
    for platform, account in accounts.items():
        entry = {'platform': platform, 'accountId': account['accountId'], 'customContent': adapt(platform, text)}
        if platform == 'snapchat':
            entry['platformSpecificData'] = {'contentType': 'spotlight'}
        elif platform == 'pinterest':
            entry['platformSpecificData'] = {'title': title[:100], 'link': 'https://afaqtwiq.com'}
        platforms.append(entry)
    payload = {'content': adapt('linkedin', text), 'mediaItems': [{'type': 'video', 'url': video_url}], 'platforms': platforms,
               'publishNow': True, 'timezone': 'Asia/Riyadh', 'metadata': {'afaqTeamVideo': str(vid), 'aiGenerated': bool(ai_generated)}}
    from app.prospect_autopilot import system_user
    now, request_id, uid = utcnow(), str(uuid.uuid4()), system_user()
    label = '+'.join(sorted(accounts))
    with db() as c:
        content_id = c.execute('''INSERT INTO social_content(title,platform,content_type,body,media_url,scheduled_at,status,created_by,created_at,updated_at)
            VALUES(%s,%s,'video',%s,%s,%s,'submitting',%s,%s,%s) RETURNING id''',
            ('فيديو #' + str(vid) + ' — باقي المنصات', label[:60], text, video_url, now, uid, now, now)).fetchone()['id']
        c.execute('''INSERT INTO social_publications(content_id,request_id,status,scheduled_at,payload_json,approved_by,created_at,updated_at)
            VALUES(%s,%s,'submitting',%s,%s,%s,%s,%s)''', (content_id, request_id, now, json.dumps(payload), uid, now, now))
    try:
        response = provider_request(key, 'POST', '/posts', payload=payload, request_id=request_id)
        post_id, state, per = publication_result(response, platforms)
        save_result(content_id, post_id, state, per)
    except Exception as exc:
        save_result(content_id, None, 'needs_review', [], str(exc)[:300])
        for platform in accounts:
            results[EXTRA[platform]] = '❌ ' + str(exc)[:150]
        return results
    for item in per:
        name = EXTRA.get(item['platform'], item['platform'])
        if item['status'] in ('published', 'publishing', 'scheduled'):
            results[name] = '✅ ' + (item['url'] or item['status'])
        else:
            results[name] = '❌ ' + (item['error'] or item['status'])[:150]
    return results


def youtube_tiktok(vid, video_url, text, actor, ai_generated=False):
    from app.daily_poster import tiktok_settings
    from app.social_publishing import connection, save_result
    from app.social_zernio import creator_info, provider_request, publication_result, verified_accounts
    key, _ = connection()
    accounts = verified_accounts(key, ('youtube', 'tiktok'))
    title = ('آفاق طويق | ' + text.split('\n')[0])[:95]
    platforms = [{'platform': 'youtube', 'accountId': accounts['youtube']['accountId'],
                  'platformSpecificData': {'title': title, 'visibility': 'public', 'madeForKids': False, 'containsSyntheticMedia': bool(ai_generated)}}]
    tiktok = None
    try:
        tiktok = tiktok_settings(creator_info(key, accounts['tiktok']['accountId']))
    except Exception:
        tiktok = None
    if tiktok:
        platforms.append({'platform': 'tiktok', 'accountId': accounts['tiktok']['accountId'],
                          **({'platformSpecificData': {'videoMadeWithAi': True}} if ai_generated else {})})
    payload = {'content': text[:2200], 'title': title, 'mediaItems': [{'type': 'video', 'url': video_url}],
               'platforms': platforms, 'publishNow': True, 'timezone': 'Asia/Riyadh', 'metadata': {'afaqTeamVideo': str(vid)}}
    if tiktok:
        payload['tiktokSettings'] = tiktok
    from app.prospect_autopilot import system_user
    now, request_id, uid = utcnow(), str(uuid.uuid4()), system_user()
    with db() as c:
        content_id = c.execute('''INSERT INTO social_content(title,platform,content_type,body,media_url,scheduled_at,status,created_by,created_at,updated_at)
            VALUES(%s,%s,'video',%s,%s,%s,'submitting',%s,%s,%s) RETURNING id''',
            ('فيديو من واتساب الفريق #' + str(vid), 'YouTube+TikTok' if tiktok else 'YouTube', text, video_url, now, uid, now, now)).fetchone()['id']
        c.execute('''INSERT INTO social_publications(content_id,request_id,status,scheduled_at,payload_json,approved_by,created_at,updated_at)
            VALUES(%s,%s,'submitting',%s,%s,%s,%s,%s)''', (content_id, request_id, now, json.dumps(payload), uid, now, now))
    try:
        response = provider_request(key, 'POST', '/posts', payload=payload, request_id=request_id)
        post_id, state, results = publication_result(response, platforms)
        save_result(content_id, post_id, state, results)
    except Exception as exc:
        save_result(content_id, None, 'needs_review', [], str(exc)[:300])
        raise
    return state + ('' if tiktok else ' (تيك توك غير متاح الآن)')


def publish(vid, actor=''):
    """Background publish to all platforms; the manager gets one message with every result."""
    init()
    with db() as c:
        row = c.execute('SELECT id,caption,status,ai_generated FROM team_videos WHERE id=%s', (int(vid),)).fetchone()
        if not row or row['status'] != 'ready':
            return 'الفيديو غير موجود أو نُشر مسبقًا؛ لم يُنشر شيء.'
        c.execute("UPDATE team_videos SET status='publishing' WHERE id=%s", (row['id'],))

    def run():
        import asyncio
        from app.meta_connect import credentials
        link, text, results = url(row['id']), row['caption'], {}
        try:
            conn = credentials()
            for name, fn in (('فيسبوك', facebook), ('إنستغرام', instagram)):
                try:
                    results[name] = '✅ ' + str(fn(conn, link, text))
                except Exception as exc:
                    results[name] = '❌ ' + str(exc)[:150]
        except Exception as exc:
            results['فيسبوك/إنستغرام'] = '❌ ' + str(exc)[:150]
        ai = bool(row.get('ai_generated'))
        try:
            results['يوتيوب/تيك توك'] = '✅ ' + youtube_tiktok(row['id'], link, text, actor, ai)
        except Exception as exc:
            results['يوتيوب/تيك توك'] = '❌ ' + str(exc)[:150]
        try:
            results.update(extra_platforms(row['id'], link, text, ai))
        except Exception as exc:
            results['باقي المنصات'] = '❌ ' + str(exc)[:150]
        with db() as c:
            c.execute("UPDATE team_videos SET status='done',results_json=%s WHERE id=%s", (json.dumps(results, ensure_ascii=False), row['id']))
        print('TEAM_VIDEO_PUBLISH', row['id'], json.dumps(results, ensure_ascii=False)[:400], flush=True)
        try:
            from app.owner_briefing import deliver
            asyncio.run(deliver('🎬 نتيجة نشر الفيديو #' + str(row['id']) + '\n' + '\n'.join(k + ': ' + v for k, v in results.items())))
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()
    return ('⏳ بدأ نشر الفيديو على كل المنصات المربوطة (فيسبوك، إنستغرام، يوتيوب، تيك توك، وأي حساب مربوط في Zernio: '
            'لينكدإن، إكس، ثريدز، بنترست…) بنص مناسب لكل منصة؛ أرسل لك نتيجة كل منصة خلال دقائق.')
