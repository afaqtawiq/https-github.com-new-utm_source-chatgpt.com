"""Synthetic coverage and item isolation tests. No network/model/database calls."""
import copy
import pytest
import datetime
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import app

# Load privately and restore package attributes so test collection cannot alter
# the real workspace hooks or storage used by other test modules.
workspace = SimpleNamespace(token=lambda _: '', render=lambda title, body: body)
view = SimpleNamespace(document_panel=lambda *args: '')
storage = SimpleNamespace(utcnow=lambda: datetime.datetime.now(datetime.timezone.utc), rows=lambda *a: [])
with patch.dict(app.__dict__, fasah_workspace=workspace, fasah_workspace_view=view), patch.dict(
        sys.modules, {'app.fasah_workspace': workspace, 'app.fasah_workspace_view': view, 'app.storage': storage}):
    spec = importlib.util.spec_from_file_location('_fasah_ai_accuracy_test', Path(__file__).parents[1] / 'app/fasah_ai.py')
    ai = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ai)

WOOD = '440711000000'
TYRE = '401110000000'


def case(text='synthetic invoice'):
    return {'documents': [{'name': 'synthetic.txt', 'kind': 'invoice', 'pages': [{'page': 1, 'text': text}]}]}


def run(monkeypatch, choices=None, items=None, coverage=None, source=None, tariff_records=None):
    items = items if items is not None else [{'description': 'wood'}, {'description': 'tyre'}]
    extracted = {'items': items, 'fields': {}, 'issues': [],
                 'coverage': coverage if coverage is not None else {'all_lines_extracted': True, 'total_invoice_lines': len(items)}}
    responses = iter([extracted, {'items': choices if choices is not None else [
        {'index': n, 'code': WOOD if n == 0 else TYRE, 'alternatives': []} for n in range(len(items))]}])
    monkeypatch.setattr(ai, 'ask', lambda *a, **k: next(responses))
    records = iter(tariff_records if tariff_records is not None else [[{'code': WOOD, 'duty': '5%'}], [{'code': TYRE, 'duty': '15%'}]] * 20)
    monkeypatch.setattr(ai.tariff_lookup, 'search_many', lambda *a, **k: next(records))
    monkeypatch.setattr(ai.tariff_lookup, 'as_prompt', lambda entries: entries)
    return ai.analyze(source or case())


def test_other_items_codes_rates_and_alternatives_rejected(monkeypatch):
    result = run(monkeypatch, [{'index': 0, 'code': TYRE, 'alternatives': [TYRE, WOOD, None, 123]},
                               {'index': 1, 'code': WOOD, 'alternatives': [WOOD, TYRE]}])
    a, b = result['items']
    assert not a['code'] and not a['duty'] and not b['code'] and not b['duty']
    assert a['alternatives'] == [ai.tariff_lookup.format_code(WOOD)]
    assert b['alternatives'] == [ai.tariff_lookup.format_code(TYRE)]
    assert result['coverage']['partial_or_unverified']


def test_matching_items_use_database_rates_and_keep_controls(monkeypatch):
    result = run(monkeypatch)
    assert [i['duty'] for i in result['items']] == ['5%', '15%']
    assert result['coverage']['partial_or_unverified'] is False
    assert result['coverage']['whole_invoice_review_verified'] is False
    prompt = ai.chrome_prompt(case(), result)
    assert 'لا تضغط أي زر إرسال' in prompt and ai.MODEL_COVERAGE_WARNING in prompt


@pytest.mark.parametrize('bad_index', [True, False, '0', 0.0, -1, 2, None, [], {}])
def test_malformed_indices_never_bind(monkeypatch, bad_index):
    result = run(monkeypatch, [{'index': bad_index, 'code': WOOD}])
    assert all(not i['code'] for i in result['items'])
    assert result['coverage']['partial_or_unverified']


def test_duplicate_indices_invalidate_all_occurrences(monkeypatch):
    result = run(monkeypatch, [{'index': 0, 'code': WOOD}] * 3 + [{'index': 1, 'code': TYRE}])
    assert result['items'][0]['code'] == ''
    assert result['items'][1]['duty'] == '15%'


