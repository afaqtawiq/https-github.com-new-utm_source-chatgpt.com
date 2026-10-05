"""Synthetic snapshot calculations only; no database, live money, or customers."""
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.finance_closing_core import (
    BILLED_FIELDS, COMPLETENESS_FIELDS, COST_FIELDS, MONEY_FIELDS,
    ROUNDING_POLICY, calculate_monthly_close,
)


MONTH = '2026-01'


def complete(**changes):
    result = dict(income_complete=True, expenses_complete=True,
                  mapping_complete=True, confirmation_ref='Synthetic monthly approval')
    result.update(changes)
    return result


def mapping(**changes):
    result = dict.fromkeys(MONEY_FIELDS, 0)
    result.update(basis_status='confirmed', basis_ref='Synthetic basis reconciliation',
                  allocation_ref='Synthetic classification approval', costs_complete=True)
    result.update(changes)
    return result


def claim(document_id=101, currency='SAR', **changes):
    result = dict(document_id=document_id, kind='claim', currency=currency,
                  amount_minor=19137, document_date='2026-01-12', status='posted',
                  mapping=mapping(shared_service_income_minor=10001,
                                  agency_only_income_minor=500, saber_revenue_minor=3001,
                                  tax_reserve_minor=1515, pass_through_minor=4120,
                                  goods_value_minor=10000001))
    result.update(changes)
    return result


def expense(document_id=102, currency='SAR', **changes):
    result = dict(document_id=document_id, kind='expense', currency=currency,
                  amount_minor=2001, document_date='2026-01-13', status='posted',
                  mapping=mapping(shared_actual_cost_minor=1000,
                                  agency_only_actual_cost_minor=1001,
                                  related_document_id=101))
    result.update(changes)
    return result


def calculate(lines=None, completeness=None):
    return calculate_monthly_close(MONTH, [claim(), expense()] if lines is None else lines,
                                   completeness=complete() if completeness is None else completeness)


def test_complete_draft_reconciles_exactly_and_keeps_saber_all_agency():
    report = calculate()
    assert report['status'] == 'draft'
    assert report['ready_for_distribution'] is True
    assert report['manager_allocation_active'] is False
    assert report['blockers'] == []
    row, = report['currencies']
    assert row['billed_total_minor'] == 19137
    assert row['expense_total_minor'] == 2001
    assert row['shared_profit_minor'] == 9001
    assert row['agency_only_profit_minor'] == 2500
    assert row['profit_minor'] == 11501
    assert row['agency_share_minor'] == 7000
    assert row['partner_share_minor'] == 4501
    assert row['agency_share_minor'] + row['partner_share_minor'] == row['profit_minor']
    assert row['rounding_minor'] == 1
    assert row['rounding_policy'] == ROUNDING_POLICY
    assert row['rounding_note']


def test_saber_margin_is_wholly_agency_and_never_split_with_partner():
    source = claim(amount_minor=7011, mapping=mapping(saber_revenue_minor=7011))
    cost = expense(amount_minor=2911, mapping=mapping(agency_only_actual_cost_minor=2911))
    row, = calculate([source, cost])['currencies']
    assert row['agency_only_profit_minor'] == 4100
    assert row['shared_profit_minor'] == 0
    assert row['agency_share_minor'] == 4100
    assert row['partner_share_minor'] == 0


def test_goods_tax_pass_through_receivables_and_manager_percent_never_become_profit():
    source = claim()
    source.update(receivable_minor=10**18, payable_minor=1, net_minor=10**18-1,
                  customer_name='Synthetic label only', manager_percent=30)
    source['mapping']['goods_value_minor'] = 10**18
    report = calculate([source, expense()])
    row, = report['currencies']
    assert row['profit_minor'] == 11501
    assert row['goods_value_minor'] == 10**18
    assert row['tax_reserve_minor'] == 1515
    assert row['pass_through_minor'] == 4120
    assert report['manager_allocation_active'] is False


def test_goods_value_cannot_reconcile_missing_billed_income():
    source = claim(amount_minor=123, mapping=mapping(goods_value_minor=123))
    row, = calculate([source])['currencies']
    assert row['ready_for_distribution'] is False
    assert row['profit_minor'] is None
    assert row['agency_share_minor'] is None


