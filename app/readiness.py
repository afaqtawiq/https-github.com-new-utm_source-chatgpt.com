"""Configuration and operational evidence; configured never means live-tested."""
import os
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.storage import get_session, one, rows

router = APIRouter()

def table_exists(name):
    return bool(one('SELECT to_regclass(?) AS name', (name,))['name'])


def operational_status(user_id):
    mail = one('SELECT enabled,test_status,synced_at,sync_error FROM spacemail_connections WHERE user_id=?', (user_id,))
    reply = one('SELECT enabled FROM official_reply_settings WHERE user_id=?', (user_id,))
    sent = one("SELECT COUNT(*) n FROM official_reply_log WHERE user_id=? AND status='sent'", (user_id,))['n']
    alert = one("SELECT status FROM agent_checks WHERE user_id=? AND kind='alert'", (user_id,))
    monitoring = one('SELECT enabled FROM production_monitor_settings WHERE user_id=?', (user_id,))
    mail_enabled = bool(mail and mail['enabled'])
    mail_tested = bool(mail_enabled and mail['test_status'] == 'received')
    result = [
        {'name':'البريد الرسمي afaq@shodai.cc', 'configured':mail_enabled,
         'state_label': ('تحتاج المزامنة مراجعة' if mail and mail['sync_error'] else
                         'نجح اختبار الإرسال والاستقبال' if mail_tested else 'يحتاج اختبارًا' if mail_enabled else 'غير مفعّل'),
         'detail': ('آخر مزامنة: ' + str(mail['synced_at'] or 'لم تسجل') if mail else 'اربط صندوق البريد الرسمي'),
         'url':'/settings/email/spacemail'},
        {'name':'الرد الأولي على البريد', 'configured':bool(reply and reply['enabled']),
         'state_label': 'مفعّل' if reply and reply['enabled'] else 'متوقف',
         'detail': f'ردود مسجلة كمرسلة: {sent}. هذه رسالة استلام ثابتة؛ لا تعالج الطلب أو تسعّره تلقائيًا.', 'url':'/official-replies'},
        {'name':'تنبيه تعطل الإنتاج', 'configured':bool(monitoring and monitoring['enabled']),
         'state_label': ('مفعّل — وصل تنبيه الاختبار' if alert and alert['status']=='received' else 'مفعّل — يحتاج اختبارًا') if monitoring and monitoring['enabled'] else 'متوقف',
         'detail':'يراقب إنتاج المحتوى. لا يُعد دليلًا على مراقبة كل عمليات الشحن.', 'url':'/agent-operations'},
    ]
    if table_exists('zernio_requests'):
        counts = rows("SELECT status,COUNT(*) n FROM zernio_requests WHERE agent='afaaq' GROUP BY status")
        totals = {row['status']:row['n'] for row in counts}
        result.append({'name':'طلبات العملاء عبر واتساب', 'configured':bool(os.getenv('ZERNIO_API_KEY') and os.getenv('ZERNIO_WEBHOOK_SECRET')),
            'state_label':'يحتاج متابعة الطلبات',
            'detail':f"استكمال بيانات: {totals.get('collecting',0)} · جاهز لمراجعة الإدارة: {totals.get('ready_for_review',0)}. اكتمال البيانات ليس تأكيد تنفيذ أو سعر.",
            'url':'/whatsapp-requests?agent=afaaq'})
    accepted = 0
    if table_exists('afaaq_tracking_updates'):
        accepted = one("SELECT COUNT(*) n FROM afaaq_tracking_updates WHERE state='accepted'")['n']
    result.append({'name':'التتبع اليدوي والرد على العميل', 'configured':True,
        'state_label':'قُبل إرسال تحديثات' if accepted else 'منشور — أول إرسال فعلي لم يثبت',
        'detail':f'تحديثات قبلها مزود واتساب: {accepted}. ارفع نتيجة الموقع والبوليصة، وطابق الحاوية ثم راجع وأرسل. قبول المزود لا يؤكد التسليم.',
        'url':'/whatsapp-requests?agent=afaaq'})
    result.append({'name':'قراءة مرفقات واتساب والتتبع دون تدخل', 'configured':False,
        'state_label':'غير مفعّل', 'detail':'المسار التشغيلي الحالي يعتمد على رفع نتيجة التتبع يدويًا.',
        'url':'/whatsapp-requests?agent=afaaq'})
    return result


