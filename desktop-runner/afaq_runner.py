"""Afaq Tuwaiq work-computer runner.

Runs on a dedicated work computer. Opens its OWN Chrome window (separate profile) where you sign in to FASAH
yourself; this program never types passwords or OTP codes and never stores them. It asks the Afaq system for
approved tasks, executes them (read-only for now), reports every step with screenshots, verifies downloaded files
and uploads them. Stop any task from WhatsApp («أوقف المهمة N») or the /agent-runner page.

First run: python afaq_runner.py  -> asks for the system address and the device token (from /agent-runner).
"""
import base64
import csv
import hashlib
import io
import json
import os
import pathlib
import re
import sys
import time
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright

HOME = pathlib.Path(os.getenv('APPDATA') or pathlib.Path.home() / '.config') / 'AfaqRunner'
CONFIG = HOME / 'config.json'
PROFILE = pathlib.Path(os.getenv('LOCALAPPDATA') or pathlib.Path.home() / '.local' / 'share') / 'AfaqRunner' / 'chrome-profile'
DOWNLOADS = pathlib.Path.home() / 'Documents' / 'AfaqRunner'
FASAH = 'https://fasah.zatca.gov.sa/ar/broker/2.0/'


class Stop(Exception):
    pass


def config():
    if CONFIG.exists():
        return json.loads(CONFIG.read_text(encoding='utf-8'))
    HOME.mkdir(parents=True, exist_ok=True)
    server = input('رابط نظام آفاق طويق [https://gulf-logistics-ai-v7-production.up.railway.app]: ').strip() or \
        'https://gulf-logistics-ai-v7-production.up.railway.app'
    token = input('رمز الجهاز من صفحة /agent-runner: ').strip()
    data = {'server': server.rstrip('/'), 'token': token}
    CONFIG.write_text(json.dumps(data), encoding='utf-8')
    return data


class Api:
    def __init__(self, cfg):
        self.base, self.headers = cfg['server'], {'X-Runner-Token': cfg['token']}

    def post(self, path, payload=None):
        r = requests.post(self.base + path, json=payload or {}, headers=self.headers, timeout=60)
        r.raise_for_status()
        return r.json()


def allowed(url, domains):
    host = (urlparse(url).hostname or '').lower()
    return urlparse(url).scheme == 'https' and any(host == d or host.endswith('.' + d) for d in domains)


def verify(path):
    """True only if the saved file exists, is non-empty and opens as its type."""
    data = pathlib.Path(path).read_bytes()
    if not data:
        return False
    name = str(path).lower()
    if name.endswith('.pdf'):
        return data.startswith(b'%PDF') and b'%%EOF' in data[-2048:]
    if name.endswith(('.xlsx', '.docx', '.zip')):
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                return z.testzip() is None
        except zipfile.BadZipFile:
            return False
    if name.endswith('.csv'):
        return len(list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))) > 1
    return True


