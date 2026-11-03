"""Team video → social publishing (owner request, Nov 2026).

The manager sends a video on WhatsApp (the text with it becomes the post caption). The agent stores it at a public
URL and prepares «نفذ CODE». After confirmation it publishes to Facebook (page video), Instagram (Reels),
YouTube and TikTok (through Zernio) in the background and sends the manager the result of every platform.
"""
import json
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


def video_index(message):
    for index, item in enumerate(message.get('attachments') or []):
        if isinstance(item, dict) and (str(item.get('type', '')).lower() == 'video' or str(item.get('mimeType', '')).lower().startswith('video/')):
            return index
    return None


def url(vid):
    from app.daily_poster import base_url
    return base_url() + '/media/team-video/' + str(vid) + '.mp4'


@router.get('/media/team-video/{name}')
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
    return body + ('' if '0507665873' in body else FOOTER)


def save(data, mime, text, actor):
    init()
    with db() as c:
        return c.execute('INSERT INTO team_videos(video,mime,caption,created_by,created_at) VALUES(%s,%s,%s,%s,%s) RETURNING id',
                         (data, mime or 'video/mp4', caption_for(text), actor, utcnow())).fetchone()['id']


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


def youtube_tiktok(vid, video_url, text, actor):
    from app.daily_poster import tiktok_settings
    from app.social_publishing import connection, save_result
    from app.social_zernio import creator_info, provider_request, publication_result, verified_accounts
    key, _ = connection()
    accounts = verified_accounts(key, ('youtube', 'tiktok'))
    title = ('آفاق طويق | ' + text.split('\n')[0])[:95]
    platforms = [{'platform': 'youtube', 'accountId': accounts['youtube']['accountId'],
                  'platformSpecificData': {'title': title, 'visibility': 'public', 'madeForKids': False, 'containsSyntheticMedia': False}}]
    tiktok = None
    try:
        tiktok = tiktok_settings(creator_info(key, accounts['tiktok']['accountId']))
    except Exception:
        tiktok = None
    if tiktok:
        platforms.append({'platform': 'tiktok', 'accountId': accounts['tiktok']['accountId']})
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
        row = c.execute('SELECT id,caption,status FROM team_videos WHERE id=%s', (int(vid),)).fetchone()
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
        try:
            results['يوتيوب/تيك توك'] = '✅ ' + youtube_tiktok(row['id'], link, text, actor)
        except Exception as exc:
            results['يوتيوب/تيك توك'] = '❌ ' + str(exc)[:150]
        with db() as c:
            c.execute("UPDATE team_videos SET status='done',results_json=%s WHERE id=%s", (json.dumps(results, ensure_ascii=False), row['id']))
        print('TEAM_VIDEO_PUBLISH', row['id'], json.dumps(results, ensure_ascii=False)[:400], flush=True)
        try:
            from app.owner_briefing import deliver
            asyncio.run(deliver('🎬 نتيجة نشر الفيديو #' + str(row['id']) + '\n' + '\n'.join(k + ': ' + v for k, v in results.items())))
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()
    return '⏳ بدأ نشر الفيديو على فيسبوك وإنستغرام ويوتيوب وتيك توك؛ أرسل لك النتيجة خلال دقائق.'
