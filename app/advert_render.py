"""Bounded local montage. Remote media is downloaded separately; FFmpeg is file-only."""
import io
import json
import math
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
import wave

import httpx
from PIL import Image, ImageDraw, ImageFont, features

from app.advert_spec import BRAND, TAGLINE
from app.media_fal import MediaError, asset_url

MAX_EXPORT = 14 * 1024 * 1024
FONT_PATHS = ('/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
SIZES = {'9:16': (1080, 1920), '16:9': (1920, 1080)}
NAVY = (9, 28, 43)
GOLD = (235, 193, 103)


def prerequisites():
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe') or not features.check('raqm'):
        raise MediaError('محرك المونتاج العربي غير جاهز على الخادم. لم يبدأ الإنتاج المدفوع.')
    if not any(Path(p).is_file() for p in FONT_PATHS):
        raise MediaError('خط العرض العربي غير متاح. لم يبدأ الإنتاج.')


def font(size):
    return ImageFont.truetype(next(p for p in FONT_PATHS if Path(p).is_file()), size,
                              layout_engine=ImageFont.Layout.RAQM)


def text(draw, value, x, y, width, size=64, fill='white'):
    for point in range(size, 23, -2):
        face = font(point)
        if draw.textbbox((0, 0), value, font=face, direction='rtl', language='ar')[2] <= width:
            draw.text((x, y), value, font=face, fill=fill, anchor='mm', direction='rtl', language='ar')
            return
    raise MediaError('النص أطول من مساحة العرض؛ اختصر نص الشاشة.')


def normalized_logo(raw):
    if len(raw) > 2 * 1024 * 1024:
        raise MediaError('حجم الشعار الأقصى 2 ميغابايت.')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in ('PNG', 'JPEG', 'WEBP') or source.width * source.height > 16000000:
                raise ValueError()
            image = source.convert('RGBA')
            image.thumbnail((900, 500))
            out = io.BytesIO()
            image.save(out, 'PNG')
            return out.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise MediaError('ارفع ملف شعار PNG أو JPEG أو WebP صالحًا.') from None


def card(ratio, scene, *, end=False, logo=None, preview=False):
    w, h = SIZES[ratio]
    image = Image.new('RGBA', (w, h), (*NAVY, 255) if end else (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = 100 if ratio == '9:16' else 140
    if end:
        draw.rectangle((margin, int(h * .24), w-margin, int(h*.24)+4), fill=GOLD)
        if logo:
            with Image.open(io.BytesIO(logo)) as original:
                mark = original.convert('RGBA')
                mark.thumbnail((int(w*.36), int(h*.18)))
                image.alpha_composite(mark, ((w-mark.width)//2, int(h*.27)))
        text(draw, BRAND, w//2, int(h*.50), w-2*margin, 100, GOLD)
        text(draw, 'التخليص الجمركي · النقل · الشحن', w//2, int(h*.59), w-2*margin, 48)
        text(draw, 'التخزين · خدمات الباب إلى الباب', w//2, int(h*.65), w-2*margin, 48)
        text(draw, TAGLINE, w//2, int(h*.74), w-2*margin, 52)
        text(draw, scene['text'], w//2, int(h*.84), w-2*margin, 50, GOLD)
    else:
        top = 120 if ratio == '9:16' else 65
        draw.rounded_rectangle((margin-28, top-44, w-margin+28, top+52), radius=20, fill=(*NAVY, 215))
        text(draw, BRAND, w//2, top, w-2*margin, 48, GOLD)
        if logo:
            with Image.open(io.BytesIO(logo)) as original:
                mark = original.convert('RGBA')
                mark.thumbnail((150, 75))
                image.alpha_composite(mark, (margin, top+65))
        center = int(h*.77) if ratio == '9:16' else int(h*.80)
        draw.rounded_rectangle((margin-28, center-80, w-margin+28, center+85), radius=24, fill=(*NAVY, 228))
        draw.rectangle((margin, center-55, margin+100, center-51), fill=GOLD)
        text(draw, scene['text'], w//2, center+10, w-2*margin, 66)
    if preview:
        text(draw, 'معاينة النص والهوية', w//2, h-60, w-2*margin, 32, GOLD)
    out = io.BytesIO()
    image.save(out, 'PNG')
    return out.getvalue()


def command(args, timeout=240):
    try:
        return subprocess.run(args, check=True, capture_output=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        # Avoid raw provider URLs, user text and local paths leaking through ffmpeg stderr.
        raise MediaError('تعذر إكمال المونتاج. حُفظت نتائج التوليد ويمكن إعادة المونتاج دون توليد مدفوع.') from None


def probe(path):
    return json.loads(command(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
        '-show_streams', '-show_format', '-of', 'json', str(path)], 25))


def download(url, stage, path):
    url = asset_url(url, stage)
    limit = 12*1024*1024 if stage == 'voice' else 48*1024*1024
    try:
        with httpx.Client(timeout=httpx.Timeout(60, connect=15), follow_redirects=False) as client:
            with client.stream('GET', url) as response:
                if response.status_code != 200:
                    raise MediaError('تعذر تنزيل وسيط الإنتاج؛ لم يُكرر التوليد.')
                count = 0
                with open(path, 'wb') as output:
                    for chunk in response.iter_bytes(65536):
                        count += len(chunk)
                        if count > limit:
                            raise MediaError('حجم وسيط الإنتاج أكبر من حد المونتاج.')
                        output.write(chunk)
                if count < 100:
                    raise MediaError('ملف الإنتاج فارغ أو غير صالح.')
    except httpx.HTTPError:
        raise MediaError('تعذر تنزيل وسيط الإنتاج. يمكن إعادة المونتاج دون إعادة التوليد.') from None


def sound_bed(path, duration):
    """Quiet original transition sound; no sampled or third-party music."""
    rng = random.Random(71)
    rate = 22050
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        block = bytearray()
        for n in range(math.ceil(duration * rate)):
            t = n/rate
            edge = min(1, t/2, max(0, duration-t)/2)
            pad = sum(math.sin(2*math.pi*f*t) for f in (110, 164.81, 220))/3
            pulse = math.exp(-((t % 5)/.18)**2)
            value = edge * (.025*pad + .02*pulse*rng.uniform(-1, 1))
            block.extend(struct.pack('<h', int(value*32767)))
            if len(block) >= 65536:
                output.writeframes(block)
                block.clear()
        output.writeframes(block)


def render(plan, outputs, *, logo=None, fetch=download):
    prerequisites()
    result = {}
    base = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-filter_complex_threads', '1']
    with tempfile.TemporaryDirectory(prefix='afaaq-ad-') as folder:
        root = Path(folder)
        durations = []
        for i in range(5):
            audio = root/f'voice-{i}.mp3'
            fetch(outputs[f'voice-{i}'], 'voice', audio)
            try:
                seconds = float(probe(audio)['format']['duration'])
            except (KeyError, ValueError, TypeError):
                raise MediaError('تعذر قراءة مدة التعليق الصوتي.') from None
            if not .3 <= seconds <= 6.2:
                raise MediaError('مدة تعليق اللقطة ' + str(i+1) + ' لا تناسب الإعلان؛ يلزم مراجعة النص قبل إنتاج جديد.')
            durations.append(max(5.0, seconds+.25))
        if sum(durations) > 30.5:
            raise MediaError('مدة التعليق تتجاوز 30 ثانية؛ حُفظ الصوت للمراجعة.')
        bed = root/'bed.wav'
        sound_bed(bed, sum(durations))
        for ratio in plan['ratios']:
            w, h = SIZES[ratio]
            segments = []
            for i, scene in enumerate(plan['scenes']):
                duration = durations[i]
                overlay = root/f'card-{i}.png'
                overlay.write_bytes(card(ratio, scene, end=i == 4, logo=logo))
                out = root/f'segment-{i}.mp4'
                inputs = []
                if i < 4:
                    clip = root/f'clip-{i}.mp4'
                    fetch(outputs[f'video-{ratio}-{i}'], 'video', clip)
                    meta = probe(clip)
                    vids = [s for s in meta.get('streams', []) if s.get('codec_type') == 'video']
                    if not vids or not 4.7 <= float(meta['format']['duration']) <= 6.5:
                        raise MediaError('مدة المشهد أو ملف الفيديو لا يطابق خطة الإعلان.')
                    aspect = vids[0]['width']/vids[0]['height']
                    if abs(aspect - w/h) > .08:
                        raise MediaError('مقاس المشهد لا يطابق المقاس المعتمد؛ لم يُقصّ المشهد تلقائيًا.')
                    inputs = ['-protocol_whitelist', 'file,pipe', '-i', str(clip), '-loop', '1', '-i', str(overlay)]
                    vf = f'[0:v]scale={w}:{h},setsar=1,fps=25,tpad=stop_mode=clone:stop_duration=2[bg];[bg][1:v]overlay=0:0[v]'
                    ai = 2
                else:
                    inputs = ['-loop', '1', '-i', str(overlay)]
                    vf = f'[0:v]scale={w}:{h},setsar=1,fps=25[v]'
                    ai = 1
                inputs += ['-protocol_whitelist', 'file,pipe', '-i', str(root/f'voice-{i}.mp3')]
                af = f';[{ai}:a]loudnorm=I=-16:TP=-1.5:LRA=11,apad,atrim=duration={duration},aresample=44100[a]'
                command(base + inputs + ['-filter_complex', vf+af, '-map', '[v]', '-map', '[a]',
                    '-t', str(duration), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22',
                    '-maxrate', '2500k', '-bufsize', '5000k', '-pix_fmt', 'yuv420p', '-threads', '2',
                    '-c:a', 'aac', '-b:a', '128k', '-ar', '44100', '-ac', '2', str(out)])
                segments.append(out)
            listing = root/'segments.txt'
            listing.write_text(''.join("file '" + p.name + "'\n" for p in segments))
            final = root/'final.mp4'
            command(base + ['-protocol_whitelist', 'file,pipe', '-f', 'concat', '-safe', '1', '-i', str(listing),
                '-i', str(bed), '-filter_complex', '[0:a][1:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]',
                '-map', '0:v:0', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart', '-t', str(sum(durations)), str(final)])
            meta = probe(final)
            videos = [s for s in meta['streams'] if s['codec_type'] == 'video']
            audios = [s for s in meta['streams'] if s['codec_type'] == 'audio']
            if (len(videos) != 1 or not audios or videos[0]['codec_name'] != 'h264'
                    or (videos[0]['width'], videos[0]['height']) != (w, h)
                    or not 24.8 <= float(meta['format']['duration']) <= 31 or final.stat().st_size > MAX_EXPORT):
                raise MediaError('لم يجتز الملف النهائي فحص المقاس والمدة والصوت والحجم.')
            result[ratio] = {'data': final.read_bytes(), 'duration': float(meta['format']['duration']),
                             'width': w, 'height': h}
    return result
