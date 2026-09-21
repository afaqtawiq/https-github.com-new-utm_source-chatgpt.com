"""Arabic TTS on the same encrypted fal account, with conservative cost ceilings."""
from decimal import Decimal, InvalidOperation, ROUND_UP
import re

from app import media_fal as fal
from app.advert_spec import VOICE_ID


def voice_rate(key):
    data = fal.call(key, 'GET', fal.PRICING, params={'endpoint_id': fal.VOICE_MODEL})
    entries = [x for x in data.get('prices', []) if isinstance(x, dict) and x.get('endpoint_id') == fal.VOICE_MODEL]
    if len(entries) != 1 or entries[0].get('currency') != 'USD':
        raise fal.MediaError('تعذر التحقق من سعر التعليق العربي. لم يبدأ الإنتاج.')
    entry = entries[0]
    unit = re.sub(r'[_-]+', ' ', str(entry.get('unit', '')).strip().lower())
    unit = ' '.join(unit.split())
    denominators = {'character': 1, 'characters': 1, 'char': 1, 'chars': 1,
                    '1000 characters': 1000, '1000 chars': 1000, '1k characters': 1000,
                    '1k chars': 1000, 'kilochars': 1000, '1000000 characters': 1000000,
                    '1m characters': 1000000, 'million characters': 1000000}
    if unit not in denominators:
        label = unit if re.fullmatch(r'[a-z0-9 ]{1,40}', unit) else 'unknown'
        raise fal.MediaError('يلزم مراجعة وحدة سعر الصوت (' + label + ') قبل الإنتاج.')
    try:
        rate = Decimal(str(entry['unit_price'])) / denominators[unit]
        if not rate.is_finite() or rate <= 0 or rate > Decimal('.01'):
            raise ValueError()
    except (InvalidOperation, KeyError, ValueError):
        raise fal.MediaError('سعر التعليق الصوتي غير صالح.') from None
    return rate


def step_cost(step, rates):
    # Round each separate request conservatively, including a 1,000-character floor.
    # UTF-8 byte count is also an upper bound on text/codepoint billing.
    units = max(1000, len(step['prompt'].encode('utf-8'))) if step['stage'] == 'voice' else 1
    return (rates[step['stage']] * units).quantize(Decimal('.000001'), rounding=ROUND_UP)


def rates(key):
    return {**fal.prices(key), 'voice': voice_rate(key)}


def submit(key, step, *, image_url=None):
    if step['stage'] != 'voice':
        return fal.submit(key, step['stage'], step['prompt'], ratio=step['ratio'], image_url=image_url)
    payload = {'text': step['prompt'], 'language_boost': 'Arabic', 'output_format': 'url',
               'voice_setting': {'voice_id': VOICE_ID, 'speed': 1.08, 'pitch': -2, 'vol': 1, 'emotion': 'neutral'},
               'audio_setting': {'sample_rate': 44100, 'bitrate': 128000, 'format': 'mp3', 'channel': 1}}
    data = fal.call(key, 'POST', fal.QUEUE + fal.VOICE_MODEL, payload=payload)
    rid = data.get('request_id')
    return {'request_id': rid,
            'status_url': fal.queue_url(data.get('status_url'), fal.VOICE_MODEL, rid, status=True),
            'response_url': fal.queue_url(data.get('response_url'), fal.VOICE_MODEL, rid)}


def result(key, stage, receipt):
    if stage != 'voice':
        return fal.result(key, stage, receipt)
    rid = receipt['request_id']
    state = fal.call(key, 'GET', fal.queue_url(receipt['status_url'], fal.VOICE_MODEL, rid, status=True))
    if state.get('request_id', rid) != rid:
        raise fal.MediaError('لم تطابق نتيجة الصوت الطلب.')
    if state.get('status') in ('IN_QUEUE', 'IN_PROGRESS'):
        return None
    if state.get('status') != 'COMPLETED' or state.get('error') or state.get('error_type'):
        raise fal.MediaError('تعذر توليد التعليق. راجع الطلب الموجود قبل أي إنتاج جديد.')
    data = fal.call(key, 'GET', fal.queue_url(receipt['response_url'], fal.VOICE_MODEL, rid))
    audio = data.get('audio')
    return fal.asset_url(audio.get('url') if isinstance(audio, dict) else None, 'voice')
