"""«لا أحد ينتظر»: promise times, irritation words and the provider answer check — pure, no database."""
import asyncio
import datetime as dt
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock, patch

_storage = types.ModuleType('app.storage')
_storage.db = Mock(side_effect=AssertionError('database touched'))
_storage.utcnow = Mock(side_effect=AssertionError('clock touched'))
_spec = importlib.util.spec_from_file_location('_no_wait', Path(__file__).resolve().parents[1] / 'app' / 'no_wait.py')
no_wait = importlib.util.module_from_spec(_spec)
with patch.dict(sys.modules, {'app.storage': _storage}):
    _spec.loader.exec_module(no_wait)

T = dt.datetime(2026, 11, 18, 7, 0, tzinfo=dt.timezone.utc)  # 10:00 Riyadh


def test_promise_times():
    due = no_wait.promise_due
    assert due('أرجع لك خلال نص ساعة', T) == T + dt.timedelta(minutes=30)
    assert due('بنرد عليك بعد ساعتين إن شاء الله', T) == T + dt.timedelta(hours=2)
    assert due('سنتواصل معكم خلال 3 ساعات', T) == T + dt.timedelta(hours=3)
    assert due('بنرسل لك الفاتورة اليوم', T).astimezone(no_wait.RIYADH).hour == 17
    assert due('ابشر، أبلغك أول ما يطلع الفسح', T) == T + dt.timedelta(hours=2)
    assert due('We will send you the quote within 45 minutes', T) == T + dt.timedelta(minutes=45)
    for text in ('الرسوم الجمركية 449 ريال', 'تم استلام المستندات، شكرا', 'هل لديكم شحنات قادمة؟'):
        assert due(text, T) is None, text


def test_upset_words():
    assert no_wait.upset_reasons('أسوأ تعامل، رجعوا فلوسي')[0] == 'strong'
    level, reasons = no_wait.upset_reasons('تأخرتم مرة، وين الرد؟؟؟')
    assert level is None and len(reasons) >= 2
    for text in ('السلام عليكم، كم سعر النقل من جدة للرياض؟', 'شكرا جزيلا ما قصرتوا', 'متى تصل الشحنة'):
        assert no_wait.upset_reasons(text) == (None, []), text


def _messages(*items):
    async def read(c, path, params=None):
        return {'messages': [{'direction': d, 'message': m, 'createdAt': a.isoformat()} for d, m, a in items]}
    return read


class _Client:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _check(read, agent=(), skip=()):
    fake = types.ModuleType('app.zernio_whatsapp')
    fake.client, fake.read = (lambda: _Client()), read
    app_pkg = sys.modules.get('app') or types.ModuleType('app')
    with patch.dict(sys.modules, {'app.zernio_whatsapp': fake, 'app': app_pkg}), patch.object(app_pkg, 'zernio_whatsapp', fake, create=True):
        return asyncio.run(no_wait.answered_after('acc', 'conv', T, agent, skip))


def test_answered_only_by_a_person():
    later = T + dt.timedelta(minutes=5)
    # Only the agent's automatic reply and the customer's messages after the promise → not answered.
    assert _check(_messages(('incoming', 'وين السعر', later), ('outgoing', 'نعتذر، أرجع لك قريبًا', later)),
                  agent=['نعتذر، أرجع لك قريبًا']) is False
    # An employee wrote something else after it → answered.
    assert _check(_messages(('outgoing', 'السعر 1,850 ريال', later))) is True
    # Older messages before the promise do not count.
    assert _check(_messages(('outgoing', 'رسالة قديمة', T - dt.timedelta(minutes=5)))) is False

    async def broken(c, path, params=None):
        raise RuntimeError('provider down')
    assert _check(broken) is None
