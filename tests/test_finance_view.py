"""Pure renderer tests with synthetic data; no DB, real documents or network."""
from copy import deepcopy
from html.parser import HTMLParser
import re
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


def total(**extra):
    return {
        'owner_id': 1, 'owner_name': 'صاحب حساب اختباري أول', 'currency': 'SAR',
        'receivable_minor': 1250, 'payable_minor': 375, 'net_minor': 875,
        'receivable_display': '12.50', 'payable_display': '3.75', 'net_display': '8.75',
        'payable_document_count': 1, **extra,
    }


def summary_groups(output):
    return re.findall(r'<article class="summary-group".*?</article>', output, re.DOTALL)


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


def test_summary_is_prominent_and_keeps_owners_and_currencies_separate():
    totals = [
        total(),
        total(currency='JPY', receivable_minor=7, payable_minor=2, net_minor=5,
              receivable_display='7', payable_display='2', net_display='5'),
        total(owner_id=3, owner_name='صاحب حساب اختباري ثان', receivable_minor=600,
              payable_minor=125, net_minor=475, receivable_display='6.00',
              payable_display='1.25', net_display='4.75'),
    ]
    output = view.render_dashboard(session('viewer'), [], [], [], [], [], totals=totals)
    assert output.index('<section class="hero">') < output.index('id="financial-summary"') < output.index('<div class="stats">')
    assert '<html lang="ar" dir="rtl">' in output
    groups = summary_groups(output)
    assert len(groups) == len(totals)
    for group, item in zip(groups, totals):
        assert 'data-owner-id="'+str(item['owner_id'])+'"' in group
        assert 'data-currency="'+item['currency']+'"' in group
        assert item['owner_name'] in group
        assert 'معرّف صاحب الحساب: '+view._number(item['owner_id']) in group
        assert 'العملة: <bdi>'+item['currency']+'</bdi>' in group
        for field in ('receivable_display', 'payable_display', 'net_display'):
            assert view._number(item[field]) in group
        assert group.count('<dt>') == 3
    assert 'JPY' not in groups[0] and 'JPY' not in groups[2]
    assert 'صاحب حساب اختباري ثان' not in groups[0] and 'صاحب حساب اختباري ثان' not in groups[1]
    assert '12.50' not in groups[1] and '12.50' not in groups[2]
    assert output.count('<span class="summary-value">') == 9
    assert 'لا يوجد إجمالي جامع بينها' in output
    assert '.summary-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))' in output
    assert '@media(max-width:700px)' in output and '.summary-cards{grid-template-columns:1fr}' in output


def test_summary_does_not_merge_owners_with_the_same_name():
    totals = [total(owner_id=1), total(owner_id=2)]
    groups = summary_groups(view.render_dashboard(session('viewer'), [], [], [], [], [], totals))
    assert len(groups) == 2
    assert 'data-owner-id="1"' in groups[0] and 'data-owner-id="2"' in groups[1]
    assert all('صاحب حساب اختباري أول' in group for group in groups)


@pytest.mark.parametrize('currency,receivable,payable,net', [
    ('SAR', '0.00', '0.00', '0.00'),
    ('SAR', '-2.75', '1.00', '-3.75'),
    ('SAR', '2.00', '-1.50', '3.50'),
    ('SAR', '-3.00', '-1.00', '-2.00'),
    ('JPY', '0', '0', '0'),
    ('KWD', '-0.001', '0.000', '-0.001'),
])
def test_summary_preserves_exact_zero_negative_and_currency_precision(currency, receivable, payable, net):
    # The service supplies formatted money. The view never recalculates from minor units.
    item = total(currency=currency, receivable_display=receivable,
                 payable_display=payable, net_display=net)
    output = view.render_dashboard(session('viewer'), [], [], [], [], [], [item])
    group = summary_groups(output)[0]
    assert re.findall(r'<span class="summary-value"><bdi class="num">(.*?)</bdi></span>', group) == [receivable, payable, net]
    assert 'الموجب مستحق لصاحب الحساب، والسالب رصيد دائن للجهات المقابلة' in group
    assert 'الموجب دين على صاحب الحساب، والسالب رصيد مدين لصالحه' in group
    assert 'الذمم المدينة ناقص الذمم الدائنة' in group


