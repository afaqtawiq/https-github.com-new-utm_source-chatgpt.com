"""خالد — التسجيل في منصة نقل بمتصفح حقيقي على نموذج «شاحنات الخليج» (طلب المالك، 26 نوفمبر 2026).

يجب أن يعبئ بيانات المؤسسة ويرفق المستندات فقط: لا كلمة مرور، ولا علامة إقرار، ولا ضغط أي زر، ولا إرسال، ولا Enter.
بدون شبكة: عنوان المنصة يُخدم محليًا من الاختبار.
"""
import base64
import hashlib
import importlib.util
import pathlib

import pytest

pytest.importorskip('requests')
sync_api = pytest.importorskip('playwright.sync_api')
_spec = importlib.util.spec_from_file_location('afaq_runner_signup', pathlib.Path(__file__).resolve().parents[1] / 'desktop-runner' / 'afaq_runner.py')
rn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rn)

REGISTER = (pathlib.Path(__file__).parent / 'fixtures' / 'gulf_trucks_register.html').read_text(encoding='utf-8')
LOGIN = """<!doctype html><html><body><h1>Login</h1><label>Company</label><input name="company"><label>Username</label><input name="u">
<label>Password</label><input type="password" name="p"><button onclick="window.__clicked=true">Login</button>
Don't have an account? <a href="https://app.gulf-transports.com/register/?lang=ar">Register</a></body></html>"""
PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF'
DOC_IDS = {'commercial_registration': '11111111-1111-1111-1111-111111111111', 'tax_certificate': '22222222-2222-2222-2222-222222222222',
           'national_address': '33333333-3333-3333-3333-333333333333'}


class FakeApi:
    base = 'https://example.invalid'

    def __init__(self):
        self.steps, self.files, self.docs = [], [], []

    def post(self, path, payload=None):
        (self.steps if path.endswith('/step') else self.files if path.endswith('/file') else []).append(payload)
        return {}

    def get(self, path):
        if '/document/' in path:
            self.docs.append(path.rsplit('/', 1)[1])
            return {'name': 'doc.pdf', 'mime': 'application/pdf', 'data_b64': base64.b64encode(PDF).decode(),
                    'sha256': hashlib.sha256(PDF).hexdigest()}
        return {'stop': False, 'approvals': {}}


def params(url):
    from_profile = {'legal_name': ('مؤسسة آفاق طويق للتخليص الجمركي', ['الاسم الكامل', 'الاسم القانوني']),
                    'short_name': ('afaq-tuwaiq', ['الاسم المختصر للحساب']), 'email': ('info@afaqtawiqs.net', ['البريد الإلكتروني']),
                    'phone': ('0530130435', ['رقم الهاتف']), 'address': ('جدة، طريق صاري', ['العنوان']),
                    'cr_number': ('4030123456', ['رقم السجل التجاري']), 'vat_number': ('300012345600003', ['رقم ضريبة القيمة المضافة']),
                    'username': ('afaqtuwaiq', ['اسم المستخدم لتسجيل الدخول'])}
    return {'url': url, 'platform': 'app.gulf-transports.com',
            'fields': [{'key': k, 'label': k, 'value': v, 'synonyms': syn} for k, (v, syn) in from_profile.items()],
            'documents': [{'kind': 'commercial_registration', 'doc_id': DOC_IDS['commercial_registration'], 'synonyms': ['سجل تجاري', 'السجل التجاري']},
                          {'kind': 'tax_certificate', 'doc_id': DOC_IDS['tax_certificate'], 'synonyms': ['شهادة ضريبة القيمة المضافة']},
                          {'kind': 'national_address', 'doc_id': DOC_IDS['national_address'], 'synonyms': ['العنوان الوطني']}]}


@pytest.fixture()
def browser_context(tmp_path, monkeypatch):
    monkeypatch.setattr(rn, 'DOWNLOADS', tmp_path)
    original = rn.Task.on_route

    def guarded(self, route):  # the runner's own allowlist guard, then the local copy of the site instead of the network
        route.continue_ = route.fallback
        return original(self, route)
    monkeypatch.setattr(rn.Task, 'on_route', guarded)
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel='chrome', headless=True)
        except Exception:
            try:
                browser = pw.chromium.launch(headless=True)
            except Exception as exc:
                pytest.skip('no browser: ' + type(exc).__name__)
        context = browser.new_context()

        def serve(route):
            body = REGISTER if '/register' in route.request.url else LOGIN
            route.fulfill(status=200, content_type='text/html; charset=utf-8', body=body)
        context.route('https://app.gulf-transports.com/**', serve)
        yield context
        browser.close()


@pytest.mark.parametrize('start', ['https://app.gulf-transports.com/register/?lang=ar', 'https://app.gulf-transports.com/'])
def test_fills_company_details_attaches_documents_and_never_submits(browser_context, start):
    api = FakeApi()
    task = rn.Task(api, {'id': 9, 'kind': 'platform_signup', 'params': params(start)}, ['app.gulf-transports.com'], browser_context)
    assert task.run()
    page = next(p for p in browser_context.pages if '/register' in p.url)
    assert page.input_value('#full_name') == 'مؤسسة آفاق طويق للتخليص الجمركي'
    assert page.input_value('#display_name') == 'afaq-tuwaiq'
    assert page.input_value('#cr_number') == '4030123456' and page.input_value('#vat_number') == '300012345600003'
    assert page.input_value('#s1_email') == 'info@afaqtawiqs.net' and page.input_value('#s1_phone') == '0530130435'
    assert page.input_value('#s1_username') == 'afaqtuwaiq'
    assert page.input_value('#s1_password') == '' and page.input_value('#s1_password2') == ''
    assert page.is_checked('#acknowledgment') is False
    for slot in ('#cr_document', '#vat_certificate', '#national_address_doc'):
        assert page.eval_on_selector(slot, 'e => e.files.length') == 1, slot
    assert page.evaluate('[!!window.__clicked, !!window.__submitted, !!window.__enter]') == [False, False, False]
    assert sorted(api.docs) == sorted(DOC_IDS.values())
    report = pathlib.Path(task.dir / 'platform-signup-report.txt').read_text(encoding='utf-8')
    assert 'لم أكتب كلمة المرور' in report and 'إرسال طلب التسجيل' in report and '✅ أُرفق' in report
    assert api.files and api.files[0]['verified']


def test_refuses_sites_outside_the_approved_list(browser_context):
    task = rn.Task(FakeApi(), {'id': 10, 'kind': 'platform_signup', 'params': params('https://evil.example.com/register')},
                   ['app.gulf-transports.com'], browser_context)
    with pytest.raises(ValueError):
        task.do_platform_signup()