@pytest.mark.parametrize('currency', ['SAR', 'KWD', 'JPY'])
def test_no_fx_or_major_unit_rounding_and_odd_minor_goes_to_partner(currency):
    source = claim(currency=currency, amount_minor=1, mapping=mapping(shared_service_income_minor=1))
    row, = calculate([source])['currencies']
    assert row['shared_profit_minor'] == 1
    assert row['agency_share_minor'] == 0
    assert row['partner_share_minor'] == 1
    assert row['rounding_minor'] == 1


def test_currencies_are_isolated_with_no_cross_currency_total():
    report = calculate([claim(), expense(), claim(201, 'KWD', amount_minor=9,
                                                mapping=mapping(shared_service_income_minor=9))])
    currencies = {row['currency']: row for row in report['currencies']}
    assert list(currencies) == ['KWD', 'SAR']
    assert currencies['SAR']['profit_minor'] == 11501
    assert currencies['KWD']['profit_minor'] == 9
    assert 'profit_minor' not in report
    assert 'agency_share_minor' not in report


def test_currency_blockers_do_not_reclassify_or_pool_another_currency():
    blocked = claim(201, 'KWD', mapping=mapping(basis_status='unresolved'))
    report = calculate([claim(), expense(), blocked])
    rows = {row['currency']: row for row in report['currencies']}
    assert report['ready_for_distribution'] is False
    assert rows['KWD']['profit_minor'] is None
    assert rows['SAR']['ready_for_distribution'] is True
    assert rows['SAR']['profit_minor'] == 11501


@pytest.mark.parametrize('key', MONEY_FIELDS)
@pytest.mark.parametrize('missing', [True, False])
def test_missing_mapping_amount_is_unknown_not_zero(key, missing):
    source = claim()
    if missing:
        del source['mapping'][key]
    else:
        source['mapping'][key] = None
    report = calculate([source, expense()])
    row, = report['currencies']
    assert report['ready_for_distribution'] is False
    assert report['lines'][0]['mapping'][key] is None
    assert row[key] is None
    assert row['profit_minor'] is None
    assert row['agency_share_minor'] is None
    assert row['partner_share_minor'] is None
    assert any('قيمة غير محددة' in issue for issue in report['blockers'])


def test_missing_entire_mapping_returns_blocked_draft_not_a_zero_profit():
    source = claim()
    del source['mapping']
    report = calculate([source])
    assert report['status'] == 'draft'
    assert report['ready_for_distribution'] is False
    row, = report['currencies']
    assert row['billed_total_minor'] == source['amount_minor']
    assert all(row[key] is None for key in MONEY_FIELDS)
    assert row['profit_minor'] is None


def test_explicit_zero_is_valid_and_distinct_from_missing_costs():
    source = claim(amount_minor=71, mapping=mapping(tax_reserve_minor=71))
    report = calculate([source])
    row, = report['currencies']
    assert report['ready_for_distribution'] is True
    assert row['profit_minor'] == 0
    assert row['agency_share_minor'] == row['partner_share_minor'] == 0
    assert row['rounding_minor'] == 0
    source['mapping']['costs_complete'] = False
    assert calculate([source])['ready_for_distribution'] is False


@pytest.mark.parametrize('status', [None, '', 'unresolved', 'undefined'])
def test_unreconciled_basis_blocks_even_with_known_customer_math(status):
    source = claim()
    source['mapping']['basis_status'] = status
    report = calculate([source, expense()])
    assert report['ready_for_distribution'] is False
    assert report['currencies'][0]['profit_minor'] is None
    assert any('أساس الإيراد غير محسوم' in issue for issue in report['blockers'])


@pytest.mark.parametrize('key', ['basis_ref', 'allocation_ref'])
@pytest.mark.parametrize('value', [None, '', ' \n\t '])
def test_approval_references_are_required(key, value):
    source = claim()
    source['mapping'][key] = value
    report = calculate([source])
    assert report['ready_for_distribution'] is False
    assert report['currencies'][0]['agency_share_minor'] is None


@pytest.mark.parametrize('value', [None, False])
def test_pending_actual_costs_block_profit_and_share_proposal(value):
    source = claim()
    source['mapping']['costs_complete'] = value
    report = calculate([source, expense()])
    assert report['ready_for_distribution'] is False
    assert report['currencies'][0]['profit_minor'] is None


@pytest.mark.parametrize('key', COMPLETENESS_FIELDS)
@pytest.mark.parametrize('value', [None, False])
def test_every_period_completeness_flag_is_mandatory(key, value):
    report = calculate(completeness=complete(**{key: value}))
    assert report['ready_for_distribution'] is False
    assert report['currencies'][0]['profit_minor'] is None
    assert report['blockers']


