"""Owner-authorised daily poster: one branded poster every day, published automatically.

Enabled only with AFAQ_DAILY_POSTER=1 and ENABLE_EXTERNAL_ACTIONS=1. From POSTER_HOUR (19:00
Riyadh) the worker renders the day's poster (7 rotating topics), then publishes it once:
image to the Facebook Page and Instagram directly through Meta, an 8-second vertical video
to YouTube and TikTok through the existing Zernio connection, and saves X/LinkedIn drafts in
the content center. Each day is claimed before any provider call; nothing is ever retried.
Posters carry facts only (licences, contact, app link) — no prices and no time promises.
"""
import asyncio
import datetime as dt
import io
import json
import math
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from PIL import Image, ImageDraw, ImageFilter, ImageFont, features
from starlette.concurrency import run_in_threadpool

from app.social_zernio import RIYADH
from app.storage import db, log, one, utcnow

router = APIRouter()
FONTS = Path(__file__).parent / 'assets' / 'fonts'
WHATSAPP = '0507665873'
WHATSAPP2 = '0530130435'
APP_URL = 'app.afaqtawiqs.net'
LICENCES = 'ترخيص التخليص 2513 · ترخيص النقل 11/00098402'
NAVY, NAVY2 = (7, 19, 31), (16, 46, 66)
GOLD, GOLD2 = (231, 182, 75), (255, 217, 120)
MUTED = (190, 210, 222)

TOPICS = [
    {'key': 'clearance', 'chip': 'خدماتنا', 'head': 'التخليص الجمركي', 'sub': 'نتابع إجراءات فسح شحنتك باحتراف',
     'points': ['إعداد البيان الجمركي ومتابعته', 'مراجعة المستندات قبل وصول الشحنة', 'متابعة اشتراطات الجهات المختصة'],
     'tags': '#تخليص_جمركي #آفاق_طويق #استيراد #السعودية'},
    {'key': 'land', 'chip': 'خدماتنا', 'head': 'النقل البري', 'sub': 'من المنفذ حتى مستودعك',
     'points': ['شاحنات بأحجام متعددة', 'نقل بين مدن المملكة', 'متابعة الشحنة حتى التسليم'],
     'tags': '#نقل_بري #شحن #آفاق_طويق #السعودية'},
    {'key': 'app', 'chip': 'تطبيق جديد', 'head': 'سوق آفاق طويق', 'sub': 'سائق؟ نوفر لك حمولتك على خطك',
     'points': ['اعرض حمولتك من جوالك', 'ناقلون على خطوط المملكة', 'التسجيل برقم الجوال'],
     'tags': '#سوق_آفاق_طويق #حمولات #سائقين #نقل'},
    {'key': 'storage', 'chip': 'خدماتنا', 'head': 'التخزين', 'sub': 'حلول تخزين لبضائعك بعد الفسح',
     'points': ['تخزين للشحنات بعد الفسح', 'تنظيم الاستلام والتسليم', 'تنسيق مباشر مع النقل'],
     'tags': '#تخزين #مستودعات #آفاق_طويق #لوجستيات'},
    {'key': 'd2d', 'chip': 'خدماتنا', 'head': 'من الباب إلى الباب', 'sub': 'شحن وتخليص ونقل بتنسيق واحد',
     'points': ['نقطة تواصل واحدة لشحنتك', 'تنسيق بين الشحن والتخليص والنقل', 'متابعة في كل مرحلة'],
     'tags': '#من_الباب_إلى_الباب #شحن #آفاق_طويق'},
    {'key': 'ports', 'chip': 'منافذنا', 'head': 'نخدمكم في المنافذ', 'sub': 'جدة · الدمام · الرياض · البطحاء',
     'points': ['ميناء جدة الإسلامي', 'ميناء الملك عبدالعزيز بالدمام', 'الميناء الجاف بالرياض ومنفذ البطحاء'],
     'tags': '#ميناء_جدة #ميناء_الدمام #منفذ_البطحاء #آفاق_طويق'},
    {'key': 'gcc', 'chip': 'الخليج', 'head': 'الشحن الخليجي', 'sub': 'نقل وتخليص بين المملكة ودول الخليج',
     'points': ['الإمارات · الكويت · قطر · البحرين · عُمان', 'تخليص عبر المنافذ البرية', 'تنسيق النقل حتى الوجهة'],
     'tags': '#شحن_خليجي #نقل_بري #آفاق_طويق #الخليج'},
]


