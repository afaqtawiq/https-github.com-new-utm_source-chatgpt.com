"""Afaq Tuwaiq work-computer runner.

Runs on a dedicated work computer and opens its OWN browser profile, where you sign in to sites yourself.
It never types passwords/OTP codes and never stores them, never exports cookies, and only opens allowlisted sites.

Security:
- The device token is kept in Windows Credential Manager (keyring), never in a file or in the code.
  `python afaq_runner.py --reset` removes it; rotate/revoke it from /agent-runner.
- Every navigation, redirect, popup and download is checked against the allowlist; anything else is blocked and
  stops the task.
- Stop works during execution: the runner polls the server and aborts in-flight requests.
- Submitting forms, paying, deleting or sending data waits for the manager's approval of that single action.
- No screenshots of sign-in pages or pages showing a password field.
"""
import argparse
import base64
import csv
import hashlib
import io
import json
import os
import pathlib
import re
import sys
import threading
import time
from urllib.parse import urlparse

import requests

SERVICE = 'AfaqTuwaiqRunner'
HOME = pathlib.Path(os.getenv('APPDATA') or pathlib.Path.home() / '.config') / 'AfaqRunner'
CONFIG = HOME / 'config.json'
PROFILE = pathlib.Path(os.getenv('LOCALAPPDATA') or pathlib.Path.home() / '.local' / 'share') / 'AfaqRunner' / 'browser-profile'
DOWNLOADS = pathlib.Path(os.getenv('AFAQ_RUNNER_DOWNLOADS') or pathlib.Path.home() / 'Documents' / 'AfaqRunner')
FASAH = 'https://fasah.zatca.gov.sa/ar/broker/2.0/'
SENSITIVE = re.compile(r'(دفع|سداد|ادفع|حذف|احذف|إلغاء|الغاء|إرسال|ارسال|اعتماد|تأكيد|تاكيد|submit|pay|delete|remove|confirm|send|save)', re.I)
SECRET_FIELD = re.compile(r'(password|passwd|otp|رمز|كلمة|cvv|card|iban|ايبان|بطاقة)', re.I)


class Stop(Exception):
    pass


# ---------- configuration and token (secure storage) ----------

def load_server():
    if CONFIG.exists():
        return json.loads(CONFIG.read_text(encoding='utf-8'))['server']
    HOME.mkdir(parents=True, exist_ok=True)
    server = input('رابط نظام آفاق طويق [https://gulf-logistics-ai-v7-production.up.railway.app]: ').strip() or \
        'https://gulf-logistics-ai-v7-production.up.railway.app'
    CONFIG.write_text(json.dumps({'server': server.rstrip('/')}), encoding='utf-8')
    return server.rstrip('/')


def load_token(store=None):
    import keyring
    store = store or keyring
    token = store.get_password(SERVICE, 'device-token')
    if not token:
        import getpass
        token = getpass.getpass('رمز الجهاز من صفحة /agent-runner (لن يظهر أثناء الكتابة): ').strip()
        store.set_password(SERVICE, 'device-token', token)
    return token


def reset_token(store=None):
    import keyring
    store = store or keyring
    try:
        store.delete_password(SERVICE, 'device-token')
    except Exception:
        pass


class Api:
    def __init__(self, base, token):
        self.base, self.headers = base.rstrip('/'), {'X-Runner-Token': token}

    def _send(self, method, path, payload, timeout, tries):
        # The system can answer slowly while it reads a declaration: wait longer and try again instead of failing the task.
        last = None
        for attempt in range(tries):
            try:
                r = requests.request(method, self.base + path, json=payload, headers=self.headers, timeout=timeout)
                r.raise_for_status()
                return r.json()
            except (requests.Timeout, requests.ConnectionError) as exc:
                last = exc
                time.sleep(3 + 4 * attempt)
        raise last

    def post(self, path, payload=None):
        # «claim» is not repeated here (a lost answer could leave a claimed task behind); the main loop asks again.
        return self._send('POST', path, payload or {}, 90, 1 if path.endswith('/claim') else 3)

    def get(self, path):
        return self._send('GET', path, None, 60, 3)


