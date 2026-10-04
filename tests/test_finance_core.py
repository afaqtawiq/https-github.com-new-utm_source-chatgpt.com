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


@pytest.mark.parametrize('kind,expected',[('claim',('receivable',1)),('receipt',('receivable',-1)),('payable',('payable',1)),('expense',('payable',1)),('payment',('payable',-1)),('receivable_adjustment',('receivable',-1)),('payable_adjustment',('payable',-1))])
def test_sides_no_profit_or_tax_inference(kind,expected):
    assert core.KINDS[kind]==expected


def test_independent_verification_requires_reference():
    f=form();f.update(source_cached_external='1',source_verification='independently_verified')
    assert core.validation_issues(core.parse_document(f))
    f['verification_ref']='Synthetic bank receipt page 1'
    assert core.validation_issues(core.parse_document(f))==[]
