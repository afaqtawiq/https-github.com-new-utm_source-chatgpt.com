"""Runner on a local dummy FASAH-like page: details hidden in a row menu, collapsed invoice sections, a site menu
link with the same word, and dangerous buttons that must never be clicked."""
import importlib.util
import pathlib
import pytest

pytest.importorskip('requests')
sync_api = pytest.importorskip('playwright.sync_api')
_spec = importlib.util.spec_from_file_location('afaq_runner_d', pathlib.Path(__file__).resolve().parents[1] / 'desktop-runner' / 'afaq_runner.py')
rn = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(rn)

PAGE = """<!doctype html><html lang=ar dir=rtl><body>
<nav><a href="#" onclick="window.bad='nav'">الفواتير</a></nav>
<main><table>
<tr><td>20261101000001</td><td>111111</td><td>01/11/2026</td><td>فسح كلي <a href="#" onclick="show(111111)">إظهار التفاصيل</a></td></tr>
<tr><td>20261102000002</td><td>222222</td><td>02/11/2026</td><td>تحت المعالجة
 <button aria-haspopup="true" onclick="this.nextElementSibling.style.display='block'">⋮</button>
 <div style="display:none"><a href="#" onclick="show(222222)">إظهار التفاصيل</a></div></td></tr>
</table></main>
<div role="dialog" id="dlg" style="display:none"><h3>تفاصيل بيان الإستيراد</h3><button onclick="dlg.style.display='none'">إغلاق</button>
<button onclick="window.bad='cancel'">إلغاء البيان</button><div>ملخص الطلب</div><div onclick="void 0">تفاصيل الطلب</div>
<div onclick="sec(this)">معلومات البيان الأساسية </div><div hidden>المستورد: سلة الرحائب</div>
<div onclick="sec(this)">الفواتير </div><div hidden>رقم الفاتورة AB-584 قيمة الفاتورة 7000</div>
<div onclick="sec(this)">تفاصيل فاتورة البيان الجمركي</div><div hidden>الرسوم الجمركية 449.53</div>
<button onclick="window.bad='submit'">تقديم الطلب</button></div>
<script>function show(n){dlg.style.display='block';dlg.dataset.n=n}
function sec(e){e.nextElementSibling.hidden=false}</script></body></html>"""


class Fake(rn.Task):
    def __init__(self):
        self.steps = []

    def wait(self, page, seconds):
        page.wait_for_timeout(50)

    def step(self, text, ok=True, page=None):
        self.steps.append(text)


@pytest.mark.parametrize('number', ['111111', '222222'])
def test_details_open_and_sections_expand(number):
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # no browser on this machine
            pytest.skip(str(exc)[:80])
        page = browser.new_page()
        page.set_content(PAGE)
        task = Fake()
        task.open_details(page, page.locator('tr', has_text=number).last, number)
        assert page.locator('#dlg').is_visible() and page.locator('#dlg').get_attribute('data-n') == number
        grown = task.expand_details(page)
        text = page.locator('body').inner_text()
        assert grown > 0 and 'قيمة الفاتورة 7000' in text and '449.53' in text and 'سلة الرحائب' in text
        assert page.evaluate('window.bad') is None  # never the site menu, «إلغاء البيان» or «تقديم الطلب»
        browser.close()