def test_period_completeness_has_no_default_true_and_requires_approval_reference():
    for completeness in (None, {}, complete(confirmation_ref='')):
        report = calculate_monthly_close(MONTH, [claim(), expense()], completeness=completeness)
        assert report['ready_for_distribution'] is False
        assert report['currencies'][0]['agency_share_minor'] is None


@pytest.mark.parametrize('field', COST_FIELDS)
def test_claim_embedded_cost_is_blocked_to_prevent_double_counting(field):
    source = claim()
    source['mapping'][field] = 1
    report = calculate([source, expense()])
    assert report['ready_for_distribution'] is False
    assert any('مستند مصروف مستقل' in issue for issue in report['blockers'])


@pytest.mark.parametrize('field', BILLED_FIELDS + ('goods_value_minor',))
def test_expense_can_only_allocate_actual_costs(field):
    source = expense()
    source['mapping'][field] = 1
    report = calculate([claim(), source])
    assert report['ready_for_distribution'] is False
    assert any('المصروف يوزع على التكاليف فقط' in issue for issue in report['blockers'])


@pytest.mark.parametrize('source', [claim(amount_minor=19138), expense(amount_minor=2002)])
def test_document_classification_must_reconcile_exactly(source):
    report = calculate([source])
    assert report['ready_for_distribution'] is False
    assert report['currencies'][0]['profit_minor'] is None
    assert any('لا يطابق' in issue for issue in report['blockers'])


@pytest.mark.parametrize('shared_cost,agency_cost', [(10002, 0), (0, 3502), (10002, 3502)])
def test_losses_remain_visible_but_do_not_create_unauthorized_negative_shares(shared_cost, agency_cost):
    cost = expense(amount_minor=shared_cost + agency_cost,
                   mapping=mapping(shared_actual_cost_minor=shared_cost,
                                   agency_only_actual_cost_minor=agency_cost))
    report = calculate([claim(), cost])
    row, = report['currencies']
    assert row['shared_profit_minor'] == 10001-shared_cost
    assert row['agency_only_profit_minor'] == 3501-agency_cost
    assert row['profit_minor'] == 13502-shared_cost-agency_cost
    assert row['agency_share_minor'] is None
    assert row['partner_share_minor'] is None
    assert row['rounding_minor'] is None
    assert report['ready_for_distribution'] is False
    assert any('خسارة' in issue for issue in report['blockers'])


def test_empty_report_is_blocked_even_with_explicit_completeness():
    report = calculate([])
    assert report['ready_for_distribution'] is False
    assert report['currencies'] == []
    assert report['blockers']


def test_input_and_nested_metadata_are_not_mutated_or_shared_with_output():
    lines = [claim(), expense()]
    lines[0]['mapping']['evidence'] = {'references': ['synthetic:source']}
    completeness = complete()
    original = deepcopy((lines, completeness))
    report = calculate_monthly_close(MONTH, lines, completeness=completeness)
    assert (lines, completeness) == original
    report['lines'][0]['mapping']['evidence']['references'].append('changed')
    report['lines'][0]['mapping']['shared_service_income_minor'] = 999
    report['completeness']['confirmation_ref'] = 'changed'
    assert (lines, completeness) == original


def test_date_objects_normalize_without_changing_input():
    source = claim(document_date=date(2026, 1, 12))
    report = calculate([source])
    assert report['lines'][0]['document_date'] == '2026-01-12'
    assert source['document_date'] == date(2026, 1, 12)


@pytest.mark.parametrize('month', ['2026-1', '2026-00', '2026-13', '0000-01',
                                   '2026-01-01', '2026-01 ', '', None, 202601])
def test_invalid_month_is_rejected(month):
    with pytest.raises(ValueError):
        calculate_monthly_close(month, [claim()], completeness=complete())


@pytest.mark.parametrize('value', ['2026-02-01', '2025-01-12', '2026-01-32',
                                   '2026-1-12', '', None, datetime(2026, 1, 12)])
def test_out_of_period_or_invalid_dates_are_rejected(value):
    with pytest.raises(ValueError):
        calculate([claim(document_date=value)])


@pytest.mark.parametrize('value', ['', None, 'BAD', 'SARA', 123])
def test_missing_or_unknown_currency_is_not_silently_sar(value):
    with pytest.raises(ValueError):
        calculate([claim(currency=value)])