@pytest.mark.parametrize('missing', [None, ''])
def test_missing_summary_amounts_are_not_fabricated_from_minor_units(missing):
    item = total(receivable_display=missing, payable_display=missing, net_display=missing)
    group = summary_groups(view.render_dashboard(session('viewer'), [], [], [], [], [], [item]))[0]
    assert group.count('<span class="summary-value">'+view._number(None)) == 3
    assert '12.50' not in group and '3.75' not in group and '8.75' not in group
    assert '<span class="summary-value">'+view._number('0.00') not in group


@pytest.mark.parametrize('totals', [None, []])
def test_missing_totals_never_infer_zero_or_recalculate_from_detail_rows(totals):
    output = view.render_dashboard(session('viewer'), parties(), [document(status='posted')],
                                   [total()], [], [], totals)
    section = output.split('id="financial-summary"', 1)[1].split('</section>', 1)[0]
    assert 'لا تتوفر إجماليات مرحّلة للعرض' in section
    assert 'لا تُفترض أرصدة صفرية' in section
    assert not summary_groups(output) and 'summary-value' not in section


def test_summary_records_only_posted_scope_and_never_claims_complete_finances():
    output = view.render_dashboard(session('viewer'), [], [], [], [], [], [total()])
    assert 'من البيانات المسجلة والمرحّلة فقط' in output
    assert output.count('مسجل ومرحّل فقط') == 3
    assert 'إثباتات القبض والدفع والتسويات والقيود العكسية المرحّلة' in output
    assert 'دون خصم التخصيصات مرة ثانية' in output
    assert 'المسودات والمستندات قيد المراجعة مستبعدة' in output
    assert 'لا يمثل ربحًا أو نقدًا متاحًا أو صورة مالية مكتملة' in output
    assert 'لا ينفذ مقاصة بين الجهات' in output
    assert 'تبقى الالتزامات غير المسجلة خارج هذه الإجماليات' in output


@pytest.mark.parametrize('count,warning', [(0, True), (1, False), (None, False)])
def test_missing_posted_debt_warning_is_explicit_and_not_assumed(count, warning):
    item = total(payable_document_count=count, payable_minor=0, payable_display='0.00')
    output = view.render_dashboard(session('viewer'), [], [], [], [], [], [item])
    assert ('لا توجد مستندات ديون مرحّلة مسجلة لهذا الحساب بهذه العملة' in output) == warning
    if warning:
        assert 'لا يثبت عدم وجود التزامات فعلية' in output
        assert 'قد توجد ديون لم تُسجل بعد' in output


def test_missing_posted_debt_warning_preserves_negative_payable_without_claiming_zero():
    item = total(payable_document_count=0, payable_minor=-125, payable_display='-1.25',
                 net_minor=1375, net_display='13.75')
    output = view.render_dashboard(session('viewer'), [], [], [], [], [], [item])
    group = summary_groups(output)[0]
    assert view._number('-1.25') in group and view._number('13.75') in group
    assert 'لا توجد مستندات ديون مرحّلة مسجلة لهذا الحساب بهذه العملة' in group
    assert 'لا يثبت عدم وجود التزامات فعلية' in group
    assert 'الصفر المعروض' not in group and view._number('0.00') not in group


def test_summary_escapes_every_display_and_group_identifier():
    bad = '\"><script>synthetic</script><img src=x onerror=alert(1)>'
    item = total(owner_id=bad, owner_name=bad, currency=bad, receivable_display=bad,
                 payable_display=bad, net_display=bad)
    output = view.render_dashboard(session('viewer'), [], [], [], [], [], [item])
    page = Page(output)
    assert bad not in output and '&lt;script&gt;' in output
    assert not {'script', 'img'} & set(page.tags)
    assert len(page.ids) == len(set(page.ids))
    assert len(summary_groups(output)) == 1


@pytest.mark.parametrize('role', ['admin', 'finance', 'transport', 'viewer'])
def test_summary_is_read_only_and_retains_all_existing_actions(role):
    inputs = [session(role), parties(), [document()], [total()], [], [], [total()]]
    before = deepcopy(inputs)
    output = view.render_dashboard(*inputs)
    assert inputs == before
    groups = summary_groups(output)
    assert len(groups) == 1 and not Page(groups[0]).forms
    assert {form['action'] for form in Page(output).posts} == {
        form['action'] for form in Page(view.render_dashboard(*inputs[:-1])).posts
    }
    assert 'script' not in Page(output).tags


