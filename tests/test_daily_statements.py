import sys
import types


def test_run_sends_pdfs_and_reports_failures(monkeypatch):
    from app import daily_statements as d
    si = types.SimpleNamespace(all_statements=lambda months: 'نص الكشوفات',
                               statement=lambda p, m: {'party': p, 'lines': [1] if p != 'C' else []})
    br = types.SimpleNamespace(YASMEN='A', OMRAN='B', SALLA='C')
    sp = types.SimpleNamespace(send_to_requester=lambda chat, ss: (['A'], ['B']))
    vo = types.SimpleNamespace(owner_chat=lambda: ('966500000000', 'conv1'))
    for name, mod in (('statement_import', si), ('billing_rules', br), ('statement_pdf', sp), ('virtual_office', vo)):
        monkeypatch.setitem(sys.modules, 'app.' + name, mod)
        import app
        monkeypatch.setattr(app, name, mod, raising=False)
    text = d.run()
    assert 'كشف A' in text and 'تعذر إرسال PDF لـB' in text and 'نص الكشوفات' in text
    vo.owner_chat = lambda: None
    text = d.run()
    assert 'تعذر إرسال PDF لـA، B' in text
