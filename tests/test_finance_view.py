"""Pure renderer tests with synthetic data; no DB, real documents or network."""
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from app import finance_view as view


class Page(HTMLParser):
    def __init__(self, rendered):
        super().__init__(convert_charrefs=True)
        self.forms, self.ids, self.labels, self.links, self.tags = [], [], [], [], []
        self.current_form = self.current_select = None
        self.feed(rendered)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append(tag)
        if 'id' in a:
            self.ids.append(a['id'])
        if tag == 'label' and 'for' in a:
            self.labels.append(a['for'])
        if tag == 'a':
            self.links.append(a.get('href', ''))
        if tag == 'form':
            self.current_form = dict(a, fields=[])
            self.forms.append(self.current_form)
        if tag in ('input', 'select', 'textarea') and self.current_form is not None:
            self.current_form['fields'].append(a)
        if tag == 'select':
            self.current_select = a
            a['options'] = []
        if tag == 'option' and self.current_select is not None:
            self.current_select['options'].append(a)

    def handle_endtag(self, tag):
        if tag == 'form':
            self.current_form = None
        if tag == 'select':
            self.current_select = None

    @property
    def posts(self):
        return [form for form in self.forms if form.get('method') == 'post']

    def form(self, action):
        return next(form for form in self.forms if form.get('action') == action)


def session(role='admin', **extra):
    return {'role': role, 'name': 'مستخدم اختباري', 'csrf': 'fixture-csrf', **extra}


def parties():
    return [
        {'id': 1, 'kind': 'owner', 'name': 'صاحب حساب اختباري', 'identity_ref': 'O-1', 'confirmed': True},
        {'id': 2, 'kind': 'counterparty', 'name': 'جهة اختبارية', 'identity_ref': 'C-1', 'confirmed': True},
    ]


def document(**extra):
    return {
        'id': 8, 'owner_id': 1, 'counterparty_id': 2, 'owner_name': 'صاحب حساب اختباري',
        'counterparty_name': 'جهة اختبارية', 'kind': 'claim', 'status': 'draft', 'currency': 'SAR',
        'amount_display': '12.50', 'allocated_display': '0.00', 'remaining_display': '12.50',
        'source_amount': '12.501', 'source_amount_raw': '12.501 من المصدر', 'source_ref': 'source-test',
        'source_locator': 'test.xlsx!A2', 'economic_ref': 'test-event', 'document_date': '2026-01-02',
        'source_role': 'detail', 'source_date_raw': '2 Jan 2026', 'source_status_raw': 'غير مثبت',
        'source_verification': 'recorded', 'source_cached_external': False,
        'rounding_required': True, 'rounded_amount_display': '12.50', 'validation_issues': [],
        'source_raw': {'source': 'test.xlsx'}, **extra,
    }


def dashboard(s=None, docs=None):
    return view.render_dashboard(s or session(), parties(), docs or [], [], [], [])


def fields(form):
    return {f['name']: f for f in form['fields'] if f.get('name')}


@pytest.mark.parametrize('renderer', ['dashboard', 'document', 'statement'])
def test_all_user_strings_are_escaped(renderer):
    bad = '\"><script>alert(1)</script><img src=x onerror=alert(1)>'
    s = session(name=bad, csrf=bad)
    ps = [{'id': 1, 'kind': 'owner', 'name': bad, 'identity_ref': bad, 'confirmed': True}]
    d = document(owner_name=bad, source_ref=bad, notes=bad, source_raw={'a': bad}, supersedes_id=bad)
    audit = [{'actor_name': bad, 'action': bad, 'detail': bad, 'created_at': bad}]
    if renderer == 'dashboard':
        output = view.render_dashboard(s, ps, [d], [{'owner_name': bad, 'currency': bad}], audit, [{'owner_name': bad, 'basis': bad}])
    elif renderer == 'document':
        output = view.render_document(s, d, [], audit, [])
    else:
        output = view.render_statement(s, ps[0], {'id': 2, 'name': bad}, bad,
                                       [{'id': 8, 'source_ref': bad, 'kind': bad, 'debit_display': bad}], bad)
    parsed = Page(output)
    assert 'script' not in parsed.tags and 'img' not in parsed.tags
    assert bad not in output
    assert '&lt;script&gt;' in output


