"""Stage 2 (mock level): extraction receives the case context, and a later port change makes the analysis stale."""
from tests.test_fasah_ai_accuracy import WOOD, ai


def test_extraction_gets_case_context_and_binds_fields(monkeypatch):
    payloads = []
    responses = iter([{'items': [{'description': 'wood'}], 'fields': {}, 'issues': [],
                       'coverage': {'all_lines_extracted': True, 'total_invoice_lines': 1}},
                      {'items': [{'index': 0, 'code': WOOD, 'alternatives': []}]}])

    def ask(system, payload, max_tokens=4000):
        payloads.append(payload)
        return next(responses)
    monkeypatch.setattr(ai, 'ask', ask)
    monkeypatch.setattr(ai.tariff_lookup, 'search_many', lambda *a, **k: [{'code': WOOD, 'duty': '5%'}])
    monkeypatch.setattr(ai.tariff_lookup, 'as_prompt', lambda entries: entries)
    case = {'documents': [{'name': 'inv.txt', 'kind': 'invoice', 'pages': [{'page': 1, 'text': 'wood'}]}],
            'context': {'profile': {'transaction': 'commercial_import', 'mode': 'sea', 'goods': 'خشب', 'dispatch_country': 'الصين'}},
            'fields': {'arrival_port': {'value': 'ميناء جدة الإسلامي'}}}
    result = ai.analyze(case)
    assert payloads[0]['case_context'] == {'transaction': 'commercial_import', 'mode': 'sea', 'goods': 'خشب',
                                           'dispatch_country': 'الصين', 'arrival_port_recorded': 'ميناء جدة الإسلامي'}
    assert 'case_context' in ai.EXTRACT and result['fields_fingerprint'] == ai.fields_fingerprint(case)
    assert ai.current_coverage(case, result)['stale_sources'] is False
    case['fields']['arrival_port']['value'] = 'ميناء الملك عبدالعزيز بالدمام'
    assert ai.current_coverage(case, result)['stale_sources'] is True
    assert ai.STALE_SOURCE_WARNING in ai.chrome_prompt(case, result)


def test_no_context_keeps_previous_payload(monkeypatch):
    payloads = []
    monkeypatch.setattr(ai, 'ask', lambda s, p, max_tokens=4000: payloads.append(p) or {'items': [], 'fields': {}, 'issues': [], 'coverage': {}})
    ai.analyze({'documents': [{'name': 'x', 'kind': 'invoice', 'pages': [{'page': 1, 'text': 'x'}]}]})
    assert set(payloads[0]) == {'documents'}
