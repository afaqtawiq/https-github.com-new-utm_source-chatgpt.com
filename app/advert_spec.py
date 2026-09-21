"""Editable, bounded cinematic brief; no provider or database side effects."""
import copy

from app.media_fal import MediaError

BRAND = 'آفاق طويق'
TAGLINE = 'من الحدود... إلى وجهة تجارتك'
VOICE_ID = 'Arabic_FriendlyGuy'
TITLE = 'آفاق طويق — من الحدود إلى وجهة تجارتك'
CAPTION = ('كل شحنة تحمل فرصة.\nآفاق طويق للتخليص الجمركي والنقل والشحن والتخزين وخدمات الباب إلى الباب، '
           'في السعودية والخليج.\nتواصل معنا لطلب عرض سعر لشحنتك.\n'
           '#آفاق_طويق #التخليص_الجمركي #النقل #الشحن #التخزين')
STYLE = ('Photorealistic premium Saudi logistics commercial, navy and warm gold palette, practical sunrise light. '
         'Representative scene, not a documentary of the company fleet or staff. No text, no logos, no uniforms '
         'with official insignia, no government emblems. Physically correct equipment and safe operations. '
         'Keep the main subject in the central safe area with room for lower-third typography. ')
SCENES = [
    {'name': 'فرصة تتحرك', 'text': 'كل شحنة تحمل فرصة',
     'voice': 'كُلُّ شَحْنَةٍ تَحْمِلُ فُرْصَة... ورحلتُها تبدأُ بخطوةٍ مدروسة.',
     'image': 'One modern navy tractor-trailer with a secured container driving on a marked port road, cranes and stacked containers in the distance. Low three-quarter view.',
     'motion': 'Smooth lateral camera tracking beside the truck. It drives forward in its lane, wheels rotate with real road contact, preserve geometry and lighting. No sudden turns.'},
    {'name': 'التخليص الجمركي', 'text': 'التخليص الجمركي',
     'voice': 'مَعَ آفَاقِ طُوَيْق... خدماتُ تخليصٍ جُمركيٍّ تدعمُ رحلةَ تجارتِك.',
     'image': 'Close view of a logistics coordinator in neutral business clothing carefully reviewing shipping documents at a modern desk, blurred container yard through the window. Documents have no legible text or private data.',
     'motion': 'Slow motivated push-in toward the paperwork. One natural hand movement turns a single sheet. Preserve fingers and document edges. No magical graphics or official seals.'},
    {'name': 'النقل والشحن', 'text': 'النقل والشحن',
     'voice': 'نقلٌ وشحنٌ داخلَ المملكةِ وإلى الخليج.',
     'image': 'A modern navy tractor-trailer carrying a shipping container on a divided Saudi highway with desert mountains, correct axle geometry and lane markings. Wide roadside three-quarter view.',
     'motion': 'Ground-level tracking parallel to the moving truck, consistent forward movement in the marked lane and realistic wheel rotation. No drifting, reversing, floating or sudden camera rotation.'},
    {'name': 'التخزين والتسليم', 'text': 'التخزين · الباب إلى الباب',
     'voice': 'وتخزينٌ، وخدماتٌ من البابِ إلى الباب.',
     'image': 'Organized modern warehouse, forklift with forks fully under a secured pallet moving through a clear marked aisle, operator wearing basic safety equipment, neatly stacked shelves. No visible brand names.',
     'motion': 'Slow stable camera dolly along the warehouse aisle. Forklift travels gently forward with load low and secure. No pedestrians in its path, no floating pallets or geometry changes.'},
    {'name': 'هوية آفاق والدعوة للتواصل', 'text': 'اطلب عرض سعر لشحنتك',
     'voice': 'آفاقُ طُوَيْق... منَ الحدودِ إلى وِجهةِ تجارتِك. اطلبْ عرضَ سعر.',
     'image': '', 'motion': ''},
]


def default_plan():
    return {'title': TITLE, 'caption': CAPTION, 'ratios': ['9:16', '16:9'],
            'voice_id': VOICE_ID, 'scenes': copy.deepcopy(SCENES), 'reuse_job_id': None}


def plan_from_form(data):
    plan = default_plan()
    mode = data.get('format', 'both')
    if mode not in ('both', '9:16', '16:9'):
        raise MediaError('اختر مقاس الإعلان.')
    plan['ratios'] = ['9:16', '16:9'] if mode == 'both' else [mode]
    for key, limit in (('title', 150), ('caption', 2200)):
        value = str(data.get(key, '')).strip()
        if not 1 <= len(value) <= limit:
            raise MediaError('أكمل عنوان الإعلان ونص المنشور ضمن الطول المحدد.')
        plan[key] = value
    for i, scene in enumerate(plan['scenes']):
        fields = [('text', 48), ('voice', 180)]
        if i < 4:
            fields += [('image', 1800), ('motion', 1500)]
        for field, limit in fields:
            value = str(data.get(f'{field}_{i}', '')).strip()
            if not 1 <= len(value) <= limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
                raise MediaError('راجع نصوص اللقطة ' + str(i + 1) + ' وأطوالها.')
            scene[field] = value
    return plan


def step_specs(plan):
    """Speech first, then each image and its video; numbered immutable steps."""
    specs = [{'key': f'voice-{i}', 'stage': 'voice', 'scene': i, 'ratio': '',
              'prompt': s['voice'], 'depends_on': None} for i, s in enumerate(plan['scenes'])]
    for ratio in plan['ratios']:
        for i, scene in enumerate(plan['scenes'][:4]):
            if ratio == '9:16' and i == 0 and plan.get('reuse_job_id'):
                continue
            image_key = f'image-{ratio}-{i}'
            specs.append({'key': image_key, 'stage': 'image', 'scene': i, 'ratio': ratio,
                          'prompt': STYLE + scene['image'], 'depends_on': None})
            specs.append({'key': f'video-{ratio}-{i}', 'stage': 'video', 'scene': i, 'ratio': ratio,
                          'prompt': scene['motion'], 'depends_on': image_key})
    return specs