def test_invalid_extracted_line_does_not_reindex_next_line(monkeypatch):
    result = run(monkeypatch, [{'index': 1, 'code': WOOD}], items=[None, {'description': 'wood'}])
    assert result['items'][0]['source_index'] == 1
    assert result['items'][0]['duty'] == '5%'
    assert result['coverage']['processed_line_count'] == 1
    assert result['coverage']['partial_or_unverified']


def test_text_limit_rejects_before_model_without_mutating_source(monkeypatch):
    source = case('x' * 60000)
    source['documents'].append({'name': 'extra', 'pages': ['x']})
    original = copy.deepcopy(source)
    monkeypatch.setattr(ai, 'ask', lambda *a, **k: pytest.fail('model called'))
    with pytest.raises(ValueError, match='60000'):
        ai.analyze(source)
    assert source == original
    assert len(ai.document_text(case('x' * 60000))[0]['text']) == 60000


def test_more_than_30_lines_rejected(monkeypatch):
    with pytest.raises(ValueError, match='30'):
        run(monkeypatch, items=[{'description': 'wood'}] * 31)


def test_exact_limit_is_not_assumed_complete(monkeypatch):
    result = run(monkeypatch, items=[{'description': 'wood'}] * 30)
    assert result['coverage']['partial_or_unverified']
    assert 'لا تدخل' in ai.chrome_prompt(case(), result)


@pytest.mark.parametrize('coverage', [{}, {'all_lines_extracted': False, 'total_invoice_lines': 2},
    {'all_lines_extracted': True, 'total_invoice_lines': 3},
    {'all_lines_extracted': True, 'total_invoice_lines': '2'}])
def test_missing_partial_or_mismatched_coverage_blocks(monkeypatch, coverage):
    result = run(monkeypatch, coverage=coverage)
    assert result['coverage']['partial_or_unverified']
    assert 'لا تدخل' in ai.chrome_prompt(case(), result)


def test_blank_page_and_document_notes_block(monkeypatch):
    source = case()
    source['documents'][0]['pages'].append({'page': 2, 'text': ''})
    source['documents'][0]['notes'] = ['Unreadable text']
    result = run(monkeypatch, source=source)
    assert result['coverage']['available_page_count'] == 2
    assert result['coverage']['partial_or_unverified']


def test_missing_classification_and_legacy_result_block(monkeypatch):
    result = run(monkeypatch, choices=[])
    assert result['coverage']['partial_or_unverified']
    assert 'لا تدخل' in ai.chrome_prompt(case(), {})


def test_ask_rejects_truncated_json_even_when_parseable(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-test-not-a-secret')
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'stop_reason': 'max_tokens', 'content': [{'type': 'text', 'text': '{"items": []}'}]}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, *args, **kwargs): return Response()
    monkeypatch.setattr(ai.httpx, 'Client', Client)
    with pytest.raises(ValueError, match='لم يكتمل'):
        ai.ask('synthetic', {})


def test_ui_warns_and_blocks_legacy_results(monkeypatch):
    source = case()
    source.update(id=1, revision=1, title='synthetic', context={'ai': {'items': [], 'fields': {}}})
    monkeypatch.setattr(ai.ws, 'token', lambda session: '')
    monkeypatch.setattr(ai.ws, 'render', lambda title, body: body)
    page = ai.page(source, {})
    assert '60,000' in page and ai.MODEL_LIMIT_WARNING in page
    assert 'لا تدخل' in page
    assert 'id="launchFasah" disabled' in page


def test_no_invoice_lines_is_not_complete(monkeypatch):
    result = run(monkeypatch, items=[])
    assert result['coverage']['partial_or_unverified']


def test_embedded_code_is_not_a_valid_candidate(monkeypatch):
    result = run(monkeypatch, [{'index': 0, 'code': 'invented ' + WOOD, 'alternatives': ['invented ' + WOOD]}])
    assert result['items'][0]['code'] == ''
    assert result['items'][0]['alternatives'] == []


