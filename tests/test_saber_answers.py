"""Synthetic public vocabulary and official evidence, no database or network."""
import asyncio
import copy
import sys
import types

import pytest
from app import saber_answers as a

ROW = dict(code='401110100000', description='إطارات سيارات جديدة', regulation='لائحة الإطارات',
           certificates='شهادة علامة الجودة أو بطاقة كفاءة الطاقة', additional_requirements='باستثناء الفئات المذكورة')


def evidence(**changes):
    result = dict(status='results', query='إطارات', query_kind='product', results=[copy.deepcopy(ROW)],
                  source_url=a.SOURCE_URL + '?Tags=tires', retrieved_at='2026-11-08T00:00:00+00:00', truncated=False)
    result.update(changes)
    return result


@pytest.fixture
def gate(monkeypatch):
    import app
    entries = [dict(code='401110100000', desc_ar='إطارات سيارات جديدة', desc_en='new car tires', context_ar='منتجات المطاط')]
    module = types.ModuleType('app.tariff_lookup')
    module.search_many = lambda *args, **kwargs: entries
    monkeypatch.setitem(sys.modules, 'app.tariff_lookup', module)
    monkeypatch.setattr(app, 'tariff_lookup', module, raising=False)
    calls = []
    async def lookup(query):
        calls.append(query)
        return evidence(query=query)
    monkeypatch.setattr(a, 'lookup_saber', lookup)
    return entries, calls


@pytest.mark.parametrize('query, public', [('اطارات سيارات', 'إطارات سيارات'), ('car tires', 'car tires'),
                                         ('401110100000', '401110100000'), ('منتجات المطاط', 'منتجات المطاط')])
def test_exact_public_phrase_is_reconstructed(gate, query, public):
    _, calls = gate
    assert asyncio.run(a.search_product(query))['status'] == 'results'
    assert calls == [public]


@pytest.mark.parametrize('query', ['إطارات العميل محمد', 'John Smith', 'محمد احمد', '121234567890',
                                  '401110100001', 'car new', 'tire', '', 'new car tires secret'])
def test_unknown_names_identifiers_and_fuzzy_matches_never_leave(gate, query):
    _, calls = gate
    assert asyncio.run(a.search_product(query))['status'] == 'unavailable'
    assert calls == []


def test_missing_local_table_fails_closed(gate):
    entries, calls = gate
    entries.clear()
    assert asyncio.run(a.search_product('إطارات'))['reason'] == 'query_not_in_public_vocabulary'
    assert not calls


def test_local_exception_and_busy_fail_closed(gate, monkeypatch):
    _, calls = gate
    def broken(query):
        raise RuntimeError('synthetic local failure')
    monkeypatch.setattr(a, '_public_query', broken)
    assert asyncio.run(a.search_product('إطارات'))['reason'] == 'local_vocabulary_unavailable'
    import threading
    monkeypatch.setattr(a, '_SLOTS', threading.BoundedSemaphore(0))
    assert asyncio.run(a.search_product('إطارات'))['reason'] == 'local_vocabulary_busy'
    assert not calls


def test_renderer_preserves_alternatives_additional_requirements_source_time():
    result = a.render_answer(evidence(), 'العميل فلان يريد اطارات')
    for value in [ROW['certificates'], ROW['additional_requirements'], ROW['description'], a.SOURCE_URL, '2026-11-08']:
        assert value in result
    assert 'فلان' not in result and 'فئات مرشحة' in result and 'خطوة منفصلة' in result
    assert len(result) <= 1400


def test_exact_code_requires_matching_row():
    e = evidence(query_kind='hs_exact', query=ROW['code'])
    assert 'البند المبحوث' in a.render_answer(e)
    e['query'] = '252520000000'
    assert 'تحتاج مراجعة' in a.render_answer(e)


def test_question_orders_candidates_without_assigning_code():
    mica = dict(ROW, code='252520000000', description='مسحوق ميكا', certificates='إقرار ذاتي')
    result = a.render_answer(evidence(results=[ROW, mica]), 'هل مسحوق ميكا يحتاج سابر؟')
    assert result.index('252520000000') < result.index('401110100000')
    assert 'ليست تصنيفًا نهائيًا' in result


def test_oversize_does_not_truncate_exceptions():
    row = dict(ROW, additional_requirements='شرط واستثناء كامل ' * 200)
    result = a.render_answer(evidence(results=[row]))
    assert len(result) <= 1400 and 'تحتاج مراجعة' in result
    assert ROW['certificates'] not in result


def test_no_invented_requirement_from_failed_evidence_or_external_links():
    assert 'لا أؤكد' in a.render_answer(evidence(status='unavailable', results=[]))
    result = a.render_answer(evidence(source_url='https://evil.invalid/private'), 'https://evil.invalid/question')
    assert 'evil.invalid' not in result and a.SOURCE_URL in result
    row = dict(ROW, certificates='راجع https://evil.invalid')
    assert 'evil.invalid' not in a.render_answer(evidence(results=[row]))


def test_empty_additional_requirements_not_invented():
    result = a.render_answer(evidence(results=[dict(ROW, additional_requirements='')]))
    assert 'متطلبات إضافية:' not in result
