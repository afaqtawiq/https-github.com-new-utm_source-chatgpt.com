"""SABER questions with a file / to a department / in the office reach the department manager (needs the app DB)."""
def test_saber_question_with_a_file_or_to_a_department_reaches_the_manager(monkeypatch):
    """Owner, 26 Nov 2026: «ايش المطلوب لاصدار سابر» with a declaration attached went to the canned reply."""
    from unittest.mock import Mock
    from app import command_agent as ca, command_ai as ai
    monkeypatch.setattr(ai, 'answer_saber_question', Mock(side_effect=AssertionError('intercepted')))
    monkeypatch.setattr(ai, 'is_saber_information_question', lambda q: True)
    monkeypatch.setattr(ca, 'call_model', Mock(side_effect=ValueError('model reached')))
    for text in ('ايش المطلوب لاصدار سابر\n\n[أرفق المالك الآن ملف «بيان.pdf» (PDF). اقرأه بأداة ask_document قبل الرد.]',
                 'فيصل: ايش المطلوب لاصدار سابر للسيراميك'):
        assert ca.run_agent(None, text) is None  # went on to the agent/routing (model failure → None), not the canned reply
    tok = ca.OFFICE.set({'key': 'clearance', 'tools': (), 'system': ''})
    try:
        assert ca.run_agent(None, 'ايش المطلوب لاصدار سابر للسيراميك') is None
    finally:
        ca.OFFICE.reset(tok)