def enabled():
    return os.getenv('AFAQ_DAILY_POSTER', '0') == '1' and os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') == '1'


def poster_hour():
    try:
        return max(0, min(23, int(os.getenv('POSTER_HOUR', '19'))))
    except ValueError:
        return 19


def base_url():
    return os.getenv('PUBLIC_BASE_URL', 'https://gulf-logistics-ai-v7-production.up.railway.app').rstrip('/')


def topic_for(day):
    return TOPICS[day.toordinal() % len(TOPICS)]


def caption(topic):
    lines = ['آفاق طويق | ' + topic['head'], topic['sub'], '']
    lines += ['✔️ ' + p for p in topic['points']]
    lines += ['', '📲 واتساب: ' + WHATSAPP + ' | ' + WHATSAPP2, '🧮 احسب تكلفة شحنتك فورًا: ' + base_url() + '/price?src=social',
              '🌐 https://' + APP_URL, LICENCES, '', topic['tags']]
    return '\n'.join(lines)


# ---------- rendering ----------

RAQM = features.check('raqm')


def font(size, black=True):
    path = FONTS / ('Cairo-Black.ttf' if black else 'Cairo-Bold.ttf')
    if RAQM:
        return ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.RAQM)
    return ImageFont.truetype(str(path), size)


def shaped(value):
    if RAQM:
        return value, {'direction': 'rtl', 'language': 'ar'}
    import arabic_reshaper
    from bidi import get_display
    return get_display(arabic_reshaper.reshape(value)), {}


def fit(draw, value, width, size, black=True):
    text, kw = shaped(value)
    for point in range(size, 18, -2):
        face = font(point, black)
        if draw.textlength(text, font=face, **kw) <= width:
            return text, face, kw
    return text, font(18, black), kw


def put(draw, value, xy, width, size, fill, anchor='mm', black=True):
    text, face, kw = fit(draw, value, width, size, black)
    draw.text(xy, text, font=face, fill=fill, anchor=anchor, **kw)


def gradient(w, h):
    img = Image.new('RGB', (w, h), NAVY)
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        row = tuple(int(NAVY[i] + (NAVY2[i] - NAVY[i]) * (1 - abs(2 * t - .8))) for i in range(3))
        for x in range(w):
            px[x, y] = row
    return img


def mark(draw, x, y, s):
    """Afaq Tuwaiq brand mark (as published on the brochure/Snapchat): gold rounded frame, mountains, sun, white base."""
    k = s / 80
    p = lambda a, b: (x + a * k, y + b * k)
    draw.rounded_rectangle([p(2, 2), p(78, 78)], radius=20 * k, fill=(62, 84, 66, 255), outline=GOLD, width=max(3, int(2.4 * k)))
    draw.line([p(14, 56), p(32, 22), p(42, 40), p(50, 28), p(66, 56)], fill=GOLD, width=max(4, int(3.4 * k)), joint='curve')
    draw.line([p(13, 58), p(67, 58)], fill='white', width=max(4, int(3.4 * k)))
    r = 4.2 * k
    draw.ellipse([x + 57 * k - r, y + 18 * k - r, x + 57 * k + r, y + 18 * k + r], fill=GOLD2)


def decor(img):
    w, h = img.size
    layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for gx in range(0, w, 60):
        d.line([(gx, 0), (gx, h)], fill=(148, 184, 205, 10))
    for gy in range(0, h, 60):
        d.line([(0, gy), (w, gy)], fill=(148, 184, 205, 10))
    pts = [(int(-40 + i * (w + 80) / 40), int(h * .58 - math.sin(i / 40 * math.pi) * h * .22)) for i in range(41)]
    for a, b in zip(pts[::2], pts[1::2]):
        d.line([a, b], fill=(231, 182, 75, 45), width=4)
    glow = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([w * .55, -h * .15, w * 1.25, h * .35], fill=(231, 182, 75, 40))
    layer = Image.alpha_composite(layer, glow.filter(ImageFilter.GaussianBlur(90)))
    return Image.alpha_composite(img.convert('RGBA'), layer)


