"""Work computer «fasah_fill» in a real browser against a FASAH-like screen (owner, 26 Nov 2026).

It must type into empty matching fields only and NEVER click a button, submit the form or press Enter.
No network: the FASAH address is served locally by the test.
"""
import importlib.util
import pathlib

import pytest

pytest.importorskip('requests')
sync_api = pytest.importorskip('playwright.sync_api')
_spec = importlib.util.spec_from_file_location('afaq_runner_fill', pathlib.Path(__file__).resolve().parents[1] / 'desktop-runner' / 'afaq_runner.py')
rn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rn)

URL = 'https://fasah.zatca.gov.sa/ar/broker/2.0/declaration/new'
SCREEN = """<!doctype html><html dir="rtl"><body>
<form id="dec" onsubmit="window.__submitted=true; return false;">
 <h2>بيانات الفاتورة</h2>
 <label for="inv">رقم الفاتورة</label><input id="inv">
 <label for="amt">قيمة الفاتورة</label><input id="amt" type="number" step="any">
 <label for="cur">العملة</label><select id="cur"><option>اختر</option><option>دولار أمريكي USD</option><option>ريال سعودي</option></select>
 <label for="pk">عدد الطرود</label><input id="pk">
 <h2>النقل</h2>
 <label for="bl">رقم البوليصة</label><input id="bl" value="OLD123">
 <label for="gw">الوزن القائم</label><input id="gw" readonly>
 <label for="nw">الوزن الصافي</label><input id="nw">
 <div><span>بلد المنشأ</span><div role="combobox" tabindex="0" style="width:120px;height:20px;border:1px solid">اختر</div></div>
 <label for="ref1">رقم المرجع</label><input id="ref1"><label for="ref2">رقم المرجع</label><input id="ref2">
 <button type="submit" onclick="window.__clicked=true">تقديم البيان</button>
 <button type="button" onclick="window.__clicked=true">حفظ</button>
</form>
<script>document.addEventListener('keydown', e => { if (e.key === 'Enter') window.__enter = true; });</script>
</body></html>"""


class FakeApi:
    base = 'https://example.invalid'

    def __init__(self):
        self.steps, self.files = [], []

    def post(self, path, payload=None):
        if path.endswith('/step'):
            self.steps.append(payload)
        if path.endswith('/file'):
            self.files.append(payload)
        return {}

    def get(self, path):
        return {'stop': False, 'approvals': {}}


@pytest.fixture()
def screen(tmp_path, monkeypatch):
    monkeypatch.setattr(rn, 'DOWNLOADS', tmp_path)
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel='chrome', headless=True)
        except Exception:
            try:
                browser = pw.chromium.launch(headless=True)
            except Exception as exc:
                pytest.skip('no browser: ' + type(exc).__name__)
        context = browser.new_context()
        context.route('https://fasah.zatca.gov.sa/**', lambda route: route.fulfill(status=200, content_type='text/html; charset=utf-8', body=SCREEN))
        page = context.new_page()
        page.goto(URL)
        yield context, page
        browser.close()


def run_fill(context, fields, items=None):
    api = FakeApi()
    task = rn.Task(api, {'id': 7, 'kind': 'fasah_fill', 'params': {'case_title': 'ETG0138695', 'fields': fields, 'items': items or [],
                                                                    'movement': 'ترانزيت إلى قطر'}},
                   ['fasah.zatca.gov.sa', 'zatca.gov.sa'], context)
    ok = task.do_fasah_fill()
    report = pathlib.Path(task.dir / 'fasah-fill-report.txt').read_text(encoding='utf-8')
    return ok, report, api


FIELDS = [
    {'key': 'invoice_number', 'label': 'رقم الفاتورة', 'value': 'INV-2026-77', 'synonyms': ['invoice number']},
    {'key': 'invoice_total', 'label': 'إجمالي الفاتورة كما ورد', 'value': '12,500.50', 'synonyms': ['قيمة الفاتورة']},
    {'key': 'currency', 'label': 'العملة', 'value': 'USD', 'synonyms': ['currency']},
    {'key': 'packages', 'label': 'عدد الطرود ووحدتها', 'value': '350 BAGS', 'synonyms': ['عدد الطرود']},
    {'key': 'bill_number', 'label': 'رقم بوليصة / مستند النقل', 'value': 'ETG0138695', 'synonyms': ['رقم البوليصة']},
    {'key': 'gross_weight', 'label': 'الوزن الإجمالي ووحدته', 'value': '21262 KG', 'synonyms': ['الوزن القائم']},
    {'key': 'net_weight', 'label': 'الوزن الصافي ووحدته', 'value': '21000 KG', 'synonyms': ['الوزن الصافي']},
    {'key': 'origin', 'label': 'بلد المنشأ', 'value': 'إثيوبيا', 'synonyms': []},
    {'key': 'ref', 'label': 'رقم المرجع', 'value': 'X1', 'synonyms': []},
    {'key': 'hs', 'label': 'رمز HS', 'value': '090111', 'synonyms': []},
]


def test_fills_only_empty_matching_fields_and_never_clicks_or_submits(screen):
    context, page = screen
    ok, report, api = run_fill(context, FIELDS, [{'description': 'Arabica coffee', 'quantity': '350', 'code': '0901.11'}])
    assert ok
    assert page.input_value('#inv') == 'INV-2026-77'
    assert page.input_value('#amt') == '12500.50'          # number field: digits only
    assert page.input_value('#pk') == '350 BAGS'
    assert page.input_value('#nw') == '21000 KG'
    assert page.input_value('#bl') == 'OLD123'              # never overwrites
    assert page.input_value('#gw') == ''                    # locked field untouched
    assert page.eval_on_selector('#cur', 'e => e.selectedIndex') == 0  # no exact option → manual
    assert page.input_value('#ref1') == '' and page.input_value('#ref2') == ''  # ambiguous → manual
    assert page.evaluate('[!!window.__clicked, !!window.__submitted, !!window.__enter]') == [False, False, False]
    assert page.url == URL
    for expected in ('لم أضغط أي زر', 'فيها قيمة مسبقًا', 'الخانة مقفلة', 'اخترها يدويًا', 'أكثر من خانة محتملة',
                     'لم أجد خانتها', 'Arabica coffee', 'ترانزيت إلى قطر', 'هيكل الشاشة'):
        assert expected in report, expected
    assert api.files and api.files[0]['verified']
    assert 'بدون ضغط أي زر' in api.steps[-2]['text']


def test_refuses_without_an_open_fasah_screen(tmp_path, monkeypatch):
    monkeypatch.setattr(rn, 'DOWNLOADS', tmp_path)
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel='chrome', headless=True)
        except Exception:
            pytest.skip('no browser')
        context = browser.new_context()
        context.new_page()
        task = rn.Task(FakeApi(), {'id': 8, 'kind': 'fasah_fill', 'params': {'fields': FIELDS}}, ['fasah.zatca.gov.sa'], context)
        assert task.do_fasah_fill() is False
        browser.close()
