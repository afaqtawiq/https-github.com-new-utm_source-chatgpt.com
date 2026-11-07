"""Independent English morning edition of the approved Afaq daily brochure.

No AI service, new credential, external scheduler, or Arabic-table migration.
Disabled by default. AFAQ_DAILY_POSTER_EN=1 plus ENABLE_EXTERNAL_ACTIONS=1
allows one English edition per Riyadh day during the morning window only.
The Arabic worker, its records, schedule, assets and rendering stay unchanged.
"""
import asyncio
import datetime as dt
import io
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from PIL import Image, ImageDraw
from starlette.concurrency import run_in_threadpool

from app import daily_poster as ar
from app.storage import db, log, one, utcnow

router = APIRouter()
RIYADH = ar.RIYADH
BRAND = 'Afaq Tuwaiq'
LICENCES = 'Customs licence 2513 | Transport licence 11/00098402'
TOPICS = [
    {'key': 'clearance', 'chip': 'OUR SERVICES', 'head': 'Customs Clearance',
     'sub': 'Support through your shipment clearance process',
     'points': ['Customs declaration preparation and follow-up', 'Document review before your shipment arrives', 'Follow-up on relevant authority requirements'],
     'tags': '#CustomsClearance #AfaqTuwaiq #Imports #SaudiArabia'},
    {'key': 'land', 'chip': 'OUR SERVICES', 'head': 'Road Transport',
     'sub': 'From the port of entry to your warehouse',
     'points': ['Trucks in a range of sizes', 'Transport between Saudi cities', 'Shipment follow-up through delivery'],
     'tags': '#RoadTransport #Freight #AfaqTuwaiq #SaudiArabia'},
    {'key': 'app', 'chip': 'OUR APP', 'head': 'Afaq Freight Market',
     'sub': 'Connecting loads with carriers on Saudi routes',
     'points': ['List your load from your phone', 'Find carriers across Saudi Arabia', 'Register with your mobile number'],
     'tags': '#AfaqTuwaiq #Freight #Carriers #SaudiArabia'},
    {'key': 'storage', 'chip': 'OUR SERVICES', 'head': 'Storage Solutions',
     'sub': 'Storage for your goods after customs clearance',
     'points': ['Post-clearance shipment storage', 'Organized receiving and dispatch', 'Direct coordination with road transport'],
     'tags': '#Storage #Warehousing #AfaqTuwaiq #Logistics'},
    {'key': 'd2d', 'chip': 'OUR SERVICES', 'head': 'Door-to-Door Logistics',
     'sub': 'Shipping, customs clearance and transport',
     'points': ['One point of contact for your shipment', 'Coordination across each logistics service', 'Follow-up at every stage'],
     'tags': '#DoorToDoor #Shipping #AfaqTuwaiq #Logistics'},
    {'key': 'ports', 'chip': 'WHERE WE WORK', 'head': 'Ports & Border Services',
     'sub': 'Jeddah | Dammam | Riyadh | Al Batha',
     'points': ['Jeddah Islamic Port', 'King Abdulaziz Port in Dammam', 'Riyadh Dry Port and Al Batha border'],
     'tags': '#JeddahPort #DammamPort #AlBatha #AfaqTuwaiq'},
    {'key': 'gcc', 'chip': 'GCC LOGISTICS', 'head': 'GCC Freight Services',
     'sub': 'Transport and clearance across Saudi Arabia and the GCC',
     'points': ['UAE | Kuwait | Qatar | Bahrain | Oman', 'Customs clearance at land borders', 'Transport coordination to your destination'],
     'tags': '#GCCFreight #RoadTransport #AfaqTuwaiq #Logistics'},
]


def enabled():
    return os.getenv('AFAQ_DAILY_POSTER_EN', '0') == '1' and os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') == '1'


def poster_hour():
    # Invalid configuration never turns an English morning edition into evening publishing.
    try:
        hour = int(os.getenv('POSTER_EN_HOUR', '9'))
        return hour if 6 <= hour <= 11 else 9
    except ValueError:
        return 9


def due(now=None):
    local = (now or dt.datetime.now(dt.timezone.utc)).astimezone(RIYADH)
    return local.date() if poster_hour() <= local.hour < 12 else None


def topic_for(day):
    return TOPICS[day.toordinal() % len(TOPICS)]


