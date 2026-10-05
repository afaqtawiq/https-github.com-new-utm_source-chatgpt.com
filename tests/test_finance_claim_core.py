"""Synthetic exact-money presentation tests; no live data or network."""
from copy import deepcopy
import pytest
from app.finance_claim_core import parse_details, present_details, COMPONENTS
from app.finance_claim_view import itemization_section, render_customer_claim


def document(**extra):
    return dict(id=42,kind='claim',status='posted',currency='SAR',amount_minor=12345,
                amount_display='123.45',owner_name='وكيل تجريبي',counterparty_name='عميل اختباري',
                invoice_ref='DEMO-42',customs_ref='TEST-24',document_date='2026-01-02',**extra)


def form(**extra):
    return dict(expected_revision='0',confirmation='1',goods_amount='100.00',goods_currency='USD',
                exchange_rate='3.75',customs_duty='10',customs_other='0.45',clearance='20',
                saber='30',zakat='3',registry='10',tax='50',source_ref='Synthetic fixture source',
                reason='Synthetic approval',**extra)


def replace(source, **extra):
    return dict(source,**extra)


def detail():
    return present_details(dict(id=7,**parse_details(form(),document())))


def test_exact_total_excludes_goods_and_keeps_components():
    row=parse_details(form(),document())
    assert row['claim_total_minor']==12345
    assert row['goods_value_minor']==37500
    assert row['components']['customs_duty']==1000 and row['components']['customs_other']==45
    shown=detail()
    assert shown['customs_total_display']=='10.45'
    assert shown['claim_total_display']=='123.45' and shown['goods_value_display']=='375.00'


@pytest.mark.parametrize('change',[
    {'tax':'50.001'},{'tax':'49.99'},{'tax':'425'},{'tax':'-1'},{'tax':'NaN'},
    {'tax':''},{'tax':'1e2'},{'tax':'1,000'},{'tax':'∞'},
    {'goods_currency':'BAD'},{'goods_amount':'0'},{'goods_amount':'100.001'},
    {'exchange_rate':'0'},{'exchange_rate':'NaN'},{'exchange_rate':'999999999999'},
    {'goods_currency':'SAR','exchange_rate':'3.75'},
    {'expected_revision':'-1'},{'expected_revision':'x'},{'expected_revision':'9999999999999999999'},
    {'confirmation':'0'},{'source_ref':''},{'reason':''},{'unknown':'1'}])
def test_rejects_invalid_or_mismatched_explicit_data(change):
    with pytest.raises(ValueError): parse_details(replace(form(),**change),document())


@pytest.mark.parametrize('key',[key for key,_ in COMPONENTS])
def test_requires_every_component_even_when_zero(key):
    fields=form();del fields[key]
    with pytest.raises(ValueError):parse_details(fields,document())


@pytest.mark.parametrize('change',[{'kind':'expense'},{'status':'void'},{'status':'reversed'},{'currency':''},{'amount_minor':None}])
def test_rejects_non_active_claim(change):
    with pytest.raises(ValueError):parse_details(form(),replace(document(),**change))


def test_fx_rounds_once_with_decimal_half_up():
    values=parse_details(replace(form(),goods_amount='1',exchange_rate='1.005'),document())
    assert values['goods_value_minor']==101


def test_customer_view_excludes_internal_data_and_escapes_all_values():
    d=replace(document(),notes='SECRET COST AND MARGIN',source_ref='PRIVATE',source_locator='PRIVATE PATH',economic_ref='INTERNAL',other_customer='OTHER CUSTOMER')
    values=detail();values['reason']='SECRET APPROVAL';values['source_ref']='PRIVATE'
    original=deepcopy((d,values))
    page=render_customer_claim(d,values)
    assert all(x not in page for x in ('SECRET','PRIVATE','INTERNAL','OTHER CUSTOMER'))
    assert '/finance/documents/42/claim.pdf' in page
    for label in ('جمارك','تخليص','سابر','زكاة','سجل تجاري','ضريبة','دون قيمة البضاعة'):
        assert label in page
    assert (d,values)==original
    d['counterparty_name']='<script>bad</script>'
    assert '<script>' not in render_customer_claim(d,values)
    assert '&lt;script&gt;' in render_customer_claim(d,values)


def test_itemization_form_permissions_stale_revision_and_active_download():
    d=replace(document(),claim_details=detail())
    admin={'role':'admin','csrf':'token','can_approve_finance':True}
    page=itemization_section(admin,d)
    assert 'name="expected_revision" value="7"' in page
    assert 'claim-details' in page and '/claim.pdf' in page
    assert 'حفظ التفصيل المعتمد' not in itemization_section(dict(admin,can_approve_finance=False),d)
    assert 'حفظ التفصيل المعتمد' not in itemization_section({'role':'finance'},d)
    assert '/claim.pdf' not in itemization_section(admin,replace(d,status='reversed'))
    assert itemization_section(admin,replace(d,kind='opening_receivable'))==''


def test_persisted_decimal_fx_is_presented_without_exponent():
    from decimal import Decimal
    row=dict(id=7,**parse_details(replace(form(),goods_amount='1000000',exchange_rate='0.00000001'),document()))
    row['exchange_rate']=Decimal('0.00000001')
    assert present_details(row)['exchange_rate']=='0.00000001'