# ---------- checks ----------

def allowed(url, domains, loopback=False):
    p = urlparse(str(url or ''))
    host = (p.hostname or '').lower()
    if p.scheme in ('about', 'data', 'blob') or url in ('about:blank', ''):
        return True
    schemes = ('https', 'http') if loopback and host == '127.0.0.1' else ('https',)
    return p.scheme in schemes and any(host == d or host.endswith('.' + d) for d in domains)


def verify(path):
    """True only if the saved file exists, is non-empty and opens as its type."""
    data = pathlib.Path(path).read_bytes()
    if not data:
        return False
    name = str(path).lower()
    if name.endswith('.pdf'):
        return data.startswith(b'%PDF') and b'%%EOF' in data[-2048:]
    if name.endswith('.xlsx'):
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                return z.testzip() is None and '[Content_Types].xml' in z.namelist()
        except zipfile.BadZipFile:
            return False
    if name.endswith('.csv'):
        try:
            return len(list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))) > 1
        except UnicodeDecodeError:
            return False
    if name.endswith('.txt'):
        try:
            return bool(data.decode('utf-8').strip())
        except UnicodeDecodeError:
            return False
    return False


MIME = {'.pdf': 'application/pdf', '.csv': 'text/csv', '.txt': 'text/plain', '.png': 'image/png',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}


# ---------- task execution ----------