@pytest.mark.parametrize('code', [None, '', ' ', False, 0])
@pytest.mark.parametrize('has_candidates', [False, True])
def test_unresolved_classification_blocks_even_with_complete_extraction(monkeypatch, code, has_candidates):
    result = run(monkeypatch, choices=[{'index': 0, 'code': code}],
                 items=[{'description': 'wood'}],
                 tariff_records=[[{'code': WOOD, 'duty': '5%'}]] if has_candidates else [[]])
    assert result['items'][0]['code'] == ''
    assert result['coverage']['partial_or_unverified']
    assert any('غير محسوم' in blocker for blocker in result['coverage']['blockers'])
    assert 'لا تدخل' in ai.chrome_prompt(case(), result)


@pytest.mark.parametrize('change', ['text', 'page', 'sha256', 'fingerprint', 'name', 'kind', 'notes', 'add', 'remove'])
def test_changed_source_invalidates_saved_analysis_and_blocks_ui(monkeypatch, change):
    source = case()
    result = run(monkeypatch, source=source)
    saved = copy.deepcopy(result)
    assert not ai.current_coverage(source, result)['partial_or_unverified']
    doc = source['documents'][0]
    if change == 'text':
        doc['pages'][0]['text'] = 'changed invoice'
    elif change == 'page':
        doc['pages'].append({'page': 2, 'text': 'another line'})
    elif change == 'add':
        source['documents'].append({'name': 'second.txt', 'pages': ['extra evidence']})
    elif change == 'remove':
        source['documents'].clear()
    else:
        doc[change] = ['new note'] if change == 'notes' else 'changed'
    assert ai.current_coverage(source, result)['stale_sources']
    assert ai.STALE_SOURCE_WARNING in ai.chrome_prompt(source, result)
    assert 'لا تدخل' in ai.chrome_prompt(source, result)
    source.update(id=1, revision=2, title='synthetic', context={'ai': result})
    html = ai.page(source, {})
    assert ai.STALE_SOURCE_WARNING in html
    assert 'id="launchFasah" disabled' in html
    assert result == saved  # Rendering must not mutate persisted coverage.


def test_unchanged_sources_survive_case_revision_and_json_roundtrip(monkeypatch):
    import json
    source = case()
    result = run(monkeypatch, source=source)
    source = json.loads(json.dumps(source))
    source.update(revision=99, context={'unrelated': True})
    assert not ai.current_coverage(source, result)['stale_sources']
    assert 'املأ الحقول' in ai.chrome_prompt(source, result)
    assert result['coverage']['whole_invoice_review_verified'] is False


def test_legacy_complete_coverage_without_fingerprint_is_blocked(monkeypatch):
    result = run(monkeypatch)
    result.pop('source_fingerprint')
    assert ai.current_coverage(case(), result)['partial_or_unverified']
    assert ai.STALE_SOURCE_WARNING in ai.chrome_prompt(case(), result)


@pytest.mark.parametrize('state', ['current', 'current_partial', 'stale', 'unbound'])
def test_copy_buttons_disabled_only_for_stale_or_unbound_sources(monkeypatch, state):
    from html.parser import HTMLParser
    source = case()
    result = run(monkeypatch, source=source)
    result['fields'] = {'invoice_number': {'value': 'SYNTHETIC-1', 'source': 'synthetic.txt'}}
    if state == 'stale':
        source['documents'][0]['pages'][0]['text'] = 'changed'
    elif state == 'unbound':
        result.pop('source_fingerprint')
    elif state == 'current_partial':
        result['coverage']['partial_or_unverified'] = True
    source.update(id=1, revision=2, title='synthetic', context={'ai': result})
    class Buttons(HTMLParser):
        def __init__(self):
            super().__init__()
            self.copies = []
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'button' and 'copy' in attrs.get('class', '').split():
                self.copies.append(attrs)
    parser = Buttons()
    parser.feed(ai.page(source, {}))
    assert len(parser.copies) == 3  # One header field and two classified items.
    assert all(('disabled' in button) == (state in ('stale', 'unbound')) for button in parser.copies)