def test_zero_is_not_hidden_or_replaced_with_missing_value():
    assert view.esc(0) == '0'
    assert view._number(0) == '<bdi class="num">0</bdi>'
    output = view.render_document(session(), document(amount_display=0, allocated_display=0), [], [], [])
    assert output.count('<bdi class="num">0</bdi>') >= 2
    output = view.render_statement(session(), parties()[0], parties()[1], 'JPY', [], 0)
    assert '<bdi class="num">0</bdi>' in output


@pytest.mark.parametrize('role', ['admin', 'finance', 'transport', 'viewer'])
def test_dashboard_role_gates(role):
    actions = {f['action'] for f in Page(dashboard(session(role))).posts}
    if role == 'admin':
        assert actions == {'/finance/documents', '/finance/parties', '/finance/rules'}
    elif role == 'finance':
        assert actions == {'/finance/documents'}
    else:
        assert not actions


@pytest.mark.parametrize('status', ['draft', 'reviewed', 'posted', 'reversed', 'void'])
@pytest.mark.parametrize('role', ['admin', 'finance', 'viewer'])
def test_detail_role_gates(role, status):
    output = view.render_document(session(role), document(status=status), [], [], [])
    actions = {f['action'].rsplit('/', 1)[-1] for f in Page(output).posts}
    expected = {'admin': {'draft': {'review', 'void'}, 'reviewed': {'post', 'void'}, 'posted': {'reverse'}},
                'finance': {'draft': {'review'}}}
    assert actions == expected.get(role, {}).get(status, set())


@pytest.mark.parametrize('status', ['draft', 'reviewed', 'posted'])
def test_explicit_permission_denial_hides_mutations(status):
    s = session(can_edit_finance=False, can_approve_finance=False)
    assert not Page(dashboard(s)).posts
    assert not Page(view.render_document(s, document(status=status), [], [], [])).posts


def test_permissions_are_independent():
    edit_only = session(can_edit_finance=True, can_approve_finance=False)
    assert {f['action'] for f in Page(dashboard(edit_only)).posts} == {'/finance/documents'}
    assert not Page(view.render_document(edit_only, document(status='reviewed'), [], [], [])).posts
    approve_only = session(can_edit_finance=False, can_approve_finance=True)
    assert '/finance/documents' not in {f['action'] for f in Page(dashboard(approve_only)).posts}
    assert {f['action'].rsplit('/', 1)[-1] for f in Page(view.render_document(approve_only, document(), [], [], [])).posts} == {'void'}


def test_document_form_preserves_economic_and_source_evidence_fields():
    output = dashboard()
    f = fields(Page(output).form('/finance/documents'))
    for key in ('economic_ref', 'source_ref', 'source_locator', 'source_amount_raw'):
        assert key in f and 'required' in f[key]
    for key in ('source_role', 'source_date_raw', 'source_status_raw', 'source_verification', 'source_cached_external'):
        assert key in f
    assert next(o['value'] for o in f['source_role']['options'] if 'selected' in o) == 'detail'
    assert next(o['value'] for o in f['source_verification']['options'] if 'selected' in o) == 'recorded'
    assert f['source_cached_external']['value'] == '1'
    assert 'checked' not in f['source_cached_external']
    assert 'required' not in f['document_date']
    assert 'سجّل كل حدث مالي مرة واحدة' in output
    assert 'ملخص المصدر دليل فقط' in output


def test_currency_unknown_and_rate_unset_not_seeded():
    page = Page(dashboard())
    currency = fields(page.form('/finance/documents'))['currency']
    assert currency['options'][0]['value'] == ''
    assert not any('selected' in o for o in currency['options'])
    assert {o['value'] for o in currency['options']} == {'', 'SAR', 'AED', 'QAR', 'USD', 'EUR', 'GBP', 'OMR', 'BHD', 'KWD', 'JPY'}
    assert 'required' not in currency
    rate = fields(page.form('/finance/rules'))['rate']
    assert rate['value'] == ''


@pytest.mark.parametrize('kind', ['dashboard', 'draft', 'reviewed', 'posted'])
def test_post_forms_have_csrf_and_unique_uuid_keys(kind):
    s = session()
    output = dashboard(s) if kind == 'dashboard' else view.render_document(s, document(status=kind), [], [], [])
    page = Page(output)
    keys = []
    for form in page.posts:
        f = fields(form)
        assert f['csrf']['value'] == s['csrf']
        assert f['csrf']['type'] == 'hidden'
        key = f['idempotency_key']['value']
        assert UUID(key).version == 4
        keys.append(key)
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize('rounding', [True, False])
def test_review_confirmation_and_conditional_rounding_ack(rounding):
    f = fields(Page(view.render_document(session(), document(rounding_required=rounding), [], [], [])).form('/finance/documents/8/review'))
    assert f['confirmation']['value'] == '1' and 'required' in f['confirmation']
    assert ('rounding_ack' in f) == rounding
    if rounding:
        assert f['rounding_ack']['value'] == '1' and 'required' in f['rounding_ack']