@pytest.mark.parametrize('value', [True, False, 1.0, '1', -1, Decimal('1'), float('nan')])
@pytest.mark.parametrize('field', MONEY_FIELDS)
def test_every_amount_requires_exact_nonnegative_integer_minor_units(field, value):
    source = claim()
    source['mapping'][field] = value
    with pytest.raises(ValueError):
        calculate([source])


@pytest.mark.parametrize('field', ['document_id', 'amount_minor'])
@pytest.mark.parametrize('value', [None, 0, -1, True, False, 1.0, '1', Decimal('1')])
def test_document_identity_and_amount_must_be_positive_integers(field, value):
    with pytest.raises(ValueError):
        calculate([claim(**{field: value})])


def test_repeated_document_is_rejected_even_if_mapping_or_currency_differs():
    with pytest.raises(ValueError):
        calculate([claim(), claim(currency='USD')])
    with pytest.raises(ValueError):
        calculate([claim(), expense(document_id=101)])


@pytest.mark.parametrize('kind', ['receipt', 'payment', 'payable', 'opening_receivable',
                                  'opening_payable', 'receivable_adjustment', 'payable_adjustment', None])
def test_balance_movements_are_not_profit_documents(kind):
    with pytest.raises(ValueError):
        calculate([claim(kind=kind)])


@pytest.mark.parametrize('status', ['draft', 'reviewed', 'reversed', 'void', ''])
def test_nonposted_status_when_supplied_blocks_distribution(status):
    report = calculate([claim(status=status)])
    assert report['ready_for_distribution'] is False
    assert report['currencies'][0]['profit_minor'] is None


@pytest.mark.parametrize('value', [1, 0, 'true', 'false', [], {}])
def test_cost_completeness_requires_a_real_boolean(value):
    source = claim()
    source['mapping']['costs_complete'] = value
    with pytest.raises(ValueError):
        calculate([source])


@pytest.mark.parametrize('key', COMPLETENESS_FIELDS)
@pytest.mark.parametrize('value', [1, 0, 'true'])
def test_period_completeness_requires_real_booleans(key, value):
    with pytest.raises(ValueError):
        calculate(completeness=complete(**{key: value}))


@pytest.mark.parametrize('value', [0, -1, True, '101', 102])
def test_optional_related_document_must_be_valid_and_not_self(value):
    source = expense()
    source['mapping']['related_document_id'] = value
    with pytest.raises(ValueError):
        calculate([claim(), source])


@pytest.mark.parametrize('value', ['approved', 'guessed', True, 1])
def test_unknown_basis_states_are_rejected(value):
    source = claim()
    source['mapping']['basis_status'] = value
    with pytest.raises(ValueError):
        calculate([source])


@pytest.mark.parametrize('value', [True, [], 'mapping', 1])
def test_non_object_mapping_is_rejected(value):
    with pytest.raises(ValueError):
        calculate([claim(mapping=value)])


@pytest.mark.parametrize('value', [None, 'lines', {}, 1])
def test_non_iterable_or_invalid_line_container_is_rejected(value):
    with pytest.raises(ValueError):
        calculate_monthly_close(MONTH, value, completeness=complete())


@pytest.mark.parametrize('value', [True, [], 'complete', 1])
def test_non_object_completeness_is_rejected(value):
    with pytest.raises(ValueError):
        calculate_monthly_close(MONTH, [claim()], completeness=value)


def test_reference_validation_and_whitespace_normalization():
    source = claim()
    source['mapping']['basis_ref'] = '  synthetic basis  '
    assert calculate([source])['lines'][0]['mapping']['basis_ref'] == 'synthetic basis'
    for value in [True, ['synthetic'], 'x\x00y', 'x'*2001]:
        source['mapping']['basis_ref'] = value
        with pytest.raises(ValueError):
            calculate([source])


def fixed_saber_claim(**mapping_changes):
    values = mapping(saber_revenue_minor=1000, saber_fixed_cost_minor=250,
                     saber_fixed_cost_approved=True,
                     saber_fixed_cost_ref='Synthetic explicit owner approval')
    values.update(mapping_changes)
    return claim(amount_minor=1000, mapping=values)