class Task:
    def __init__(self, api, task, domains, context):
        self.api, self.id, self.kind, self.params, self.domains, self.context = api, task['id'], task['kind'], task['params'], domains, context
        self.dir = DOWNLOADS / f"task-{self.id}"
        self.dir.mkdir(parents=True, exist_ok=True)

    def step(self, text, ok=True, page=None):
        shot = None
        if page is not None:
            try:
                shot = base64.b64encode(page.screenshot(full_page=False)).decode()
            except Exception:
                shot = None
        print(('✓ ' if ok else '✗ ') + text, flush=True)
        if self.api.post(f'/api/runner/tasks/{self.id}/step', {'text': text, 'ok': ok, 'screenshot_b64': shot}).get('stop'):
            raise Stop()

    def upload(self, path, mime):
        data = pathlib.Path(path).read_bytes()
        ok = verify(path)
        self.api.post(f'/api/runner/tasks/{self.id}/file', {'name': pathlib.Path(path).name, 'mime': mime, 'verified': ok,
                                                           'sha256': hashlib.sha256(data).hexdigest(),
                                                           'data_b64': base64.b64encode(data).decode()})
        self.step(f'رُفع الملف {pathlib.Path(path).name} ({len(data):,} بايت) — ' + ('تم التحقق أنه يفتح' if ok else 'فشل التحقق'), ok)
        return ok

    def page(self, url):
        if not allowed(url, self.domains):
            raise ValueError('موقع غير مسموح: ' + url)
        p = self.context.new_page()
        p.goto(url, wait_until='domcontentloaded', timeout=60000)
        if not allowed(p.url, self.domains):
            raise ValueError('حولني الموقع إلى عنوان غير مسموح؛ أوقفت.')
        return p

    def run(self):
        return getattr(self, 'do_' + self.kind)()

    def do_download_test(self):
        url = self.api.base + '/agent-runner/test-file.pdf'
        self.step('بدأت التجربة: تنزيل ملف تجريبي من النظام')
        r = self.context.request.get(url, timeout=60000)
        path = self.dir / 'afaq-runner-test.pdf'
        path.write_bytes(r.body())
        self.step(f'حُفظ الملف في {path}')
        return self.upload(path, 'application/pdf')

    def do_download_file(self):
        url = self.params['url']
        if not allowed(url, self.domains):
            raise ValueError('موقع غير مسموح')
        r = self.context.request.get(url, timeout=120000)
        name = re.sub(r'[^\w.\-]', '_', pathlib.Path(urlparse(url).path).name or 'download')
        path = self.dir / name
        path.write_bytes(r.body())
        self.step(f'نزل الملف ({len(r.body()):,} بايت) إلى {path}')
        return self.upload(path, r.headers.get('content-type', 'application/octet-stream').split(';')[0])

    def do_read_page(self):
        p = self.page(self.params['url'])
        p.wait_for_timeout(4000)
        text = p.inner_text('body')
        self.step('فتحت الصفحة: ' + (p.title() or p.url), page=p)
        path = self.dir / 'page.txt'
        path.write_text(text, encoding='utf-8')
        return self.upload(path, 'text/plain')

    def do_fasah_declarations(self):
        which = self.params.get('which', 'import')
        p = self.page(FASAH)
        self.step('فتحت فسح', page=p)
        for _ in range(60):  # up to 5 minutes for you to sign in yourself in this window
            if '/login' not in p.url:
                break
            if _ == 0:
                self.step('فسح يطلب تسجيل الدخول: سجّل دخولك بنفسك في نافذة الجهاز (لن أكتب كلمة المرور أو الرمز)', False, page=p)
            time.sleep(5)
            if self.api.post(f'/api/runner/tasks/{self.id}/step', {'text': 'بانتظار تسجيل الدخول…', 'ok': True}).get('stop'):
                raise Stop()
        if '/login' in p.url:
            raise ValueError('لم يتم تسجيل الدخول خلال 5 دقائق')
        p.wait_for_timeout(5000)
        label = 'بيان التصدير' if which == 'export' else 'بيان الاستيراد'
        p.get_by_text(label, exact=True).first.click()
        p.wait_for_timeout(6000)
        self.step('فتحت قائمة ' + label, page=p)
        text = p.locator('main').inner_text()
        rows = []
        for line in text.splitlines():
            m = re.match(r'^(\d{14})\s+(\d{3,8})?\s*(\d{2}/\d{2}/\d{4})?\s*(.*)$', line.strip())
            if m:
                rows.append([m.group(1), m.group(2) or '', m.group(3) or '', m.group(4)])
        if not rows:  # the table renders cells on separate lines: fall back to grouping by reference numbers
            parts = re.split(r'\n(?=\d{14}\b)', text)
            rows = [[x.split()[0], '', '', ' '.join(x.split()[1:])[:300]] for x in parts if re.match(r'^\d{14}\b', x.strip())]
        path = self.dir / f'fasah-{which}.csv'
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['رقم المرجع', 'رقم البيان', 'التاريخ', 'التفاصيل'])
            w.writerows(rows)
        self.step(f'قرأت {len(rows)} بيان (قراءة فقط، لم أغير شيئًا)')
        return self.upload(path, 'text/csv')


def main():
    cfg = config()
    api = Api(cfg)
    PROFILE.mkdir(parents=True, exist_ok=True)
    print('جهاز آفاق طويق يعمل. للإيقاف: Ctrl+C', flush=True)
    with sync_playwright() as pw:
        kwargs = dict(user_data_dir=str(PROFILE), headless=False, accept_downloads=True, locale='ar-SA')
        try:
            context = pw.chromium.launch_persistent_context(channel='chrome', **kwargs)
        except Exception:
            context = pw.chromium.launch_persistent_context(**kwargs)
        while True:
            try:
                got = api.post('/api/runner/claim')
            except Exception as exc:
                print('تعذر الاتصال بالنظام:', exc, flush=True)
                time.sleep(30)
                continue
            if not got.get('task'):
                time.sleep(10)
                continue
            task = Task(api, got['task'], got.get('allowed_domains') or [], context)
            status, result = 'failed', {}
            try:
                ok = task.run()
                status = 'done' if ok else 'failed'
            except Stop:
                status, result = 'stopped', {'note': 'أوقفت بطلبك'}
            except Exception as exc:
                result = {'error': str(exc)[:300]}
                try:
                    task.step('توقفت المهمة: ' + str(exc)[:200], False)
                except Exception:
                    pass
            api.post(f'/api/runner/tasks/{task.id}/finish', {'status': status, 'result': result})


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
