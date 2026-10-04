"""Synthetic unit cases; no financial source documents or customer data."""
from decimal import Decimal
import csv
import io
import pytest
from app import finance_core as core


def form(**extra):
    return dict(owner_id='1',counterparty_id='2',kind='claim',currency='SAR',amount='123.45678901',
        document_date='2026-01-02',amount_basis='gross',source_role='detail',source_ref='fixture.xlsx',
        source_locator='sheet1!A2',economic_ref='event-1',**extra)


@pytest.mark.parametrize('currency,raw,expected', [('SAR','1.005',101),('KWD','1.0005',1001),('JPY','1.5',2),('SAR','0.004',0),('SAR','999999999999.99999999',100000000000000)])
def test_explicit_currency_rounding(currency,raw,expected):
    assert core.minor_units(core.decimal_amount(raw),currency)==expected


@pytest.mark.parametrize('bad',['0','-1','NaN','Infinity','1e3','1,000','1.123456789','1000000000000',None,''])
def test_invalid_amount(bad):
    with pytest.raises(ValueError):core.decimal_amount(bad)


def test_original_precision_separate_from_posting_amount():
    d=core.parse_document(form())
    assert d['source_amount']==Decimal('123.45678901') and d['source_amount_raw']=='123.45678901'
    assert d['amount_minor']==12346 and core.display_minor(d['amount_minor'],'SAR')=='123.46'
    assert core.display_minor(0,'SAR')=='0.00'


def test_unknown_is_not_sar_and_incomplete_date_stays_raw():
    f=form();f.update(currency='',document_date='',source_date_raw='2026-01-??')
    d=core.parse_document(f)
    assert d['currency']=='' and d['amount_minor'] is None and d['document_date'] is None
    assert d['source_date_raw']=='2026-01-??' and len(core.validation_issues(d))==2


def test_cached_values_and_summary_require_resolution():
    f=form();f.update(source_cached_external='1',source_status_raw='Matched',source_role='summary')
    d=core.parse_document(f)
    assert d['source_verification']=='recorded' and d['source_status_raw']=='Matched'
    assert len(core.validation_issues(d))==2


def test_allocation_disallows_unacknowledged_rounding():
    assert core.exact_minor('1.01','SAR')==101
    with pytest.raises(ValueError):core.exact_minor('1.005','SAR')
    with pytest.raises(ValueError):core.exact_minor('0.001','SAR')


@pytest.mark.parametrize('value',['=cmd()','  +cmd()','-1','@evil','\ttext','\ntext'])
def test_csv_formula_injection(value):
    rendered=core.csv_bytes(['a'],[[value],[0]])
    lines=list(csv.reader(io.StringIO(rendered.decode('utf-8-sig'))))
    assert lines[1][0]=="'"+value and lines[2][0]=='0'


@pytest.mark.parametrize('kind,expected',[('opening_receivable',('receivable',1)),('opening_payable',('payable',1)),('claim',('receivable',1)),('receipt',('receivable',-1)),('payable',('payable',1)),('expense',('payable',1)),('payment',('payable',-1)),('receivable_adjustment',('receivable',-1)),('payable_adjustment',('payable',-1))])
def test_sides_no_profit_or_tax_inference(kind,expected):
    assert core.KINDS[kind]==expected


def test_independent_verification_requires_reference():
    f=form();f.update(source_cached_external='1',source_verification='independently_verified')
    assert core.validation_issues(core.parse_document(f))
    f['verification_ref']='Synthetic bank receipt page 1'
    assert core.validation_issues(core.parse_document(f))==[]


def opening_form(**extra):
    data=form()
    data.update(kind='opening_receivable',source_role='summary',amount_basis='net',
        opening_cutoff='2026-01-02',opening_confirmation_ref='Synthetic owner approval, confirmed net balance and cutoff')
    data.update(extra)
    return data


@pytest.mark.parametrize('kind,side',[('opening_receivable','receivable'),('opening_payable','payable')])
def test_opening_preserves_precision_and_is_not_new_claim_or_receipt(kind,side):
    item=core.parse_document(opening_form(kind=kind,source_cached_external='1'))
    assert core.KINDS[item['kind']]==(side,1)
    assert item['kind'] not in ('claim','receipt','payable','payment','expense')
    assert item['source_amount']==Decimal('123.45678901') and item['amount_minor']==12346
    assert item['source_role']=='summary' and item['source_verification']=='recorded'
    assert item['source_cached_external'] and core.validation_issues(item)==[]