def test_owner_approved_fixed_saber_cost_is_reporting_only_and_wholly_agency():
    source = fixed_saber_claim()
    before = deepcopy(source)
    report = calculate([source])
    row, = report['currencies']
    assert report['status'] == 'draft'
    assert report['ready_for_distribution'] is True
    assert row['saber_fixed_cost_minor'] == 250
    assert row['saber_revenue_minor'] == 1000
    assert row['agency_only_profit_minor'] == 750
    assert row['agency_share_minor'] == 750
    assert row['partner_share_minor'] == 0
    assert row['shared_profit_minor'] == 0
    assert row['expense_total_minor'] == 0
    assert row['shared_actual_cost_minor'] == row['agency_only_actual_cost_minor'] == 0
    assert len(report['lines']) == 1
    assert report['lines'][0]['kind'] == 'claim'
    assert source == before


def test_fixed_saber_cost_leaves_shared_fifty_fifty_pool_untouched():
    source = fixed_saber_claim(shared_service_income_minor=10001)
    source['amount_minor'] = 11001
    row, = calculate([source])['currencies']
    assert row['shared_profit_minor'] == 10001
    assert row['agency_only_profit_minor'] == 750
    assert row['agency_share_minor'] == 5750
    assert row['partner_share_minor'] == 5001
    assert row['profit_minor'] == 10751
    assert row['agency_share_minor'] + row['partner_share_minor'] == row['profit_minor']
    assert row['rounding_minor'] == 1


def test_legacy_absent_fixed_cost_fields_normalize_to_unused_zero():
    report = calculate()
    for line in report['lines']:
        assert line['mapping']['saber_fixed_cost_minor'] == 0
        assert line['mapping']['saber_fixed_cost_approved'] is False
        assert line['mapping']['saber_fixed_cost_ref'] == ''
    row, = report['currencies']
    assert row['saber_fixed_cost_minor'] == 0
    assert row['profit_minor'] == 11501
    assert row['agency_share_minor'] == 7000
    assert row['partner_share_minor'] == 4501


@pytest.mark.parametrize('changes', [
    {'saber_fixed_cost_approved': False},
    {'saber_fixed_cost_ref': ''},
    {'saber_fixed_cost_ref': None},
    {'saber_fixed_cost_ref': ' \t\n '},
])
def test_fixed_saber_cost_requires_explicit_owner_approval_and_evidence(changes):
    report = calculate([fixed_saber_claim(**changes)])
    row, = report['currencies']
    assert report['ready_for_distribution'] is False
    assert row['profit_minor'] is None
    assert row['agency_share_minor'] is None
    assert any('اعتمادًا صريحًا من المالك' in issue for issue in report['blockers'])


@pytest.mark.parametrize('key', ['saber_fixed_cost_approved', 'saber_fixed_cost_ref'])
def test_positive_fixed_cost_cannot_rely_on_missing_approval_fields(key):
    source = fixed_saber_claim()
    del source['mapping'][key]
    report = calculate([source])
    assert report['ready_for_distribution'] is False
    assert report['currencies'][0]['agency_share_minor'] is None


@pytest.mark.parametrize('value', [None, 0])
def test_fixed_cost_requires_known_positive_saber_revenue(value):
    source = fixed_saber_claim(saber_revenue_minor=value, shared_service_income_minor=1000)
    report = calculate([source])
    assert report['ready_for_distribution'] is False
    assert any('إيراد سابر موجبًا' in issue for issue in report['blockers'])


@pytest.mark.parametrize('value', [None, 0, 1, 'true', 'false', [], {}])
def test_fixed_cost_approval_rejects_non_boolean_values(value):
    with pytest.raises(ValueError):
        calculate([fixed_saber_claim(saber_fixed_cost_approved=value)])


@pytest.mark.parametrize('value', [True, False, 250.0, '250', -1, Decimal('250'), float('nan')])
def test_fixed_cost_requires_exact_nonnegative_integer_minor_units(value):
    with pytest.raises(ValueError):
        calculate([fixed_saber_claim(saber_fixed_cost_minor=value)])


def test_explicitly_unknown_fixed_cost_stays_unknown_instead_of_becoming_zero():
    report = calculate([fixed_saber_claim(saber_fixed_cost_minor=None)])
    row, = report['currencies']
    assert report['lines'][0]['mapping']['saber_fixed_cost_minor'] is None
    assert row['saber_fixed_cost_minor'] is None
    assert row['agency_only_profit_minor'] is None
    assert row['agency_share_minor'] is None
    assert report['ready_for_distribution'] is False