@pytest.mark.parametrize('role', ['admin', 'finance', 'transport', 'viewer'])
def test_dashboard_role_gates(role):
    actions = {f['action'] for f in Page(dashboard(session(role))).posts}
    if role == 'admin':
        assert actions == {'/finance/documents', '/finance/parties', '/finance/rules', '/finance/owners/1/display-name'}
    elif role == 'finance':
        assert actions == {'/finance/documents'}
    else:
        assert not actions


@pytest.mark.parametrize('status', ['draft', 'reviewed', 'posted', 'reversed', 'void'])
@pytest.mark.parametrize('role', ['admin', 'finance', 'viewer'])
def test_detail_role_gates(role, status):
    output = view.render_document(session(role), document(status=status), [], [], [])
    actions = {f['action'].rsplit('/', 1)[-1] for f in Page(output).posts}
    expected = {'admin': {'draft': {'review', 'void', 'claim-details'}, 'reviewed': {'post', 'void', 'claim-details'}, 'posted': {'reverse', 'claim-details'}},
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
    assert {f['action'].rsplit('/', 1)[-1] for f in Page(view.render_document(approve_only, document(), [], [], [])).posts} == {'void', 'claim-details'}


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


OPENING_CREDIT_PAIRS = [
    ('opening_receivable', 'receipt'),
    ('opening_receivable', 'receivable_adjustment'),
    ('opening_payable', 'payment'),
    ('opening_payable', 'payable_adjustment'),
]
OPENING_LABELS = {
    'opening_receivable': 'رصيد افتتاحي مدين',
    'opening_payable': 'رصيد افتتاحي دائن (دين على صاحب الحساب)',
}


@pytest.fixture(params=['opening_receivable', 'opening_payable'])
def opening_kind(request):
    return request.param


def opening_document(**extra):
    return document(**{
        'kind': 'opening_receivable', 'source_role': 'summary', 'amount_basis': 'net',
        'opening_cutoff': '2026-01-01', 'document_date': '2026-01-01',
        'opening_confirmation_ref': 'synthetic-owner-net-balance-approval',
        'opening_review_ack': False, **extra,
    })


def test_opening_creation_fields_are_optional_blank_and_not_workflow_inputs():
    output = dashboard()
    f = fields(Page(output).form('/finance/documents'))
    assert set(OPENING_LABELS) <= {o['value'] for o in f['kind']['options']}
    assert all(label in output for label in OPENING_LABELS.values())
    assert f['opening_cutoff']['type'] == 'date'
    assert f['opening_cutoff']['value'] == ''
    assert 'required' not in f['opening_cutoff']
    assert 'required' not in f['opening_confirmation_ref']
    assert 'opening_review_ack' not in f and 'opening_ack' not in f
    assert 'تفاصيل الرصيد الافتتاحي المدين أو الدائن فقط' in output
    assert 'مرجع موافقة صريحة من المستخدم أو صاحب الحساب' in output
    assert '(summary)' in output and '(net)' in output
    assert 'تاريخ المستند مساويًا لتاريخ القطع' in output
    assert 'اترك روابط الشحنة والفاتورة والبيان الجمركي فارغة' in output
    assert 'احتفظ بنص المبلغ الأصلي ودقته العشرية وإشارته كما وردت' in output
    assert 'إقرار التقريب مستقل' in output
    assert 'ولا تعاد إضافة الحركات التاريخية المشمولة فيه' in output
    assert 'أدخل مبلغ الدين على صاحب الحساب كقيمة رقمية موجبة' in output
    assert 'حتى لو كان نص المبلغ الأصلي سالبًا' in output
    assert 'يبقى النص الأصلي بإشارته محفوظًا دون تغيير' in output
    assert 'بما فيه الإشارة والعملة أو الفواصل' in output


@pytest.mark.parametrize('status,action', [('draft', 'review'), ('reviewed', 'post')])
@pytest.mark.parametrize('rounding', [True, False])
def test_opening_requires_separate_explicit_review_and_post_ack(opening_kind, status, action, rounding):
    output = view.render_document(session(), opening_document(kind=opening_kind, status=status, rounding_required=rounding), [], [], [])
    f = fields(Page(output).form('/finance/documents/8/'+action))
    assert f['opening_ack']['type'] == 'checkbox'
    assert f['opening_ack']['value'] == '1' and 'required' in f['opening_ack']
    assert 'checked' not in f['opening_ack']
    assert f['confirmation']['value'] == '1' and 'required' in f['confirmation']
    assert 'opening_review_ack' not in f
    assert ('rounding_ack' in f) == (rounding and action == 'review')
    if 'rounding_ack' in f:
        assert 'required' in f['rounding_ack'] and 'checked' not in f['rounding_ack']
    assert 'المطالبات أو الديون والتسويات التاريخية' in output
    assert 'ليس إيرادًا أو مصروفًا جديدًا، ولا إثبات قبض أو دفع' in output
    ordinary = fields(Page(view.render_document(session(), document(status=status), [], [], [])).form('/finance/documents/8/'+action))
    assert 'opening_ack' not in ordinary


@pytest.mark.parametrize('ack', [False, True])
def test_opening_detail_displays_immutable_cutoff_evidence_and_workflow_ack(opening_kind, ack):
    d = opening_document(kind=opening_kind, opening_review_ack=ack)
    before = deepcopy(d)
    output = view.render_document(session(), d, [], [], [])
    assert d == before
    assert '<h2>'+OPENING_LABELS[opening_kind]+'</h2>' in output
    assert 'تاريخ قطع الرصيد الافتتاحي' in output and d['opening_cutoff'] in output
    assert d['opening_confirmation_ref'] in output
    assert ('تم الإقرار أثناء المراجعة' if ack else 'بانتظار إقرار المراجعة') in output
    assert 'تاريخ القطع ومرجع الاعتماد محفوظان دون تعديل لاحق' in output
    assert d['source_amount_raw'] in output and d['source_amount'] in output
    assert d['rounded_amount_display'] in output
    assert ('القيمة العشرية الأصلية' in output) == (opening_kind == 'opening_receivable')
    assert 'بتاريخ بعد القطع فقط' in output
    if opening_kind == 'opening_payable':
        assert 'صافي الدين التاريخي على صاحب الحساب' in output
        assert 'إثبات دفع فعلي أو تسوية غير نقدية للذمم الدائنة' in output
        assert 'إثبات قبض فعلي' not in output
    else:
        assert 'صافي المستحق التاريخي لصاحب الحساب' in output
        assert 'إثبات قبض فعلي أو تسوية غير نقدية للذمم المدينة' in output
        assert 'إثبات دفع فعلي' not in output
    for form in Page(output).forms:
        assert not {'opening_cutoff', 'opening_confirmation_ref', 'opening_review_ack'} & set(fields(form))


def test_opening_payable_preserves_signed_source_and_positive_posting_amount():
    d = opening_document(kind='opening_payable', source_amount='12.501',
                         source_amount_raw='-12.501 SAR من مصدر اختباري')
    before = deepcopy(d)
    output = view.render_document(session(), d, [], [], [])
    assert d == before
    assert '<dd>-12.501 SAR من مصدر اختباري</dd>' in output
    assert '<dt>مقدار الرصيد الدائن قبل التقريب</dt><dd>12.501</dd>' in output
    assert 'القيمة العشرية الأصلية' not in output
    assert '<strong>'+view._number('12.50')+'</strong>' in output
    assert 'مبلغ الدين على صاحب الحساب يسجل كقيمة رقمية موجبة' in output
    assert 'يبقى نص المبلغ الأصلي بإشارته محفوظًا دون تغيير' in output


@pytest.mark.parametrize('cached', [False, True])
def test_opening_owner_approval_does_not_claim_independent_verification(opening_kind, cached):
    output = view.render_document(session(), opening_document(kind=opening_kind, source_cached_external=cached), [], [], [])
    assert 'مسجل من المصدر فقط' in output
    assert 'تم التحقق بدليل مستقل' not in output
    assert 'ملخص تجميعي لصافي الرصيد الافتتاحي' in output
    assert 'ملخص تجميعي: دليل فقط' not in output
    if cached:
        assert 'يستند الرصيد الافتتاحي إلى مرجع الاعتماد الصريح' in output
        assert 'ولا يعد ذلك تحققًا مستقلًا' in output
        assert 'نعم؛ يلزم تحقق مستقل' not in output
    else:
        assert 'غير معلّم كمصدر خارجي مخزن' in output


def test_cached_opening_without_approval_reference_displays_missing_requirement(opening_kind):
    output = view.render_document(session(), opening_document(kind=opening_kind, source_cached_external=True, opening_confirmation_ref=''), [], [], [])
    assert 'يلزم مرجع اعتماد صريح لصافي الرصيد الافتتاحي' in output
    assert 'يستند الرصيد الافتتاحي إلى مرجع الاعتماد الصريح' not in output
    assert 'تم التحقق بدليل مستقل' not in output


@pytest.mark.parametrize('renderer', ['dashboard', 'document', 'statement'])
def test_opening_labels_remain_distinct_and_evidence_is_escaped(opening_kind, renderer):
    bad = '\"><script>synthetic</script><img src=x>'
    d = opening_document(kind=opening_kind, opening_cutoff=bad, opening_confirmation_ref=bad,
                         source_amount_raw=bad)
    if renderer == 'dashboard':
        output = dashboard(session('viewer'), [d])
    elif renderer == 'document':
        output = view.render_document(session(), d, [], [], [])
    else:
        side = 'payable' if opening_kind == 'opening_payable' else 'receivable'
        output = view.render_statement(session(), parties()[0], parties()[1], 'SAR', [d], '12.50', side=side)
    assert OPENING_LABELS[opening_kind] in output
    assert 'رصيد تاريخي صافٍ' in output
    assert 'ليس إيرادًا أو مصروفًا جديدًا، ولا إثبات قبض أو دفع' in output
    assert bad not in output and '&lt;script&gt;' in output
    page = Page(output)
    assert 'script' not in page.tags and 'img' not in page.tags
    assert len(page.ids) == len(set(page.ids))
    assert set(page.labels) <= set(page.ids)


@pytest.mark.parametrize('opening_kind,credit_kind', OPENING_CREDIT_PAIRS)
@pytest.mark.parametrize('opening_is_current', [True, False])
def test_opening_allocation_accepts_later_actual_credit_in_both_directions(opening_kind, credit_kind, opening_is_current):
    opening = opening_document(kind=opening_kind, status='posted', opening_review_ack=True)
    credit = document(id=9, kind=credit_kind, status='posted', document_date='2026-01-02')
    current, candidate = (opening, credit) if opening_is_current else (credit, opening)
    before = deepcopy([current, candidate])
    output = view.render_document(session(), current, [], [], [candidate])
    assert [current, candidate] == before
    f = fields(Page(output).form('/finance/allocations'))
    fixed, choice = ('document_id', 'credit_id') if opening_is_current else ('credit_id', 'document_id')
    assert f[fixed]['value'] == str(current['id'])
    assert f[choice]['options'][1]['value'] == str(candidate['id'])
    assert {'csrf', 'idempotency_key', 'amount'} <= set(f)
    assert OPENING_LABELS[opening_kind] in output


@pytest.mark.parametrize('opening_kind,credit_kind', OPENING_CREDIT_PAIRS)
@pytest.mark.parametrize('credit_date', ['2025-12-31', '2026-01-01', '', None, 'not-a-date', '2026-02-30'])
@pytest.mark.parametrize('opening_is_current', [True, False])
def test_opening_allocation_hides_missing_or_pre_cutoff_credit_dates(opening_kind, credit_kind, credit_date, opening_is_current):
    opening = opening_document(kind=opening_kind, status='posted')
    credit = document(id=9, kind=credit_kind, status='posted', document_date=credit_date)
    current, candidate = (opening, credit) if opening_is_current else (credit, opening)
    output = view.render_document(session(), current, [], [], [candidate])
    assert '/finance/allocations' not in {f['action'] for f in Page(output).posts}


@pytest.mark.parametrize('opening_kind,credit_kind', OPENING_CREDIT_PAIRS)
@pytest.mark.parametrize('cutoff', ['', None, 'not-a-date', '2026-02-30'])
@pytest.mark.parametrize('opening_is_current', [True, False])
def test_opening_allocation_hides_missing_or_invalid_cutoff(opening_kind, credit_kind, cutoff, opening_is_current):
    opening = opening_document(kind=opening_kind, status='posted', opening_cutoff=cutoff)
    credit = document(id=9, kind=credit_kind, status='posted', document_date='2026-01-02')
    current, candidate = (opening, credit) if opening_is_current else (credit, opening)
    output = view.render_document(session(), current, [], [], [candidate])
    assert '/finance/allocations' not in {f['action'] for f in Page(output).posts}


@pytest.mark.parametrize('opening_is_current', [True, False])
def test_opening_allocation_hides_incompatible_credit_in_both_directions(opening_kind, opening_is_current):
    compatible = {credit for kind, credit in OPENING_CREDIT_PAIRS if kind == opening_kind}
    for kind in set(view.KINDS) - compatible:
        opening = opening_document(kind=opening_kind, status='posted')
        other = document(id=9, kind=kind, status='posted', document_date='2026-01-02')
        current, candidate = (opening, other) if opening_is_current else (other, opening)
        output = view.render_document(session(), current, [], [], [candidate])
        assert '/finance/allocations' not in {f['action'] for f in Page(output).posts}


@pytest.mark.parametrize('opening_kind,credit_kind', OPENING_CREDIT_PAIRS)
@pytest.mark.parametrize('opening_is_current', [True, False])
@pytest.mark.parametrize('changes', [
    {'currency': 'USD'}, {'owner_id': 10}, {'counterparty_id': 11}, {'status': 'reviewed'},
    {'status': 'reversed'}, {'id': 8},
])
def test_opening_allocation_hides_different_ledger_or_ineligible_credit(opening_kind, credit_kind, opening_is_current, changes):
    opening = opening_document(kind=opening_kind, status='posted')
    credit = document(**{'id': 9, 'kind': credit_kind, 'status': 'posted',
                         'document_date': '2026-01-02', **changes})
    current, candidate = (opening, credit) if opening_is_current else (credit, opening)
    output = view.render_document(session(), current, [], [], [candidate])
    assert '/finance/allocations' not in {f['action'] for f in Page(output).posts}


@pytest.mark.parametrize('opening_kind,credit_kind', OPENING_CREDIT_PAIRS)
@pytest.mark.parametrize('restricted_session', [session('finance'), session('viewer'), session(can_approve_finance=False)])
@pytest.mark.parametrize('opening_is_current', [True, False])
def test_opening_allocations_remain_admin_only(opening_kind, credit_kind, restricted_session, opening_is_current):
    opening = opening_document(kind=opening_kind, status='posted')
    credit = document(id=9, kind=credit_kind, status='posted', document_date='2026-01-02')
    current, candidate = (opening, credit) if opening_is_current else (credit, opening)
    output = view.render_document(restricted_session, current, [], [], [candidate])
    assert '/finance/allocations' not in {f['action'] for f in Page(output).posts}


def test_owner_name_correction_is_narrow_guarded_and_accessible():
    ps=parties()+[dict(parties()[0],id=3,confirmed=False)]
    ps[0]['name_revision']=17
    output=view.render_dashboard(session(),ps,[],[],[],[])
    page=Page(output)
    form=page.form('/finance/owners/1/display-name')
    inputs=fields(form)
    assert set(inputs)=={'csrf','idempotency_key','expected_revision','name','reason','confirmation'}
    assert inputs['expected_revision']['value']=='17'
    assert inputs['name']['value']==ps[0]['name']
    assert inputs['name']['maxlength']=='200' and 'required' in inputs['name']
    assert inputs['reason']['maxlength']=='1000' and 'required' in inputs['reason']
    assert inputs['confirmation']['value']=='1' and 'required' in inputs['confirmation']
    assert inputs['csrf']['value']=='fixture-csrf'
    UUID(inputs['idempotency_key']['value'])
    assert '/finance/owners/2/display-name' not in output
    assert '/finance/owners/3/display-name' not in output
    assert 'type="reset">إلغاء التغييرات</button>' in output
    assert 'تبقى الهوية الأصلية ومراجع المصدر والأرصدة' in output
    for s in (session('finance'),session('viewer'),session(can_approve_finance=False)):
        assert '/display-name' not in view.render_dashboard(s,ps,[],[],[],[])
    assert len(page.ids)==len(set(page.ids))
    assert all(label in page.ids for label in page.labels)
