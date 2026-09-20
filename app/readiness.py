"""Configuration and operational evidence; configured never means live-tested."""
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.storage import get_session, one, rows

router = APIRouter()


def configuration_status():
    present = lambda *names: all(bool(os.getenv(name, '').strip()) for name in names)
    direct = (present('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_WHATSAPP_FROM')
              if os.getenv('WHATSAPP_PROVIDER', 'meta').lower() == 'twilio'
              else present('WHATSAPP_ACCESS_TOKEN', 'WHATSAPP_PHONE_NUMBER_ID', 'WHATSAPP_APP_SECRET', 'WHATSAPP_VERIFY_TOKEN'))
    return [
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
    return {'release': '7.3.0-operational-repair', 'live_acceptance': 'pending',
            'external_actions_enabled': os.getenv('ENABLE_EXTERNAL_ACTIONS', '0') == '1',
            'integrations': configuration_status(),
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
    table = ''.join('<tr><td>' + esc(x['name']) + '</td><td>' + ('إعداد موجود — لم يُختبر حيًا' if x['configured'] else 'إعداد ناقص') + '</td><td>' + esc(x['detail']) + '</td></tr>' for x in data['integrations'])
    sources = ''.join('<tr><td>' + esc(x['name']) + '</td><td>' + esc(x['last_status'] or 'لم يُفحص') + '</td><td>' + esc(x['last_checked_at']) + '</td></tr>' for x in data['sources'])
    return HTMLResponse(page('جاهزية التشغيل', head(current(request), 'جاهزية التشغيل') +
        '<div class="card"><h2>حالة الاختبار التشغيلي</h2><p>التصحيحات البرمجية مطبقة. اختبار القنوات الحي ودورة النقل الكاملة لم يُعتمدا بعد.</p><p>صلاحية الإجراءات الخارجية: ' + ('مفعّلة؛ تخضع لاعتماد الإجراء' if data['external_actions_enabled'] else 'متوقفة؛ يمكن تجهيز المسودات') +
        '</p><p>Gmail: ' + ('ربط محفوظ؛ يحتاج اختبارًا حيًا' if data['gmail_connected'] else 'لا يوجد ربط محفوظ لهذا المستخدم') +
        '</p><a href="/settings/email">إعداد البريد</a></div><div class="card scroll"><table><tr><th>الوظيفة</th><th>الحالة</th><th>المتبقي</th></tr>' + table +
        '</table></div><div class="card scroll"><h2>آخر فحص للمصادر</h2><table><tr><th>المصدر</th><th>النتيجة</th><th>الوقت</th></tr>' + sources + '</table></div>'))