def test_explicit_zero_fixed_cost_needs_no_owner_approval_or_saber_revenue():
    source = claim(amount_minor=300, mapping=mapping(shared_service_income_minor=300,
                                                    saber_fixed_cost_minor=0))
    row, = calculate([source])['currencies']
    assert row['ready_for_distribution'] is True
    assert row['agency_share_minor'] == row['partner_share_minor'] == 150


def test_fixed_cost_on_expense_is_blocked_even_if_owner_approval_supplied():
    source = expense(mapping=mapping(shared_actual_cost_minor=1000,
                                    agency_only_actual_cost_minor=1001,
                                    saber_fixed_cost_minor=250,
                                    saber_fixed_cost_approved=True,
                                    saber_fixed_cost_ref='Synthetic owner approval'))
    report = calculate([claim(), source])
    assert report['ready_for_distribution'] is False
    assert report['currencies'][0]['profit_minor'] is None
    assert any('ولا تسجل على المصروف' in issue for issue in report['blockers'])


@pytest.mark.parametrize('lines_reversed', [False, True])
def test_linked_actual_agency_cost_and_fixed_saber_cost_block_both_lines(lines_reversed):
    source = fixed_saber_claim()
    cost = expense(amount_minor=200, mapping=mapping(agency_only_actual_cost_minor=200,
                                                   related_document_id=source['document_id']))
    lines = [cost, source] if lines_reversed else [source, cost]
    report = calculate(lines)
    assert report['ready_for_distribution'] is False
    for line in report['lines']:
        assert line['ready_for_distribution'] is False
        assert any('قد يتكرران' in issue for issue in line['blockers'])
    row, = report['currencies']
    assert row['saber_fixed_cost_minor'] == 250
    assert row['agency_only_actual_cost_minor'] == 200
    assert row['profit_minor'] is None
    assert row['agency_share_minor'] is None
    assert row['partner_share_minor'] is None


def test_linked_shared_only_actual_cost_does_not_duplicate_agency_saber_cost():
    source = fixed_saber_claim(shared_service_income_minor=200)
    source['amount_minor'] = 1200
    cost = expense(amount_minor=100, mapping=mapping(shared_actual_cost_minor=100,
                                                   related_document_id=source['document_id']))
    row, = calculate([source, cost])['currencies']
    assert row['ready_for_distribution'] is True
    assert row['agency_only_profit_minor'] == 750
    assert row['shared_profit_minor'] == 100
    assert row['agency_share_minor'] == 800
    assert row['partner_share_minor'] == 50


def test_actual_agency_cost_linked_to_other_claim_does_not_duplicate_fixed_cost():
    source = fixed_saber_claim()
    other = claim(103, amount_minor=500, mapping=mapping(agency_only_income_minor=500))
    cost = expense(amount_minor=100, mapping=mapping(agency_only_actual_cost_minor=100,
                                                   related_document_id=other['document_id']))
    row, = calculate([source, other, cost])['currencies']
    assert row['ready_for_distribution'] is True
    assert row['agency_only_profit_minor'] == 1150
    assert row['agency_share_minor'] == 1150
    assert row['partner_share_minor'] == 0


@pytest.mark.parametrize('changes', [
    {'basis_status': 'unresolved'},
    {'basis_ref': ''},
    {'allocation_ref': ''},
    {'costs_complete': False},
    {'costs_complete': None},
    {'shared_actual_cost_minor': None},
    {'agency_only_actual_cost_minor': None},
])
def test_fixed_cost_approval_never_bypasses_other_basis_or_completeness_blockers(changes):
    report = calculate([fixed_saber_claim(**changes)])
    assert report['ready_for_distribution'] is False
    assert report['currencies'][0]['agency_share_minor'] is None


@pytest.mark.parametrize('key', COMPLETENESS_FIELDS)
def test_fixed_cost_owner_approval_does_not_replace_month_completeness(key):
    report = calculate([fixed_saber_claim()], completeness=complete(**{key: False}))
    assert report['ready_for_distribution'] is False
    assert report['currencies'][0]['agency_share_minor'] is None


def test_fixed_cost_loss_is_not_silently_shifted_to_shared_pool():
    source = fixed_saber_claim(saber_fixed_cost_minor=1200, shared_service_income_minor=1000)
    source['amount_minor'] = 2000
    row, = calculate([source])['currencies']
    assert row['shared_profit_minor'] == 1000
    assert row['agency_only_profit_minor'] == -200
    assert row['profit_minor'] == 800
    assert row['agency_share_minor'] is None
    assert row['partner_share_minor'] is None
    assert row['ready_for_distribution'] is False