def configuration_status():
    present = lambda *names: all(bool(os.getenv(name, '').strip()) for name in names)
    direct = (present('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_WHATSAPP_FROM')
              if os.getenv('WHATSAPP_PROVIDER', 'meta').lower() == 'twilio'
              else present('WHATSAPP_ACCESS_TOKEN', 'WHATSAPP_PHONE_NUMBER_ID', 'WHATSAPP_APP_SECRET', 'WHATSAPP_VERIFY_TOKEN'))
    from app.social_publishing import connection_status
    social = connection_status()
    published = None
    published_ok = False
    for candidate in rows("SELECT content_id,results_json,updated_at FROM social_publications WHERE status='published' ORDER BY updated_at DESC LIMIT 100"):
        try:
            results = json.loads(candidate['results_json'])
            published_ok = ({p['platform'] for p in results} == {'youtube','tiktok'} and
                            all(p.get('status') == 'published' and p.get('url') for p in results))
            if published_ok:
                published = candidate
                break
        except (ValueError, KeyError, TypeError):
            pass
    produced = one("SELECT id FROM media_jobs WHERE status='complete' AND kind='video' AND image_url IS NOT NULL AND video_url IS NOT NULL AND approved_at IS NOT NULL ORDER BY id DESC LIMIT 1")
    advert = one("SELECT j.id FROM advert_jobs j WHERE j.status='complete' AND j.approved_at IS NOT NULL AND EXISTS(SELECT 1 FROM advert_exports x WHERE x.job_id=j.id) ORDER BY j.id DESC LIMIT 1")
    return [
        {'name': 'نشر فيديوهات آفاق على YouTube وTikTok', 'configured': social['configured'], 'live_tested': published_ok, 'detail': ('ثبت نجاح النشر على الحسابين؛ راجع المحتوى رقم ' + str(published['content_id'])) if published_ok else 'يلزم إيصال نشر مؤكد للحسابين؛ حفظ الربط وحده لا يثبت نجاح النشر'},
        {'name': 'إنتاج الصور والفيديو عبر fal.ai', 'configured': bool(one('SELECT id FROM media_provider_settings WHERE id=1')), 'live_tested': bool(produced), 'detail': ('اكتملت صورة وفيديو في مهمة الإنتاج رقم ' + str(produced['id'])) if produced else 'اعتماد التكلفة ثم إنتاج فعلي وحفظ النتيجة؛ حفظ المفتاح لا يثبت نجاح التوليد'},
        {'name': 'إعلان كامل بالتعليق العربي والهوية', 'configured': bool(one('SELECT id FROM media_provider_settings WHERE id=1')), 'live_tested': bool(advert), 'detail': ('اكتمل الإعلان رقم ' + str(advert['id'])) if advert else 'المسار متاح؛ يحتاج اعتماد تكلفة إعلان ثم إنتاجًا حيًا ومراجعة الصوت والمونتاج'},
        {'name': 'أوامر واتساب الإدارية', 'configured': present('ZERNIO_API_KEY', 'ZERNIO_WEBHOOK_SECRET', 'WHATSAPP_COMMAND_OWNER', 'WHATSAPP_COMMAND_ACCOUNT_ID'), 'detail': 'تحتاج اختبار رسالة واردة وتنفيذ موثق من رقم الإدارة'},
        {'name': 'تفريغ الرسائل الصوتية', 'configured': present('OPENAI_API_KEY'), 'detail': 'يحتاج مفتاح تفريغ صوتي ثم اختبار رسالة صوتية'},
        {'name': 'إرسال عروض النقل عبر واتساب', 'configured': direct, 'detail': 'يحتاج إعداد مزود الإرسال واعتماد العرض قبل إرساله'},
        {'name': 'بحث الويب الآلي', 'configured': present('BRAVE_SEARCH_API_KEY'), 'detail': 'المصادر العامة تعمل بشكل مستقل؛ روابط البحث اليدوية لا تُحسب فرصًا'},
        {'name': 'بحث الشركات في الخرائط', 'configured': present('GOOGLE_MAPS_API_KEY'), 'detail': 'وجود شركة في الخرائط لا يثبت وجود طلب شراء'},
        {'name': 'إعداد ربط Gmail', 'configured': present('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'TOKEN_ENCRYPTION_KEY'), 'detail': 'إعداد OAuth وحده لا يثبت اتصال البريد أو صلاحية الإرسال'},
    ]


def snapshot(request):
    session = get_session(request.cookies.get('gla_session'))
    if not session:
        raise HTTPException(401, 'Login required')
    if session.get('role') != 'admin':
        raise HTTPException(403, 'Administrator access required')
    from app.zernio_receiver import ensure_intake_tables
    ensure_intake_tables()
    return {'release': '7.6.0-cinematic-studio', 'live_acceptance': 'pending',
            'external_actions_enabled': os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') == '1',
            'integrations': configuration_status(),
            'operations': operational_status(session['user_id']),
            'gmail_connected': bool(one("SELECT id FROM email_connections WHERE user_id=? AND status='connected'", (session['user_id'],))),
            'sources': rows('SELECT name,last_status,last_checked_at FROM source_watches ORDER BY id'),
            'workflow': rows('SELECT status,COUNT(*) count FROM freight_negotiations GROUP BY status ORDER BY status')}


@router.get('/api/v7/readiness')
def readiness_api(request: Request):
    return snapshot(request)


@router.get('/readiness', response_class=HTMLResponse)
def readiness_page(request: Request):
    from app.main import page, esc, head, current
    data = snapshot(request)
    table = ''.join('<tr><td>' + esc(x['name']) + '</td><td>' + ('اختبار إنتاج موثق ناجح' if x.get('live_tested') else ('إعداد موجود — لم يُختبر حيًا' if x['configured'] else 'إعداد ناقص')) + '</td><td>' + esc(x['detail']) + '</td></tr>' for x in data['integrations'])
    sources = ''.join('<tr><td>' + esc(x['name']) + '</td><td>' + esc(x['last_status'] or 'لم يُفحص') + '</td><td>' + esc(x['last_checked_at']) + '</td></tr>' for x in data['sources'])
    operations = ''.join('<tr><td><a href="' + esc(x['url']) + '">' + esc(x['name']) + '</a></td><td>' + esc(x['state_label']) + '</td><td>' + esc(x['detail']) + '</td></tr>' for x in data['operations'])
    return HTMLResponse(page('جاهزية التشغيل', head(current(request), 'جاهزية التشغيل') +
        '<div class="card"><h2>حالة الاختبار التشغيلي</h2><p>تعرض كل وظيفة دليل تشغيلها على حدة. دورة النقل الكاملة والقنوات الأخرى تحتفظ باختباراتها المستقلة.</p><p>صلاحية الإجراءات الخارجية: ' + ('مفعّلة؛ تخضع لاعتماد الإجراء' if data['external_actions_enabled'] else 'متوقفة؛ يمكن تجهيز المسودات') +
        '</p><a href="/settings/email/spacemail">البريد الرسمي</a></div><div class="card scroll"><h2>التشغيل الأساسي وخطوة العمل التالية</h2><table><tr><th>الوظيفة</th><th>الحالة الفعلية</th><th>الدليل والمتبقي</th></tr>' + operations +
        '</table></div><div class="card scroll"><h2>الإنتاج والتكاملات المساندة</h2><p>الصوت والخرائط والبحث الموسع وظائف مستقلة؛ عدم ربطها لا يمنع استقبال الطلبات النصية ومتابعتها يدويًا.</p><table><tr><th>الوظيفة</th><th>الحالة</th><th>المتبقي</th></tr>' + table +
        '</table></div><div class="card scroll"><h2>آخر فحص للمصادر</h2><table><tr><th>المصدر</th><th>النتيجة</th><th>الوقت</th></tr>' + sources + '</table></div>'))