def render_poster(topic, size=(1080, 1350)):
    w, h = size
    img = decor(gradient(w, h))
    d = ImageDraw.Draw(img, 'RGBA')
    m = 72
    with Image.open(FONTS.parent / 'afaq-logo-official.png') as logo:
        logo = logo.convert('RGBA')
        logo.thumbnail((190, 200))
        cw, ch = logo.width + 36, logo.height + 24
        d.rounded_rectangle([w - m - cw, 30, w - m, 30 + ch], radius=26, fill=(255, 255, 255, 255))
        img.alpha_composite(logo, (w - m - cw + 18, 42))
    put(d, 'آفاق طويق', (w - m - cw - 30, 104), 480, 64, 'white', anchor='rm')
    put(d, 'للتخليص الجمركي والخدمات اللوجستية', (w - m - cw - 30, 168), 480, 32, MUTED, anchor='rm', black=False)
    # topic chip
    chip, cf, ck = fit(d, topic['chip'], 400, 34, False)
    cw = d.textlength(chip, font=cf, **ck) + 56
    d.rounded_rectangle([w - m - cw, 278, w - m, 334], radius=28, fill=GOLD)
    d.text((w - m - cw / 2, 306), chip, font=cf, fill=NAVY, anchor='mm', **ck)
    put(d, topic['head'], (w - m, 420), w - 2 * m, 112, 'white', anchor='rm')
    put(d, topic['sub'], (w - m, 530), w - 2 * m, 46, MUTED, anchor='rm', black=False)
    d.rectangle([w - m - 160, 590, w - m, 596], fill=GOLD)
    for i, point in enumerate(topic['points']):
        y = 680 + i * 104
        d.ellipse([w - m - 52, y - 26, w - m, y + 26], fill=GOLD)
        d.line([(w - m - 39, y), (w - m - 29, y + 11), (w - m - 13, y - 11)], fill=NAVY, width=6, joint='curve')
        put(d, point, (w - m - 76, y), w - 2 * m - 90, 44, 'white', anchor='rm', black=False)
    # contact panel
    top = h - 330
    d.rounded_rectangle([m - 12, top, w - m + 12, h - 60], radius=34, fill=(4, 14, 24, 235), outline=GOLD, width=3)
    put(d, 'واتساب ' + WHATSAPP + '  |  ' + WHATSAPP2, (w // 2, top + 72), w - 2 * m - 60, 54, GOLD2)
    face = font(44, True)
    d.text((w // 2, top + 152), APP_URL, font=face, fill='white', anchor='mm')
    put(d, LICENCES, (w // 2, top + 222), w - 2 * m - 60, 30, MUTED, black=False)
    out = io.BytesIO()
    img.convert('RGB').save(out, 'JPEG', quality=92, optimize=True)
    return out.getvalue()


def video_frame(poster_jpeg):
    w, h = 1080, 1920
    canvas = decor(gradient(w, h))
    d = ImageDraw.Draw(canvas, 'RGBA')
    put(d, 'من الحدود... إلى وجهة تجارتك', (w // 2, 170), w - 140, 54, GOLD2)
    with Image.open(io.BytesIO(poster_jpeg)) as p:
        canvas.alpha_composite(p.convert('RGBA'), (0, 285))
    put(d, 'تابعنا للمزيد', (w // 2, 1760), w - 200, 44, MUTED, black=False)
    out = io.BytesIO()
    canvas.convert('RGB').save(out, 'PNG')
    return out.getvalue()


def render_video(poster_jpeg, seconds=8):
    with tempfile.TemporaryDirectory() as tmp:
        frame, video = Path(tmp) / 'frame.png', Path(tmp) / 'poster.mp4'
        frame.write_bytes(video_frame(poster_jpeg))
        fps, frames = 30, seconds * 30
        vf = (f"scale=2160:-1,zoompan=z='1+0.05*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s=1080x1920:fps={fps},fade=t=in:st=0:d=0.6,fade=t=out:st={seconds - 0.7}:d=0.7,format=yuv420p")
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-loop', '1', '-i', str(frame),
                        '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo', '-vf', vf, '-t', str(seconds),
                        '-c:v', 'libx264', '-preset', 'medium', '-crf', '21', '-c:a', 'aac', '-b:a', '96k',
                        '-shortest', '-movflags', '+faststart', str(video)], check=True, timeout=240)
        return video.read_bytes()


# ---------- storage & public media ----------

def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS afaq_daily_posters(
            day DATE PRIMARY KEY, topic TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '',
            image BYTEA, video BYTEA, status TEXT NOT NULL, results_json TEXT NOT NULL DEFAULT '{}',
            zernio_content_id BIGINT, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)''')


def media_urls(day):
    return base_url() + '/media/daily-poster/' + day.isoformat() + '.jpg', base_url() + '/media/daily-poster/' + day.isoformat() + '.mp4'


@router.get('/media/daily-poster/{name}')
def public_media(name: str):
    stem, _, ext = name.partition('.')
    try:
        day = dt.date.fromisoformat(stem)
    except ValueError:
        raise HTTPException(404)
    column = {'jpg': 'image', 'mp4': 'video'}.get(ext)
    if not column:
        raise HTTPException(404)
    row = one('SELECT ' + column + ' data FROM afaq_daily_posters WHERE day=?', (day,))
    if not row or not row['data']:
        raise HTTPException(404)
    return Response(bytes(row['data']), media_type='image/jpeg' if ext == 'jpg' else 'video/mp4',
                    headers={'Cache-Control': 'public, max-age=86400'})


# ---------- publishing ----------

def set_result(day, channel, value):
    with db() as c:
        row = c.execute('SELECT results_json FROM afaq_daily_posters WHERE day=%s FOR UPDATE', (day,)).fetchone()
        results = json.loads(row['results_json'] or '{}')
        results[channel] = value
        c.execute('UPDATE afaq_daily_posters SET results_json=%s,updated_at=%s WHERE day=%s',
                  (json.dumps(results, ensure_ascii=False), utcnow(), day))


def publish_facebook(conn, image_url, text):
    from app.meta_connect import graph
    r = graph('POST', conn['page_id'] + '/photos', conn['token'], data={'url': image_url, 'caption': text, 'published': 'true'})
    post = r.get('post_id') or r.get('id')
    return {'status': 'published', 'id': post, 'url': 'https://www.facebook.com/' + str(post)}


def publish_instagram(conn, image_url, text):
    from app.meta_connect import MetaError, graph
    if not conn.get('ig_id'):
        raise MetaError('لا يوجد حساب إنستغرام مرتبط بالصفحة.')
    creation = graph('POST', conn['ig_id'] + '/media', conn['token'], data={'image_url': image_url, 'caption': text})['id']
    for _ in range(20):
        status = graph('GET', creation, conn['token'], params={'fields': 'status_code'}).get('status_code')
        if status == 'FINISHED':
            break
        if status in ('ERROR', 'EXPIRED'):
            raise MetaError('رفض إنستغرام معالجة الصورة.')
        time.sleep(3)
    media = graph('POST', conn['ig_id'] + '/media_publish', conn['token'], data={'creation_id': creation})['id']
    try:
        link = graph('GET', media, conn['token'], params={'fields': 'permalink'}).get('permalink') or ''
    except MetaError:
        link = ''
    return {'status': 'published', 'id': media, 'url': link}


def tiktok_settings(creator):
    if not isinstance(creator, dict) or creator.get('creator', {}).get('canPostMore') is not True:
        return None
    privacy = {x.get('value') for x in creator.get('privacyLevels', []) if isinstance(x, dict)}
    commercial = {x.get('value') for x in creator.get('commercialContentTypes', []) if isinstance(x, dict)}
    if 'PUBLIC_TO_EVERYONE' not in privacy:
        return None
    toggles = creator.get('postingLimits', {}).get('interactionSettings', {})
    allow = lambda f: isinstance(toggles.get(f), dict) and toggles[f].get('enabled') is True
    settings = {'privacy_level': 'PUBLIC_TO_EVERYONE', 'content_preview_confirmed': True, 'express_consent_given': True,
                'videoMadeWithAi': False, 'allow_comment': allow('allow_comment'), 'allow_duet': False, 'allow_stitch': False}
    pick = next((v for v in ('your_brand', 'none') if v in commercial), None)
    if pick is None:
        return None
    settings['commercialContentType'] = pick
    return settings


def publish_video(day, topic, text, video_url, uid):
    """YouTube + TikTok through Zernio, recorded as a normal publication so sync/comment workers see it."""
    from app.social_publishing import connection, save_result
    from app.social_zernio import creator_info, provider_request, publication_result, verified_accounts
    key, _ = connection()
    accounts = verified_accounts(key, ('youtube', 'tiktok'))
    title = ('آفاق طويق | ' + topic['head'])[:95]
    platforms = [{'platform': 'youtube', 'accountId': accounts['youtube']['accountId'],
                  'platformSpecificData': {'title': title, 'visibility': 'public', 'madeForKids': False,
                                           'containsSyntheticMedia': False}}]
    tiktok = None
    try:
        tiktok = tiktok_settings(creator_info(key, accounts['tiktok']['accountId']))
    except Exception:
        tiktok = None
    if tiktok:
        platforms.append({'platform': 'tiktok', 'accountId': accounts['tiktok']['accountId']})
    now = utcnow()
    payload = {'content': text[:2200], 'title': title, 'mediaItems': [{'type': 'video', 'url': video_url}],
               'platforms': platforms, 'publishNow': True, 'timezone': 'Asia/Riyadh',
               'metadata': {'afaqDailyPoster': day.isoformat()}}
    if tiktok:
        payload['tiktokSettings'] = tiktok
    request_id = str(uuid.uuid4())
    with db() as c:
        content_id = c.execute('''INSERT INTO social_content(title,platform,content_type,body,media_url,scheduled_at,status,created_by,created_at,updated_at)
            VALUES(%s,%s,'video',%s,%s,%s,'submitting',%s,%s,%s) RETURNING id''',
            ('بوستر يومي ' + day.isoformat() + ' — ' + topic['head'], 'YouTube+TikTok' if tiktok else 'YouTube',
             text, video_url, now, uid, now, now)).fetchone()['id']
        c.execute('''INSERT INTO social_publications(content_id,request_id,status,scheduled_at,payload_json,approved_by,created_at,updated_at)
            VALUES(%s,%s,'submitting',%s,%s,%s,%s,%s)''', (content_id, request_id, now, json.dumps(payload), uid, now, now))
        c.execute('UPDATE afaq_daily_posters SET zernio_content_id=%s WHERE day=%s', (content_id, day))
    try:
        response = provider_request(key, 'POST', '/posts', payload=payload, request_id=request_id)
        post_id, state, results = publication_result(response, platforms)
        save_result(content_id, post_id, state, results)
    except Exception as exc:
        save_result(content_id, None, 'needs_review', [], str(exc)[:300])
        raise
    return {'status': state, 'content_id': content_id, 'tiktok': bool(tiktok)}


def save_drafts(day, topic, text, image_url, uid):
    now = utcnow()
    ids = []
    with db() as c:
        for platform in ('X', 'LinkedIn'):
            ids.append(c.execute('''INSERT INTO social_content(title,platform,content_type,body,media_url,scheduled_at,status,created_by,created_at,updated_at)
                VALUES(%s,%s,'post',%s,%s,%s,'draft',%s,%s,%s) RETURNING id''',
                ('بوستر يومي ' + day.isoformat() + ' — ' + topic['head'], platform, text[:2800] if platform == 'LinkedIn' else
                 (topic['head'] + ' — ' + topic['sub'] + '\nواتساب ' + WHATSAPP + ' | ' + WHATSAPP2 + '\nhttps://' + APP_URL)[:270],
                 image_url, now, uid, now, now)).fetchone()['id'])
    return ids


def record_meta(day, topic, text, image_url, uid, results):
    links = [results[k].get('url') for k in ('facebook', 'instagram') if isinstance(results.get(k), dict) and results[k].get('url')]
    if not links:
        return
    now = utcnow()
    with db() as c:
        c.execute('''INSERT INTO social_content(title,platform,content_type,body,media_url,scheduled_at,status,created_by,created_at,updated_at,published_at)
            VALUES(%s,'Facebook+Instagram','post',%s,%s,%s,'published',%s,%s,%s,%s)''',
            ('بوستر يومي ' + day.isoformat() + ' — ' + topic['head'], text + '\n\n' + '\n'.join(links), image_url, now, uid, now, now, now))


def claim(day, topic, text):
    with db() as c:
        return bool(c.execute('''INSERT INTO afaq_daily_posters(day,topic,caption,status,created_at,updated_at)
            VALUES(%s,%s,%s,'rendering',%s,%s) ON CONFLICT DO NOTHING RETURNING day''',
            (day, topic['key'], text, utcnow(), utcnow())).fetchone())


def run_for(day):
    """One bounded pass for a day. Claimed first: a crash never causes a second publish."""
    from app.prospect_autopilot import system_user
    topic = topic_for(day)
    text = caption(topic)
    if not claim(day, topic, text):
        return {'day': day.isoformat(), 'skipped': 'already_claimed'}
    uid = system_user()
    image = render_poster(topic)
    video = render_video(image)
    with db() as c:
        c.execute("UPDATE afaq_daily_posters SET image=%s,video=%s,status='publishing',updated_at=%s WHERE day=%s",
                  (image, video, utcnow(), day))
    image_url, video_url = media_urls(day)
    results = {}
    from app.meta_connect import MetaError, connected, credentials
    if connected():
        try:
            conn = credentials()
        except MetaError as exc:
            conn = None
            results['facebook'] = results['instagram'] = {'status': 'failed', 'error': str(exc)}
        if conn:
            for channel, fn in (('facebook', publish_facebook), ('instagram', publish_instagram)):
                try:
                    results[channel] = fn(conn, image_url, text)
                except Exception as exc:
                    results[channel] = {'status': 'failed', 'error': str(exc)[:300]}
                set_result(day, channel, results[channel])
    else:
        results['facebook'] = results['instagram'] = {'status': 'not_connected'}
    try:
        results['youtube_tiktok'] = publish_video(day, topic, text, video_url, uid)
    except Exception as exc:
        results['youtube_tiktok'] = {'status': 'failed', 'error': str(exc)[:300]}
    try:
        results['drafts'] = {'status': 'saved', 'content_ids': save_drafts(day, topic, text, image_url, uid)}
    except Exception as exc:
        results['drafts'] = {'status': 'failed', 'error': str(exc)[:200]}
    record_meta(day, topic, text, image_url, uid, results)
    ok = [k for k, v in results.items() if isinstance(v, dict) and v.get('status') in ('published', 'publishing', 'scheduled', 'saved')]
    final = 'done' if len(ok) == len(results) else ('partial' if ok else 'failed')
    with db() as c:
        c.execute('UPDATE afaq_daily_posters SET status=%s,results_json=%s,updated_at=%s WHERE day=%s',
                  (final, json.dumps(results, ensure_ascii=False), utcnow(), day))
    log(uid, 'daily_poster_run', 'afaq_daily_poster', None, day.isoformat() + ' · ' + topic['head'] + ' · ' + final)
    return {'day': day.isoformat(), 'status': final, 'results': {k: v.get('status') for k, v in results.items()}}


def due(now=None):
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(RIYADH)
    return now.date() if now.hour >= poster_hour() else None


def sync_pending():
    """Refresh the Zernio status of today's/yesterday's daily video so URLs reach the comment worker."""
    from app.social_publishing import connection, save_result
    from app.social_zernio import identifier, provider_request, publication_result
    with db() as c:
        rows = c.execute('''SELECT p.content_id,p.provider_post_id,p.payload_json FROM afaq_daily_posters d
            JOIN social_publications p ON p.content_id=d.zernio_content_id
            WHERE d.day >= CURRENT_DATE - 2 AND p.provider_post_id IS NOT NULL
            AND p.status IN ('submitting','scheduled','publishing')''').fetchall()
    if not rows:
        return 0
    key, _ = connection()
    for row in rows:
        try:
            response = provider_request(key, 'GET', '/posts/' + identifier(row['provider_post_id']))
            post_id, state, results = publication_result(response, json.loads(row['payload_json'])['platforms'])
            save_result(row['content_id'], post_id, state, results)
        except Exception as exc:
            print('DAILY_POSTER_SYNC', row['content_id'], type(exc).__name__, flush=True)
    return len(rows)


def tick():
    init()
    day = due()
    result = run_for(day) if day else None
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
                        print('DAILY_POSTER', result, flush=True)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print('DAILY_POSTER_ERROR', type(exc).__name__, str(exc)[:200], flush=True)
            await asyncio.sleep(300)

    @app.on_event('startup')
    async def start():
        app.state.daily_poster_worker = asyncio.create_task(loop())


# ---------- admin view ----------

@router.get('/daily-posters', response_class=HTMLResponse)
def admin_page(request: Request):
    from app.social_content import e, page
    from app.social_publishing import admin
    admin(request)
    init()
    rows = []
    with db() as c:
        rows = c.execute('SELECT day,topic,status,results_json,updated_at FROM afaq_daily_posters ORDER BY day DESC LIMIT 30').fetchall()
    today = dt.datetime.now(RIYADH).date()
    body = '<div class="nav"><a href="/content-center">مركز المحتوى</a><a href="/settings/meta">ربط Meta</a><a href="/settings/social">إعدادات النشر</a></div>'
    body += ('<div class="hero"><h1>البوستر اليومي</h1><p class="muted">بوستر واحد يوميًا الساعة ' + str(poster_hour()) +
             ':00 بتوقيت الرياض · فيسبوك وإنستغرام عبر Meta · YouTube وTikTok فيديو 8 ثوانٍ · مسودات X وLinkedIn. الحالة: <b>' +
             ('مفعّل' if enabled() else 'متوقف') + '</b></p><p>موضوع اليوم: <b>' + e(topic_for(today)['head']) +
             '</b> · <a href="/daily-posters/preview/' + str(TOPICS.index(topic_for(today))) + '.jpg" target="_blank">معاينة</a></p></div>')
    body += '<div class="card scroll"><table><tr><th>اليوم</th><th>الموضوع</th><th>الحالة</th><th>النتائج</th><th></th></tr>'
    for r in rows:
        res = json.loads(r['results_json'] or '{}')
        cells = ' · '.join(e(k) + ': ' + e((v or {}).get('status')) + (' <a target="_blank" rel="noopener" href="' + e(v['url']) + '">↗</a>' if isinstance(v, dict) and str(v.get('url', '')).startswith('https://') else '')
                           for k, v in res.items())
        day = r['day'].isoformat() if hasattr(r['day'], 'isoformat') else str(r['day'])
        body += ('<tr><td>' + e(day) + '</td><td>' + e(r['topic']) + '</td><td><span class="pill">' + e(r['status']) + '</span></td><td>' + cells +
                 '</td><td><a href="/media/daily-poster/' + e(day) + '.jpg" target="_blank">الصورة</a> · <a href="/media/daily-poster/' + e(day) + '.mp4" target="_blank">الفيديو</a></td></tr>')
    body += '</table></div>'
    return HTMLResponse(page(body), headers={'Cache-Control': 'no-store'})


@router.get('/daily-posters/preview/{index}.jpg')
def preview(index: int, request: Request):
    from app.social_publishing import admin
    admin(request)
    if not 0 <= index < len(TOPICS):
        raise HTTPException(404)
    return Response(render_poster(TOPICS[index]), media_type='image/jpeg', headers={'Cache-Control': 'no-store'})
