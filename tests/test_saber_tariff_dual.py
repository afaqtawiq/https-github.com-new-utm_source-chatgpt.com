"""Stage 4: mixed SABER + customs-duty questions get BOTH lookups, each with its source and date (MOCK level:
the model and SABER site are simulated, the tariff table is monkeypatched; no network)."""
import asyncio
import datetime as dt

import pytest

from app import whatsapp_natural as natural
from tests.test_customs_first import install_model

@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://unit-test-only.invalid/no-network')


SABER_ROW = {'code': '940130000000', 'description': 'كراسي دوارة قابلة لتعديل الارتفاع', 'regulation': 'اللائحة الفنية للأثاث',
             'certificates': 'شهادة مطابقة المنتج (PCoC) ثم شهادة الإرسالية (SCoC)', 'additional_requirements': ''}
TARIFF_ROW = {'code': '940130000000', 'desc_ar': 'مقاعد دوارة قابلة لتعديل الارتفاع', 'duty': '5%', 'context_ar': 'مقاعد'}


def saber_ok(monkeypatch):
    async def fake(args):
        return {'status': 'results', 'query': args.get('query'), 'query_kind': 'keyword', 'results': [SABER_ROW],
                'source_url': 'https://saber.sa/Home/HSCodes?Tags=chair'}
    monkeypatch.setattr(natural, 'saber_result', fake)


def test_section_uses_exact_saber_code_first(monkeypatch):
    from app import tariff_lookup
    monkeypatch.setattr(tariff_lookup, 'search', lambda q, limit=1: [TARIFF_ROW] if q == '940130000000' else [])
    monkeypatch.setattr(tariff_lookup, 'search_many', lambda *a, **k: (_ for _ in ()).throw(AssertionError('not needed')))
    text = natural.dual_tariff_section(['940130000000'], 'كرسي', today=dt.date(2026, 11, 9))
    assert '94 01 30 00 00 00' in text and 'الرسم: 5%' in text and 'نفس بند سابر' in text
    assert '30 سبتمبر 2026' in text and 'تاريخ الاستعلام: 2026-11-09' in text and 'زاتكا' in text


def test_section_falls_back_to_description_then_fails_closed(monkeypatch):
    from app import tariff_lookup
    monkeypatch.setattr(tariff_lookup, 'search', lambda q, limit=1: [])
    monkeypatch.setattr(tariff_lookup, 'search_many', lambda ar, en, limit=3: [TARIFF_ROW])
    assert 'مرشح بالوصف' in natural.dual_tariff_section([], 'كرسي مكتب')
    monkeypatch.setattr(tariff_lookup, 'search_many', lambda ar, en, limit=3: [])
    assert natural.dual_tariff_section([], 'كرسي مكتب') == ''
    def broken(*a, **k):
        raise RuntimeError('table unavailable')
    monkeypatch.setattr(tariff_lookup, 'search_many', broken)
    assert natural.dual_tariff_section([], 'كرسي مكتب') == ''
    # A row without a duty is never rendered as a rate.
    monkeypatch.setattr(tariff_lookup, 'search_many', lambda ar, en, limit=3: [dict(TARIFF_ROW, duty='')])
    assert natural.dual_tariff_section([], 'كرسي مكتب') == ''


def test_mixed_question_answers_both_with_sources(monkeypatch):
    install_model(monkeypatch, [{'type': 'tool_use', 'id': 's1', 'name': 'saber_search', 'input': {'query': 'كرسي مكتب'}}])
    saber_ok(monkeypatch)
    from app import tariff_lookup
    monkeypatch.setattr(tariff_lookup, 'search', lambda q, limit=1: [TARIFF_ROW] if q == '940130000000' else [])
    answer = asyncio.run(natural.reply('هل الكراسي المكتبية عليها سابر وكم الرسوم الجمركية عليها؟'))
    assert 'PCoC' in answer and 'saber.sa' in answer, answer
    assert 'الرسم: 5%' in answer and 'تاريخ الاستعلام' in answer and 'جدول التعرفة الخليجي' in answer
    assert 'لم أتحقق هنا من تعرفة' not in answer


def test_mixed_question_tariff_down_keeps_explicit_deferral(monkeypatch):
    install_model(monkeypatch, [{'type': 'tool_use', 'id': 's1', 'name': 'saber_search', 'input': {'query': 'كرسي مكتب'}}])
    saber_ok(monkeypatch)
    from app import tariff_lookup
    monkeypatch.setattr(tariff_lookup, 'search', lambda q, limit=1: [])
    monkeypatch.setattr(tariff_lookup, 'search_many', lambda *a, **k: [])
    answer = asyncio.run(natural.reply('هل الكراسي المكتبية عليها سابر وكم الرسوم الجمركية عليها؟'))
    assert 'PCoC' in answer and 'لم أتحقق هنا من تعرفة هذه البضاعة' in answer and 'الرسم:' not in answer


def test_saber_down_never_asserts_and_tariff_not_invented(monkeypatch):
    install_model(monkeypatch, [{'type': 'tool_use', 'id': 's1', 'name': 'saber_search', 'input': {'query': 'كرسي مكتب'}}])
    async def down(args):
        return {'status': 'error', 'results': []}
    monkeypatch.setattr(natural, 'saber_result', down)
    from app import tariff_lookup
    monkeypatch.setattr(tariff_lookup, 'search', lambda q, limit=1: [])
    monkeypatch.setattr(tariff_lookup, 'search_many', lambda *a, **k: [TARIFF_ROW])
    answer = asyncio.run(natural.reply('هل الكراسي المكتبية عليها سابر وكم الرسوم الجمركية عليها؟'))
    assert answer.startswith(natural.SABER_UNVERIFIED_REPLY)
    # SABER failed → no certificate claim; the tariff part is still a separate dated candidate lookup.
    assert 'PCoC' not in answer and 'مرشح بالوصف' in answer and 'تاريخ الاستعلام' in answer