class Task:
    def __init__(self, api, task, domains, context, loopback=False):
        self.api, self.id, self.kind, self.params = api, task['id'], task['kind'], task['params']
        self.domains, self.context, self.loopback = domains, context, loopback
        self.dir = DOWNLOADS / f'task-{self.id}'
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stopped = threading.Event()
        self.keep = set()
        self.blocked = []
        self.last_poll = 0

    # control
    def poll(self, force=False):
        if self.stopped.is_set():
            raise Stop()
        if force or time.time() - self.last_poll > 2:
            self.last_poll = time.time()
            if self.api.get(f'/api/runner/tasks/{self.id}/control').get('stop'):
                self.stopped.set()
                raise Stop()

    def wait(self, page, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.poll()
            if self.blocked:
                raise ValueError('حاول الموقع فتح عنوان غير مسموح؛ أوقفت المهمة.')
            page.wait_for_timeout(500)

    # guards (installed on the browser context)
    def on_route(self, route):
        req = route.request
        if self.stopped.is_set():
            return route.abort()
        # Only top-level page navigations are restricted; embedded frames of an allowed site (sign-in widgets,
        # accessibility tools) must load or the site itself breaks.
        top = False
        try:
            top = req.is_navigation_request() and req.frame.parent_frame is None
        except Exception:
            top = req.is_navigation_request()
        if top and not allowed(req.url, self.domains, self.loopback):
            self.blocked.append(req.url)
            return route.abort('blockedbyclient')
        return route.continue_()

    def on_page(self, page):
        def check(*_):
            if not allowed(page.url, self.domains, self.loopback):
                self.blocked.append(page.url)
                try:
                    page.close()
                except Exception:
                    pass
        page.on('framenavigated', lambda frame: check() if frame == page.main_frame else None)
        page.on('download', self.on_download)

    def on_download(self, download):
        if not allowed(download.url, self.domains, self.loopback):
            self.blocked.append(download.url)
            download.cancel()

    def safe_for_screenshot(self, page):
        if re.search(r'(login|signin|auth|otp)', page.url, re.I):
            return False
        try:
            return page.locator('input[type=password]:visible').count() == 0
        except Exception:
            return False

    def step(self, text, ok=True, page=None):
        shot = None
        if page is not None and self.safe_for_screenshot(page):
            try:
                shot = base64.b64encode(page.screenshot(full_page=False, type='png')).decode()
            except Exception:
                shot = None
        print(('✓ ' if ok else '✗ ') + text, flush=True)
        r = self.api.post(f'/api/runner/tasks/{self.id}/step', {'text': text, 'ok': ok, 'screenshot_b64': shot,
                                                               'url': page.url if page is not None else ''})
        if r.get('stop'):
            self.stopped.set()
            raise Stop()

    def approval(self, action, detail, page=None):
        """Ask the manager for ONE sensitive action and wait (max 15 minutes). Returns True only if approved."""
        self.step('بانتظار موافقتك على: ' + action, page=page)
        aid = str(self.api.post(f'/api/runner/tasks/{self.id}/approval', {'action': action, 'detail': detail})['approval_id'])
        end = time.time() + 15 * 60
        while time.time() < end:
            state = self.api.get(f'/api/runner/tasks/{self.id}/control')
            if state.get('stop'):
                self.stopped.set()
                raise Stop()
            decision = state.get('approvals', {}).get(aid)
            if decision in ('approved', 'denied'):
                self.step(('تمت الموافقة على: ' if decision == 'approved' else 'رُفض: ') + action, decision == 'approved')
                return decision == 'approved'
            time.sleep(3)
        return False

    def upload(self, path, source_url=''):
        data = pathlib.Path(path).read_bytes()
        ok = verify(path)
        mime = MIME.get(pathlib.Path(path).suffix.lower(), 'application/octet-stream')
        self.api.post(f'/api/runner/tasks/{self.id}/file', {'name': pathlib.Path(path).name, 'mime': mime, 'verified': ok,
                                                           'sha256': hashlib.sha256(data).hexdigest(), 'source_url': source_url,
                                                           'data_b64': base64.b64encode(data).decode()})
        self.step(f'حُفظ {pathlib.Path(path).name} ({len(data):,} بايت) — ' + ('تم التحقق أنه يفتح' if ok else 'فشل التحقق: الملف لا يفتح'), ok)
        return ok

    def open(self, url):
        if not allowed(url, self.domains, self.loopback):
            raise ValueError('موقع غير مسموح: ' + url)
        page = self.context.new_page()
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        if self.blocked or not allowed(page.url, self.domains, self.loopback):
            raise ValueError('حاول الموقع التحويل إلى عنوان غير مسموح؛ أوقفت المهمة.')
        return page

    def run(self):
        self.context.route('**/*', self.on_route)
        self.context.on('page', self.on_page)
        try:
            return getattr(self, 'do_' + self.kind)()
        finally:
            for p in list(self.context.pages)[1:]:
                if p in self.keep:
                    continue
                try:
                    p.close()
                except Exception:
                    pass
            self.context.unroute('**/*')

    # kinds
    def do_download_test(self):
        url = self.api.base + '/agent-runner/test-file.pdf'
        self.step('بدأت التجربة: تنزيل ملف تجريبي من النظام')
        self.poll(force=True)
        r = self.context.request.get(url, timeout=60000)
        path = self.dir / 'afaq-runner-test.pdf'
        path.write_bytes(r.body())
        return self.upload(path)

    def do_download_file(self):
        url = self.params['url']
        if not allowed(url, self.domains, self.loopback):
            raise ValueError('موقع غير مسموح')
        self.poll(force=True)
        r = self.context.request.get(url, timeout=120000, max_redirects=0)
        if 300 <= r.status < 400:
            target = r.headers.get('location', '')
            if not allowed(target, self.domains, self.loopback):
                raise ValueError('التنزيل يحول إلى عنوان غير مسموح؛ أوقفت.')
            r = self.context.request.get(target, timeout=120000, max_redirects=0)
        name = re.sub(r'[^\w.\-]', '_', pathlib.Path(urlparse(url).path).name or 'download')
        path = self.dir / name
        path.write_bytes(r.body())
        self.step(f'نزل الملف ({len(r.body()):,} بايت)')
        return self.upload(path, url)

    def do_read_page(self):
        page = self.open(self.params['url'])
        self.wait(page, 3)
        self.step('فتحت الصفحة: ' + (page.title() or page.url), page=page)
        text = page.inner_text('body').strip()
        if not text:
            self.step('الصفحة لا تحتوي نصًا يمكن حفظه', False)
            return False
        path = self.dir / 'page.txt'
        path.write_text(text, encoding='utf-8')
        return self.upload(path, page.url)

    def do_fill_form(self):
        page = self.open(self.params['url'])
        self.wait(page, 2)
        for field in self.params.get('fields') or []:
            label, value = str(field.get('label') or ''), str(field.get('value') or '')
            if SECRET_FIELD.search(label):
                raise ValueError('لا أعبئ كلمات المرور أو رموز التحقق أو بيانات البطاقات.')
            box = page.get_by_label(label, exact=False).first
            if (box.get_attribute('type') or '').lower() == 'password':
                raise ValueError('الحقل حقل كلمة مرور؛ لا أعبئه.')
            box.fill(value)
            self.poll()
        self.step('عبأت الحقول (' + str(len(self.params.get('fields') or [])) + ') — لم أرسل شيئًا بعد', page=page)
        submit = str(self.params.get('submit_label') or '')
        if not submit:
            return True
        detail = 'النموذج: ' + page.url + '\n' + '\n'.join(f"{f.get('label')}: {f.get('value')}" for f in self.params.get('fields') or [])
        if not self.approval('الضغط على «' + submit + '»', detail, page=page):
            self.step('لم أرسل النموذج (بدون موافقة)', False)
            return False
        page.get_by_role('button', name=submit).first.click()
        self.wait(page, 3)
        self.step('أُرسل النموذج بعد موافقتك', page=page)
        return True

    def fasah_list(self, which):
        """Open FASAH (reusing the signed-in window) and show the import/export declaration list."""
        label = 'بيان التصدير' if which == 'export' else 'بيان الاستيراد'
        # Reuse an open FASAH window: closing it can end the FASAH session.
        page = next((p for p in self.context.pages if 'fasah.zatca.gov.sa' in p.url and not p.is_closed()), None)
        if page is None:
            page = self.open(FASAH)
        else:
            page.bring_to_front()
        self.keep.add(page)
        asked = False
        end = time.time() + 10 * 60  # time for you to sign in yourself in this window
        while time.time() < end:
            self.wait(page, 3)
            if '/login' in page.url:
                if not asked:
                    self.step('فسح يطلب تسجيل الدخول: سجّل دخولك بنفسك في نافذة الجهاز (لن أكتب كلمة المرور أو الرمز). أنتظرك 10 دقائق.', False)
                    asked = True
                continue
            if page.get_by_text(label, exact=True).count():
                break
        else:
            raise ValueError('لم يكتمل تسجيل الدخول في فسح خلال 10 دقائق')
        try:
            decline = page.get_by_role('button', name='رفض', exact=True)
            if decline.count() and decline.first.is_visible():
                decline.first.click(timeout=5000)
        except Exception:
            pass
        for attempt in range(10):  # the home page keeps loading for a while after sign-in
            self.poll()
            try:
                if attempt in (3, 6):
                    # Left on a details window or another screen by the previous task: close it and reload FASAH home.
                    for name in ('إغلاق', 'اغلاق'):
                        close = page.get_by_text(name, exact=True)
                        if close.count() and close.first.is_visible():
                            close.first.click(timeout=5000)
                    page.keyboard.press('Escape')
                    page.goto(FASAH, wait_until='domcontentloaded', timeout=60000)
                    self.wait(page, 5)
                link = page.get_by_role('link', name=label, exact=True)
                if not (link.count() and link.first.is_visible()):
                    menu = page.get_by_text('البيان الجمركي و الفسح', exact=True)
                    if menu.count():
                        menu.first.click(timeout=8000)
                        self.wait(page, 2)
                link = page.get_by_role('link', name=label, exact=True)
                if link.count() and link.first.is_visible():
                    link.first.click(timeout=8000)
                    self.wait(page, 5)
                if self.list_rows(page):
                    self.step('فتحت قائمة ' + label, page=page)
                    return page
            except Stop:
                raise
            except Exception:
                pass
            self.wait(page, 4)
        raise ValueError('لم أجد قائمة «' + label + '» في فسح بعد الدخول')

    @staticmethod
    def list_rows(page):
        text = page.locator('main').inner_text()
        rows = []
        for part in re.split(r'\n(?=\d{14}\b)', text):
            m = re.match(r'^(\d{14})\s+(?:(\d{3,8})\s+)?(?:(\d{2}/\d{2}/\d{4})\s+)?(.*)$', ' '.join(part.split()))
            if m:
                details = re.sub(r'\s*(إظهار التفاصيل|تتبع مراحل البيان).*$', '', m.group(4))
                rows.append([m.group(1), m.group(2) or '', m.group(3) or '', details[:300]])
        return rows

    def filter_party(self, page, name, which):
        """FASAH filter panel: importer/exporter name (read-only filtering)."""
        page.get_by_text('تصفية', exact=True).first.click(timeout=8000)
        self.wait(page, 2)
        box = None
        for label in (('اسم المصدّر', 'اسم المصدر') if which == 'export' else ('اسم المستورد',)):
            for loc in (page.get_by_placeholder(label), page.get_by_role('textbox', name=label), page.get_by_label(label)):
                if loc.count():
                    box = loc.first
                    break
            if box is not None:
                break
        if box is None:
            # The export list has no name filter: read the pages and filter by name here instead.
            try:
                page.keyboard.press('Escape')
            except Exception:
                pass
            self.step('لا توجد خانة تصفية بالاسم في هذه القائمة؛ سأقرأ الصفحات وأصفّي بالاسم')
            return False
        box.fill(name)
        page.get_by_role('button', name='تطبيق الاختيارات').first.click(timeout=8000)
        self.wait(page, 5)
        self.step('صفّيت القائمة على: ' + name, page=page)
        return True

    def next_page(self, page, number):
        before = (self.list_rows(page) or [[None]])[0][0]
        target = page.locator('ul.pagination, nav, .pagination').get_by_text(str(number), exact=True)
        if not target.count():
            target = page.get_by_role('button', name=str(number), exact=True)
        if not target.count():
            return False
        target.last.click(timeout=8000)
        for _ in range(10):
            self.wait(page, 1.5)
            rows = self.list_rows(page)
            if rows and rows[0][0] != before:
                return True
        return False

    def collect(self, page, since=None, pages=3):
        rows, seen = [], set()
        for number in range(1, max(1, min(int(pages or 3), 20)) + 1):
            if number > 1 and not self.next_page(page, number):
                break
            fresh = [r for r in self.list_rows(page) if r[0] not in seen]
            seen.update(r[0] for r in fresh)
            rows += fresh
            if since and fresh:
                dates = [time.strptime(r[2], '%d/%m/%Y') for r in fresh if r[2]]
                if dates and min(dates) < time.strptime(since, '%Y-%m-%d'):
                    break
        if since:
            rows = [r for r in rows if not r[2] or time.strptime(r[2], '%d/%m/%Y') >= time.strptime(since, '%Y-%m-%d')]
        return rows

    def do_fasah_declarations(self):
        which = self.params.get('which', 'import')
        page = self.fasah_list(which)
        party = self.params.get('party')
        filtered = self.filter_party(page, party, which) if party else True
        rows = self.collect(page, self.params.get('since'), self.params.get('pages', 3) if filtered else 20)
        if party and not filtered:
            rows = [r for r in rows if party in r[3]]
        path = self.dir / f'fasah-{which}.csv'
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['رقم المرجع', 'رقم البيان', 'التاريخ', 'التفاصيل'])
            w.writerows(rows)
        self.step(f'قرأت {len(rows)} بيان (قراءة فقط)')
        return self.upload(path, page.url)

    DETAIL_SECTIONS = ('معلومات البيان الأساسية', 'الفواتير', 'تفاصيل فاتورة البيان الجمركي',
                       'الفواتير المصدرة على البيان الجمركي من جميع الجهات', 'الأصناف')

    def open_details(self, page, row, number):
        """Click «إظهار التفاصيل» of one row (read-only). Some rows keep it inside the row's actions menu."""
        target = row.get_by_text('إظهار التفاصيل')
        for attempt in range(4):
            try:
                row.scroll_into_view_if_needed(timeout=5000)
                if attempt == 1:  # hidden inside the row menu: open the menu first
                    for toggle in (row.get_by_text('الإجراءات', exact=True), row.locator('[aria-haspopup], .dropdown-toggle, [data-toggle="dropdown"]')):
                        if toggle.count():
                            toggle.first.click(timeout=4000)
                            self.wait(page, 1)
                            break
                if attempt == 3:  # still hidden: fire the same click on the element itself
                    target.first.dispatch_event('click')
                else:
                    target.first.click(timeout=8000)
                self.wait(page, 4)
                if page.get_by_text('تفاصيل الطلب', exact=True).count() or page.get_by_text('ملخص الطلب', exact=True).count():
                    return
            except Stop:
                raise
            except Exception:
                page.keyboard.press('Escape')
                self.wait(page, 2)
        try:
            seen = ' '.join(row.inner_text().split())[:200] + ' | ' + row.inner_html()[:500]
        except Exception:
            seen = ''
        raise ValueError('تعذر فتح تفاصيل البيان ' + number + ': ' + seen)

    def expand_details(self, page):
        """The details screen shows collapsed sections; open the invoice sections so their text can be read (read-only).
        Only these exact section titles are clicked — never «تقديم الطلب», «إلغاء البيان» or «إنشاء نسخة»."""
        before = len(page.locator('body').inner_text())
        scope = page  # stay inside the details window: the site menu may have links with the same words
        for css in ('[role="dialog"]', '.modal-content', '.modal', 'main'):
            box = page.locator(css).filter(has_text='معلومات البيان الأساسية')
            if box.count():
                scope = box.last
                break
        for title in self.DETAIL_SECTIONS:
            try:
                head = scope.get_by_text(title, exact=True)
                if head.count() and head.first.is_visible():
                    head.first.click(timeout=5000)
                    self.wait(page, 2)
            except Stop:
                raise
            except Exception:
                continue
        return len(page.locator('body').inner_text()) - before

    def do_fasah_details(self):
        """Open ONE declaration's details and save its text (read-only), for billing."""
        which, number = self.params.get('which', 'import'), str(self.params.get('number') or '')
        if not re.fullmatch(r'\d{3,8}', number):
            raise ValueError('رقم البيان غير صالح')
        page = self.fasah_list(which)
        if self.params.get('party'):
            self.filter_party(page, self.params['party'], which)
        for p in range(1, 31):
            if p > 1 and not self.next_page(page, p):
                break
            row = page.locator('tr', has_text=number)
            if row.count():
                self.open_details(page, row.last, number)  # .last = the innermost row when tables are nested
                tab = page.get_by_text('تفاصيل الطلب', exact=True)
                if tab.count():
                    tab.first.click(timeout=8000)
                    self.wait(page, 4)
                grown = self.expand_details(page)
                text = page.locator('body').inner_text()
                self.step(f'فتحت تفاصيل البيان {number} وأقسام الفواتير (+{max(grown, 0)} حرف)', page=page)
                close = page.get_by_text('إغلاق', exact=True)
                if close.count():
                    close.first.click(timeout=5000)
                path = self.dir / f'fasah-{number}.txt'
                path.write_text(text, encoding='utf-8')
                return self.upload(path, page.url)
        raise ValueError('لم أجد البيان ' + number + ' في القائمة')


    def find_row(self, page, number, which):
        if self.params.get('party'):
            self.filter_party(page, self.params['party'], which)
        for p in range(1, 31):
            if p > 1 and not self.next_page(page, p):
                break
            row = page.locator('tr', has_text=number)
            if row.count():
                return row.first
        raise ValueError('لم أجد البيان ' + number + ' في القائمة')

    def do_fasah_release_notice(self):
        """Download the customs release notice (إشعار الفسح) PDF of ONE released declaration — read-only."""
        which, number = self.params.get('which', 'import'), str(self.params.get('number') or '')
        if not re.fullmatch(r'\d{3,8}', number):
            raise ValueError('رقم البيان غير صالح')
        page = self.fasah_list(which)
        row = self.find_row(page, number, which)
        labels = re.compile(r'(طباعة إشعار الفسح|إشعار الفسح|اشعار الفسح|طباعة الإشعار|طباعة)')
        target = row.get_by_text(labels)
        if not target.count():
            row.get_by_text('إظهار التفاصيل').first.click(timeout=8000)
            self.wait(page, 4)
            target = page.get_by_role('button', name=labels)
            if not target.count():
                target = page.get_by_text(labels)
        if not target.count():
            self.step('لم أجد زر إشعار الفسح للبيان ' + number, False, page=page)
            raise ValueError('زر إشعار الفسح غير ظاهر (قد لا يكون البيان مفسوحًا بعد)')
        path = self.dir / f'release-{number}.pdf'
        before = set(self.context.pages)
        try:
            with page.expect_download(timeout=45000) as info:
                target.first.click(timeout=8000)
            info.value.save_as(path)
        except Exception:
            # Some screens open the PDF in a new tab instead of downloading it: fetch that URL in the same session.
            pdf_url = None
            for other in self.context.pages:
                if other not in before and allowed(other.url, self.domains, self.loopback):
                    other.wait_for_load_state('domcontentloaded', timeout=30000)
                    pdf_url = other.url
                    break
            if not pdf_url:
                self.step('لم يبدأ تنزيل إشعار الفسح', False, page=page)
                raise ValueError('لم يبدأ تنزيل إشعار الفسح')
            body = self.context.request.get(pdf_url, timeout=60000).body()
            if not body.startswith(b'%PDF'):
                raise ValueError('الصفحة المفتوحة ليست ملف PDF')
            path.write_bytes(body)
        self.step('نزّلت إشعار الفسح للبيان ' + number)
        return self.upload(path, page.url)