@pytest.mark.parametrize('status,action', [('reviewed', 'post'), ('posted', 'reverse')])
def test_post_and_reverse_require_explicit_confirmation(status, action):
    f = fields(Page(view.render_document(session(), document(status=status), [], [], [])).form('/finance/documents/8/'+action))
    assert f['confirmation']['value'] == '1' and 'required' in f['confirmation']
    assert 'required' in f['reason']


@pytest.mark.parametrize('credit,debit', [('receipt', 'claim'), ('payment', 'payable'), ('payment', 'expense'),
                                        ('receivable_adjustment', 'claim'), ('payable_adjustment', 'expense')])
def test_eligible_allocation_form(credit, debit):
    d = document(kind=credit, status='posted')
    candidate = document(id=9, kind=debit, status='posted')
    page = Page(view.render_document(session(), d, [], [], [candidate]))
    f = fields(page.form('/finance/allocations'))
    assert f['credit_id']['value'] == '8'
    assert f['document_id']['options'][1]['value'] == '9'
    assert {'csrf', 'idempotency_key', 'amount'} <= set(f)
    candidate['currency'] = 'USD'
    assert '/finance/allocations' not in {p['action'] for p in Page(view.render_document(session(), d, [], [], [candidate])).posts}
    assert '/finance/allocations' not in {p['action'] for p in Page(view.render_document(session('finance'), d, [], [], [candidate])).posts}


def test_reversed_allocations_are_explicitly_inactive_on_counterpart():
    allocations = [
        {'id': 1, 'credit_id': 9, 'document_id': 8, 'amount_display': '10.00', 'reversed_at': '2026-01-03T01:00:00Z'},
        {'id': 2, 'credit_id': 10, 'document_id': 8, 'amount_display': '2.00', 'reversed_at': None},
    ]
    output = view.render_document(session(), document(status='posted'), allocations, [], [])
    assert 'معكوس · غير مطبق' in output and 'نشط · مطبق' in output
    assert 'تاريخ العكس' in output and '2026-01-03T01:00:00Z' in output
    assert 'لا يدخل في المبلغ المخصص أو المتبقي لأي من المستندين' in output


def test_supersession_link_preserves_prior_evidence():
    output = view.render_document(session(), document(supersedes_id=7), [], [], [])
    assert '/finance/documents/7' in Page(output).links
    assert 'يظل الدليل السابق محفوظًا دون تعديل' in output


@pytest.mark.parametrize('side', ['receivable', 'payable'])
def test_statement_side_preserved_and_not_netting(side):
    entries = [{'id': 30, 'document_id': 8, 'kind': 'claim', 'status': 'reversal', 'debit_display': '0.00',
                'credit_display': '12.50', 'running_display': '0.00', 'source_ref': 'test-event'}]
    output = view.render_statement(session(), parties()[0], parties()[1], 'SAR', entries, '0.00', side=side)
    page = Page(output)
    export = next(link for link in page.links if link.startswith('/finance/statement.csv?'))
    assert parse_qs(urlsplit(export).query) == {'owner_id': ['1'], 'counterparty_id': ['2'], 'currency': ['SAR'], 'side': [side]}
    assert view.SIDES[side] in output and 'لا تجري مقاصة' in output
    assert 'قيد عكسي' in output
    assert '/finance/documents/8' in page.links
    assert '/finance/documents/30' not in page.links


@pytest.mark.parametrize('renderer', ['dashboard', 'document', 'statement'])
def test_accessible_unique_ids_and_no_external_assets(renderer):
    output = dashboard() if renderer == 'dashboard' else (
        view.render_document(session(), document(), [], [], []) if renderer == 'document' else
        view.render_statement(session(), parties()[0], parties()[1], 'SAR', [], '0.00'))
    page = Page(output)
    assert len(page.ids) == len(set(page.ids))
    assert set(page.labels) <= set(page.ids)
    assert '<html lang="ar" dir="rtl">' in output
    assert 'script' not in page.tags and 'img' not in page.tags and 'link' not in page.tags
    assert 'https://' not in output and 'http://' not in output
    assert not page.posts if renderer == 'statement' else True