def caption(topic):
    return '\n'.join([BRAND + ' | ' + topic['head'], topic['sub'], ''] +
                     ['- ' + p for p in topic['points']] +
                     ['', 'WhatsApp: ' + ar.WHATSAPP + ' | ' + ar.WHATSAPP2,
                      'Shipment cost calculator: ' + ar.base_url() + '/price?src=social',
                      'https://' + ar.APP_URL, LICENCES, '', topic['tags']])


def put(draw, text, xy, width, size, fill, anchor='lm', black=True):
    """Latin text is measured and drawn left-to-right, without Arabic shaping."""
    for point in range(size, 17, -1):
        face = ar.font(point, black)
        if draw.textlength(text, font=face) <= width:
            draw.text(xy, text, font=face, fill=fill, anchor=anchor)
            return
    raise ValueError('English poster text exceeds its layout width')


def render_poster(topic):
    w, h, m = 1080, 1350, 72
    img = ar.decor(ar.gradient(w, h))
    d = ImageDraw.Draw(img, 'RGBA')
    with Image.open(ar.FONTS.parent / 'afaq-logo-official.png') as logo:
        logo = logo.convert('RGBA')
        logo.thumbnail((150, 170))
        d.rounded_rectangle([m, 38, m + logo.width + 36, 62 + logo.height], radius=24, fill='white')
        img.alpha_composite(logo, (m + 18, 50))
    put(d, BRAND.upper(), (285, 103), 720, 62, 'white')
    put(d, 'CUSTOMS CLEARANCE & LOGISTICS', (285, 165), 720, 30, ar.MUTED, black=False)
    d.rounded_rectangle([m, 279, m + 360, 335], radius=28, fill=ar.GOLD)
    put(d, topic['chip'], (m + 180, 307), 320, 31, ar.NAVY, anchor='mm', black=False)
    put(d, topic['head'], (m, 425), w - 2 * m, 89, 'white')
    put(d, topic['sub'], (m, 528), w - 2 * m, 40, ar.MUTED, black=False)
    d.rectangle([m, 590, m + 160, 596], fill=ar.GOLD)
    for i, point in enumerate(topic['points']):
        y = 680 + i * 104
        d.ellipse([m, y - 26, m + 52, y + 26], fill=ar.GOLD)
        d.line([(m + 13, y), (m + 23, y + 11), (m + 39, y - 11)], fill=ar.NAVY, width=6, joint='curve')
        put(d, point, (m + 76, y), w - 2 * m - 90, 38, 'white', black=False)
    top = h - 330
    d.rounded_rectangle([m - 12, top, w - m + 12, h - 60], radius=34,
                        fill=(4, 14, 24, 235), outline=ar.GOLD, width=3)
    put(d, 'WhatsApp ' + ar.WHATSAPP + ' | ' + ar.WHATSAPP2,
        (w // 2, top + 72), w - 2 * m - 60, 46, ar.GOLD2, anchor='mm')
    put(d, ar.APP_URL, (w // 2, top + 152), w - 2 * m - 60, 44, 'white', anchor='mm')
    put(d, LICENCES, (w // 2, top + 222), w - 2 * m - 60, 29, ar.MUTED, anchor='mm', black=False)
    out = io.BytesIO()
    img.convert('RGB').save(out, 'JPEG', quality=92, optimize=True)
    return out.getvalue()


def video_frame(poster_jpeg):
    canvas = ar.decor(ar.gradient(1080, 1920))
    d = ImageDraw.Draw(canvas, 'RGBA')
    put(d, 'From the border to your business', (540, 170), 940, 54, ar.GOLD2, anchor='mm')
    with Image.open(io.BytesIO(poster_jpeg)) as image:
        canvas.alpha_composite(image.convert('RGBA'), (0, 285))
    put(d, 'Follow Afaq Tuwaiq for more', (540, 1760), 880, 44, ar.MUTED, anchor='mm', black=False)
    out = io.BytesIO()
    canvas.convert('RGB').save(out, 'PNG')
    return out.getvalue()


def render_video(poster_jpeg):
    with tempfile.TemporaryDirectory() as tmp:
        frame, video = Path(tmp) / 'frame.png', Path(tmp) / 'poster.mp4'
        frame.write_bytes(video_frame(poster_jpeg))
        vf = ("scale=2160:-1,zoompan=z='1+0.05*on/240':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              ":d=240:s=1080x1920:fps=30,fade=t=in:st=0:d=0.6,fade=t=out:st=7.3:d=0.7,format=yuv420p")
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-filter_threads', '1', '-loop', '1', '-i', str(frame),
                        '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo', '-vf', vf, '-t', '8',
                        '-c:v', 'libx264', '-threads', '2', '-preset', 'medium', '-crf', '21', '-c:a', 'aac', '-b:a', '96k',
                        '-shortest', '-movflags', '+faststart', str(video)], check=True, timeout=240)
        return video.read_bytes()


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS afaq_daily_posters_en(
            day DATE PRIMARY KEY, topic TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '',
            image BYTEA, video BYTEA, status TEXT NOT NULL, results_json TEXT NOT NULL DEFAULT '{}',
            zernio_content_id BIGINT, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)''')


def media_urls(day):
    prefix = ar.base_url() + '/media/daily-poster-en/' + day.isoformat()
    return prefix + '.jpg', prefix + '.mp4'


@router.get('/media/daily-poster-en/{name}')
def public_media(name: str):
    stem, _, ext = name.partition('.')
    try:
        day = dt.date.fromisoformat(stem)
    except ValueError:
        raise HTTPException(404)
    column = {'jpg': 'image', 'mp4': 'video'}.get(ext)
    if not column:
        raise HTTPException(404)
    row = one('SELECT ' + column + ' data FROM afaq_daily_posters_en WHERE day=?', (day,))
    if not row or not row['data']:
        raise HTTPException(404)
    return Response(bytes(row['data']), media_type='image/jpeg' if ext == 'jpg' else 'video/mp4',
                    headers={'Cache-Control': 'public, max-age=86400'})


def set_result(day, channel, value):
    with db() as c:
        row = c.execute('SELECT results_json FROM afaq_daily_posters_en WHERE day=%s FOR UPDATE', (day,)).fetchone()
        results = json.loads(row['results_json'] or '{}')
        results[channel] = value
        c.execute('UPDATE afaq_daily_posters_en SET results_json=%s,updated_at=%s WHERE day=%s',
                  (json.dumps(results), utcnow(), day))


def claim(day, topic, text):
    with db() as c:
        return bool(c.execute('''INSERT INTO afaq_daily_posters_en(day,topic,caption,status,created_at,updated_at)
            VALUES(%s,%s,%s,'rendering',%s,%s) ON CONFLICT DO NOTHING RETURNING day''',
            (day, topic['key'], text, utcnow(), utcnow())).fetchone())


class PublicationWindowClosed(RuntimeError):
    pass


def publishing_guard(day, now=None):
    if not enabled() or due(now) != day:
        raise PublicationWindowClosed('English publication is disabled or outside the morning window')


def publish_instagram(conn, image_url, text, guard):
    # Recheck the morning gate after Meta has finished processing its container.
    from app.meta_connect import MetaError, graph
    if not conn.get('ig_id'):
        raise MetaError('No Instagram account is connected.')
    guard()
    creation = graph('POST', conn['ig_id'] + '/media', conn['token'], data={'image_url': image_url, 'caption': text})['id']
    ready = False
    for _ in range(20):
        state = graph('GET', creation, conn['token'], params={'fields': 'status_code'}).get('status_code')
        if state == 'FINISHED':
            ready = True
            break
        if state in ('ERROR', 'EXPIRED'):
            raise MetaError('Instagram rejected the image container.')
        time.sleep(3)
    if not ready:
        raise MetaError('Instagram processing did not finish; do not retry automatically.')
    guard()
    media = graph('POST', conn['ig_id'] + '/media_publish', conn['token'], data={'creation_id': creation})['id']
    try:
        link = graph('GET', media, conn['token'], params={'fields': 'permalink'}).get('permalink') or ''
    except MetaError:
        link = ''
    return {'status': 'published', 'id': media, 'url': link}


def publish_video(day, topic, text, video_url, uid, guard=None):
    from app.social_publishing import connection, save_result
    from app.social_zernio import creator_info, provider_request, publication_result, verified_accounts
    guard = guard or (lambda: publishing_guard(day))
    guard()
    key, _ = connection()
    accounts = verified_accounts(key, ('youtube', 'tiktok'))
    title = (BRAND + ' | ' + topic['head'])[:95]
    platforms = [{'platform': 'youtube', 'accountId': accounts['youtube']['accountId'],
                  'platformSpecificData': {'title': title, 'visibility': 'public', 'madeForKids': False,
                                           'containsSyntheticMedia': False}}]
    try:
        tiktok = ar.tiktok_settings(creator_info(key, accounts['tiktok']['accountId']))
    except Exception:
        tiktok = None
    if tiktok:
        platforms.append({'platform': 'tiktok', 'accountId': accounts['tiktok']['accountId']})
    now = utcnow()
    payload = {'content': text[:2200], 'title': title, 'mediaItems': [{'type': 'video', 'url': video_url}],
               'platforms': platforms, 'publishNow': True, 'timezone': 'Asia/Riyadh',
               'metadata': {'afaqDailyPoster': day.isoformat(), 'language': 'en'}}
    if tiktok:
        payload['tiktokSettings'] = tiktok
    request_id = str(uuid.uuid4())
    with db() as c:
        content_id = c.execute('''INSERT INTO social_content(title,platform,content_type,body,media_url,scheduled_at,status,created_by,created_at,updated_at)
            VALUES(%s,%s,'video',%s,%s,%s,'submitting',%s,%s,%s) RETURNING id''',
            ('English daily brochure ' + day.isoformat() + ' | ' + topic['head'],
             'YouTube+TikTok' if tiktok else 'YouTube', text, video_url, now, uid, now, now)).fetchone()['id']
        c.execute('''INSERT INTO social_publications(content_id,request_id,status,scheduled_at,payload_json,approved_by,created_at,updated_at)
            VALUES(%s,%s,'submitting',%s,%s,%s,%s,%s)''', (content_id, request_id, now, json.dumps(payload), uid, now, now))
        c.execute('UPDATE afaq_daily_posters_en SET zernio_content_id=%s WHERE day=%s', (content_id, day))
    try:
        guard()
        response = provider_request(key, 'POST', '/posts', payload=payload, request_id=request_id)
        post_id, state, results = publication_result(response, platforms)
        save_result(content_id, post_id, state, results)
    except PublicationWindowClosed:
        save_result(content_id, None, 'cancelled', [], 'Morning window closed before provider submission.')
        raise
    except Exception as exc:
        save_result(content_id, None, 'needs_review', [], 'Submission outcome needs review: ' + type(exc).__name__)
        raise
    return {'status': state, 'content_id': content_id, 'tiktok': bool(tiktok),
            'tiktok_status': 'submitted' if tiktok else 'skipped_unavailable'}


def save_drafts(day, topic, text, image_url, uid):
    now, ids = utcnow(), []
    with db() as c:
        for platform in ('X', 'LinkedIn'):
            body = text[:2800] if platform == 'LinkedIn' else (
                topic['head'] + ' | ' + topic['sub'] + '\nWhatsApp ' + ar.WHATSAPP +
                ' | ' + ar.WHATSAPP2 + '\nhttps://' + ar.APP_URL)[:270]
            ids.append(c.execute('''INSERT INTO social_content(title,platform,content_type,body,media_url,scheduled_at,status,created_by,created_at,updated_at)
                VALUES(%s,%s,'post',%s,%s,%s,'draft',%s,%s,%s) RETURNING id''',
                ('English daily brochure ' + day.isoformat() + ' | ' + topic['head'],
                 platform, body, image_url, now, uid, now, now)).fetchone()['id'])
    return ids


def record_meta(day, topic, text, image_url, uid, results):
    links = [(k, results[k].get('url')) for k in ('facebook', 'instagram')
             if isinstance(results.get(k), dict) and results[k].get('status') == 'published' and results[k].get('url')]
    if not links:
        return
    now = utcnow()
    with db() as c:
        c.execute('''INSERT INTO social_content(title,platform,content_type,body,media_url,scheduled_at,status,created_by,created_at,updated_at,published_at)
            VALUES(%s,%s,'post',%s,%s,%s,'published',%s,%s,%s,%s)''',
            ('English daily brochure ' + day.isoformat() + ' | ' + topic['head'],
             '+'.join(k.title() for k, _ in links), text + '\n\n' + '\n'.join(url for _, url in links),
             image_url, now, uid, now, now, now))


def final_status(results):
    """Queued video is pending, never proof that all channels were published."""
    states = [results.get(k, {}).get('status') for k in ('facebook', 'instagram', 'youtube_tiktok')]
    video = results.get('youtube_tiktok', {})
    if results.get('drafts', {}).get('status') == 'failed':
        return 'partial'
    if all(s == 'published' for s in states) and video.get('tiktok') is True:
        return 'published'
    if any(s in ('failed', 'needs_review', 'not_connected', 'partial', 'cancelled', 'blocked_window') for s in states) or video.get('tiktok') is False:
        return 'partial' if any(s in ('published', 'publishing', 'scheduled', 'submitting', 'partial') for s in states) else 'needs_review'
    return 'pending'


def run_for(day, now=None):
    # Direct invocation cannot bypass activation or post a missed morning in the evening.
    if not enabled():
        return {'day': day.isoformat(), 'skipped': 'disabled'}
    if due(now) != day:
        return {'day': day.isoformat(), 'skipped': 'outside_morning_window'}
    guard = lambda: publishing_guard(day, now)
    topic = topic_for(day)
    text = caption(topic)
    if not claim(day, topic, text):
        return {'day': day.isoformat(), 'skipped': 'already_claimed'}
    # Claim precedes rendering and any provider call. Crashes never retry posting.
    from app.prospect_autopilot import system_user
    uid = system_user()
    results = {}
    try:
        image = render_poster(topic)
        video = render_video(image)
        with db() as c:
            c.execute("UPDATE afaq_daily_posters_en SET image=%s,video=%s,status='publishing',updated_at=%s WHERE day=%s",
                      (image, video, utcnow(), day))
        image_url, video_url = media_urls(day)
        from app.meta_connect import connected, credentials
        try:
            conn = credentials() if connected() else None
            meta_error = None
        except Exception:
            conn, meta_error = None, 'needs_review'
        for channel, fn in (('facebook', ar.publish_facebook), ('instagram', lambda c, u, t: publish_instagram(c, u, t, guard))):
            try:
                guard()
                results[channel] = fn(conn, image_url, text) if conn else {'status': meta_error or 'not_connected'}
            except PublicationWindowClosed:
                results[channel] = {'status': 'blocked_window'}
            except Exception:
                results[channel] = {'status': 'needs_review', 'error': 'Provider outcome requires review; do not retry automatically.'}
            set_result(day, channel, results[channel])
        try:
            guard()
            results['youtube_tiktok'] = publish_video(day, topic, text, video_url, uid, guard=guard)
        except PublicationWindowClosed:
            results['youtube_tiktok'] = {'status': 'blocked_window'}
        except Exception:
            results['youtube_tiktok'] = {'status': 'needs_review', 'error': 'Provider outcome requires review; do not retry automatically.'}
        set_result(day, 'youtube_tiktok', results['youtube_tiktok'])
        try:
            results['drafts'] = {'status': 'saved', 'content_ids': save_drafts(day, topic, text, image_url, uid)}
        except Exception:
            results['drafts'] = {'status': 'failed'}
        record_meta(day, topic, text, image_url, uid, results)
        final = final_status(results)
    except Exception as exc:
        final = 'needs_review'
        results['run'] = {'status': 'needs_review', 'error_type': type(exc).__name__}
    with db() as c:
        c.execute('UPDATE afaq_daily_posters_en SET status=%s,results_json=%s,updated_at=%s WHERE day=%s',
                  (final, json.dumps(results), utcnow(), day))
    log(uid, 'daily_poster_en_run', 'afaq_daily_poster_en', None, day.isoformat() + ' | ' + final)
    return {'day': day.isoformat(), 'status': final, 'results': {k: v.get('status') for k, v in results.items()}}


def sync_pending():
    """Read existing provider jobs only. No retry, new upload, or new publication."""
    from app.social_publishing import connection, save_result
    from app.social_zernio import identifier, provider_request, publication_result
    with db() as c:
        rows = c.execute('''SELECT d.day,d.results_json,p.content_id,p.provider_post_id,p.payload_json,p.status
            FROM afaq_daily_posters_en d JOIN social_publications p ON p.content_id=d.zernio_content_id
            WHERE d.day >= CURRENT_DATE - 7 AND p.provider_post_id IS NOT NULL
            AND (p.status IN ('submitting','scheduled','publishing') OR
                 (p.status IN ('published','partial','failed','cancelled') AND d.status IN ('pending','publishing')))''').fetchall()
    if not rows:
        return 0
    key, _ = connection()
    for row in rows:
        try:
            response = provider_request(key, 'GET', '/posts/' + identifier(row['provider_post_id']))
            post_id, state, channel_results = publication_result(response, json.loads(row['payload_json'])['platforms'])
            if post_id != row['provider_post_id']:
                raise ValueError('Provider post identity mismatch')
            save_result(row['content_id'], post_id, state, channel_results)
            results = json.loads(row['results_json'])
            video = results.get('youtube_tiktok', {})
            video.update({'status': state, 'channels': channel_results})
            results['youtube_tiktok'] = video
            with db() as c:
                c.execute('UPDATE afaq_daily_posters_en SET status=%s,results_json=%s,updated_at=%s WHERE day=%s',
                          (final_status(results), json.dumps(results), utcnow(), row['day']))
        except Exception as exc:
            print('DAILY_POSTER_EN_SYNC', row['content_id'], type(exc).__name__, flush=True)
    return len(rows)


def tick(now=None):
    if not enabled():
        return None
    day = due(now)
    result = run_for(day, now) if day else None
    sync_pending()
    return result


def register_worker(app):
    async def loop():
        await asyncio.sleep(90)
        while True:
            if enabled():
                try:
                    result = await run_in_threadpool(tick)
                    if result and not result.get('skipped'):
                        print('DAILY_POSTER_EN', result, flush=True)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print('DAILY_POSTER_EN_ERROR', type(exc).__name__, flush=True)
            await asyncio.sleep(300)

    @app.on_event('startup')
    async def start():
        app.state.daily_poster_en_worker = asyncio.create_task(loop())


@router.get('/daily-posters-en', response_class=HTMLResponse)
def admin_page(request: Request):
    from app.social_content import e, page
    from app.social_publishing import admin
    admin(request)
    with db() as c:
        rows = c.execute('SELECT day,topic,status,results_json FROM afaq_daily_posters_en ORDER BY day DESC LIMIT 30').fetchall()
    today = dt.datetime.now(RIYADH).date()
    body = '<div class="nav"><a href="/daily-posters">البوستر العربي</a><a href="/content-center">مركز المحتوى</a></div>'
    body += ('<div class="hero"><h1>البوستر الإنجليزي الصباحي</h1><p>يوميًا ' + str(poster_hour()) +
             ':00 بتوقيت الرياض، ولا يُنشر بعد الظهر عند فوات الموعد. الحالة: <b>' + ('مفعّل' if enabled() else 'متوقف') +
             '</b></p><p>Facebook وInstagram: صورة. YouTube وTikTok: فيديو 8 ثوانٍ. X وLinkedIn: مسودات فقط.</p>' +
             '<p>العربي المسائي دون تغيير. موضوع اليوم: ' + e(topic_for(today)['head']) +
             ' · <a href="/daily-posters-en/preview/' + str(TOPICS.index(topic_for(today))) + '.jpg">معاينة</a></p></div>')
    body += '<div class="card scroll"><table><tr><th>اليوم</th><th>الموضوع</th><th>الحالة</th><th>النتائج</th><th>الملفات</th></tr>'
    for row in rows:
        day = row['day'].isoformat()
        image_url, video_url = media_urls(row['day'])
        body += ('<tr><td>' + e(day) + '</td><td>' + e(row['topic']) + '</td><td>' + e(row['status']) +
                 '</td><td>' + e(row['results_json']) + '</td><td><a href="' + e(image_url) + '">الصورة</a> · ' +
                 '<a href="' + e(video_url) + '">الفيديو</a></td></tr>')
    return HTMLResponse(page(body + '</table></div>'), headers={'Cache-Control': 'no-store'})


@router.get('/daily-posters-en/preview/{index}.jpg')
def preview(index: int, request: Request):
    from app.social_publishing import admin
    admin(request)
    if not 0 <= index < len(TOPICS):
        raise HTTPException(404)
    return Response(render_poster(TOPICS[index]), media_type='image/jpeg', headers={'Cache-Control': 'no-store'})