def run_one(api, got, context):
    task = Task(api, got['task'], got.get('allowed_domains') or [], context, got.get('allow_http_loopback', False))
    status, result = 'failed', {}
    try:
        status = 'done' if task.run() else 'failed'
    except Stop:
        status, result = 'stopped', {'note': 'أوقفت'}
    except Exception as exc:
        result = {'error': str(exc)[:300]}
        try:
            task.step('توقفت المهمة: ' + str(exc)[:200], False)
        except Exception:
            pass
    try:
        return api.post(f'/api/runner/tasks/{task.id}/finish', {'status': status, 'result': result})['status']
    except requests.HTTPError:
        return status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reset', action='store_true', help='remove the stored device token')
    parser.add_argument('--once', action='store_true', help='run at most one task then exit (testing)')
    parser.add_argument('--headless', action='store_true')
    args = parser.parse_args()
    if args.reset:
        reset_token()
        print('حُذف رمز الجهاز من خزنة ويندوز.')
        return
    api = Api(load_server(), os.getenv('AFAQ_RUNNER_TOKEN_FOR_TESTS') or load_token())
    PROFILE.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    print('جهاز آفاق طويق يعمل. للإيقاف الكامل: Ctrl+C', flush=True)
    with sync_playwright() as pw:
        kwargs = dict(user_data_dir=str(PROFILE), headless=args.headless, accept_downloads=True, locale='ar-SA', chromium_sandbox=True)
        try:
            context = pw.chromium.launch_persistent_context(channel='chrome', **kwargs)
        except Exception:
            context = pw.chromium.launch_persistent_context(**kwargs)
        while True:
            try:
                got = api.post('/api/runner/claim')
            except Exception as exc:
                print('تعذر الاتصال بالنظام:', str(exc)[:120], flush=True)
                time.sleep(30)
                continue
            if got.get('task'):
                print('انتهت المهمة:', run_one(api, got, context), flush=True)
                if args.once:
                    break
            elif args.once:
                break
            else:
                time.sleep(10)
        context.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