@pytest.mark.parametrize('kind',['opening_receivable','opening_payable'])
@pytest.mark.parametrize('extra',[
    {'opening_cutoff':''},{'opening_cutoff':'2026-01-03'},{'opening_confirmation_ref':''},
    {'source_role':'detail'},{'amount_basis':'gross'},{'invoice_ref':'invoice-1'},
    {'customs_ref':'declaration-1'},{'shipment_id':'1'},
    {'source_verification':'independently_verified','verification_ref':''},
])
def test_opening_requires_explicit_cutoff_net_summary_and_approval(kind,extra):
    assert core.validation_issues(core.parse_document(opening_form(kind=kind,**extra)))


def test_opening_payable_keeps_negative_source_evidence_but_posts_positive_liability():
    raw='-123.45678901 synthetic original credit balance'
    item=core.parse_document(opening_form(kind='opening_payable',source_amount_raw=raw,
        source_cached_external='1'))
    assert item['source_amount']==Decimal('123.45678901') and item['source_amount_raw']==raw
    assert item['amount_minor']==12346 and core.KINDS[item['kind']]==('payable',1)
    assert item['source_verification']=='recorded' and item['verification_ref']==''
    assert core.validation_issues(item)==[]
    for amount in ('-123.45678901','0'):
        with pytest.raises(ValueError):
            core.parse_document(opening_form(kind='opening_payable',amount=amount,source_amount_raw=raw))


def test_normal_document_cannot_carry_opening_override():
    data=form();data['opening_confirmation_ref']='Cannot bypass cached evidence check'
    with pytest.raises(ValueError):core.parse_document(data)
    data=form();data['opening_cutoff']='2026-01-02'
    with pytest.raises(ValueError):core.parse_document(data)


def total_row(**extra):
    result=dict(owner_id=1,owner_name='Synthetic owner',currency='SAR',receivable_minor=12345,
        payable_minor=2000,payable_document_count=1)
    result.update(extra)
    return result


def test_owner_totals_exact_receivables_minus_recorded_debts():
    first=total_row()
    second=dict(first,receivable_minor=Decimal('4321'),payable_minor=Decimal('345'),payable_document_count=2)
    result=core.owner_balance_totals([first,second])
    assert result==[dict(owner_id=1,owner_name='Synthetic owner',currency='SAR',receivable_minor=16666,
        payable_minor=2345,net_minor=14321,payable_document_count=3,
        receivable_display='166.66',payable_display='23.45',net_display='143.21')]
    assert first==total_row(), 'Read-only summary changed its input'


def test_owner_totals_never_mix_currencies_or_identical_owner_names():
    first=total_row()
    result=core.owner_balance_totals([first,dict(first,owner_id=2),dict(first,currency='KWD'),dict(first,currency='JPY')])
    assert len(result)==4
    keyed={(r['owner_id'],r['currency']):r for r in result}
    assert keyed[(1,'SAR')]['net_display']=='103.45'
    assert keyed[(2,'SAR')]['net_display']=='103.45'
    assert keyed[(1,'KWD')]['net_display']=='10.345'
    assert keyed[(1,'JPY')]['net_display']=='10345'


@pytest.mark.parametrize('receivable,payable,expected',[(0,0,'0.00'),(-125,200,'-3.25'),(125,-200,'3.25'),(200,200,'0.00')])
def test_owner_totals_preserve_zero_and_credit_balances(receivable,payable,expected):
    row=dict(total_row(),receivable_minor=receivable,payable_minor=payable,payable_document_count=0)
    item=core.owner_balance_totals([row])[0]
    assert item['net_display']==expected and item['payable_document_count']==0


def test_owner_totals_empty_and_no_dashboard_display_limit():
    assert core.owner_balance_totals([])==[]
    rows=[dict(total_row(),receivable_minor=1,payable_minor=0,payable_document_count=0) for _ in range(225)]
    assert core.owner_balance_totals(rows)[0]['net_display']=='2.25'


@pytest.mark.parametrize('field,value',[('receivable_minor',1.25),('payable_minor',Decimal('1.1')),('receivable_minor',True),('payable_document_count',-1),('currency',''),('currency','ZZZ'),('owner_id',0)])
def test_owner_totals_reject_missing_or_inexact_scope_and_units(field,value):
    with pytest.raises(ValueError):core.owner_balance_totals([dict(total_row(),**{field:value})])
