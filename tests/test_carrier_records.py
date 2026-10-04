"""Synthetic-only company parsing and export boundaries."""
import csv
import io
import pytest
from app.carrier_records import (COLUMNS, contact_keys, csv_text, identity_key,
                                 normalize_phone, normalize_record, prepare_matrix)


def example(**extra):
    return {'company_name':'Example Carrier', 'country':'SA', 'phone':'0500000001', **extra}


def test_unknown_information_stays_blank_and_no_consent_inferred():
    record, errors = normalize_record(example(contact_consent='granted', offer_consent=1))
    assert not errors
    assert record['phone'] == '+966500000001'
    assert record['capacity'] == record['vehicle_types'] == record['preferred_routes'] == ''
    assert 'contact_consent' not in record and 'offer_consent' not in record
    assert record['verification_status'] == 'unverified'


@pytest.mark.parametrize('raw', ['+966050000001', '+966500000001 / +966500000002', '+9710500000001', 'not a phone', '+966++500000001', '050+0000001', '+9+6+6+500000001'])
def test_invalid_contacts_are_not_repaired(raw):
    _,errors=normalize_record(example(phone=raw))
    assert errors


def test_international_country_is_not_guessed_or_merged():
    sa,_=normalize_record(example())
    ae,_=normalize_record(example(country='AE',phone='0500000001'))
    assert sa['phone']=='+966500000001' and ae['phone']=='+971500000001'
    assert identity_key(sa)!=identity_key(ae)
    assert contact_keys(sa).isdisjoint(contact_keys(ae))


def test_unicode_phone_and_name_normalization():
    assert normalize_phone('٠٥٠٠٠٠٠٠٠١','SA')=='+966500000001'
    a,_=normalize_record(example(company_name='  EXAMPLE   Carrier  ',email='DISPATCH@EXAMPLE.INVALID'))
    b,_=normalize_record(example(company_name='example carrier'))
    assert identity_key(a)==identity_key(b)
    assert a['email']=='dispatch@example.invalid'


def test_public_contact_verified_requires_source_and_date():
    _,errors=normalize_record(example(verification_status='public_contact_verified'))
    assert errors
    record,errors=normalize_record(example(verification_status='public_contact_verified',source_url='https://example.invalid/contact',verified_on='2026-01-01'))
    assert not errors and record['verified_on']=='2026-01-01'


@pytest.mark.parametrize('key,value',[('website','javascript:alert(1)'),('source_url','https://user:secret@example.invalid'),('verified_on','2026-99-99'),('verified_on','2999-01-01'),('email','a@x.invalid,b@y.invalid'),('country','ZZ')])
def test_invalid_provenance_and_email(key,value):
    assert normalize_record(example(**{key:value}))[1]


def test_file_dedup_does_not_hide_first_valid_row_and_shared_contacts_need_review():
    matrix=[['company_name','country','phone'],['Example','SA','bad'],['Example','SA','0500000001'],[' EXAMPLE ','SA','+966500000001'],['Separate Company','SA','0500000001']]
    items=prepare_matrix(matrix)
    assert items[0]['errors']
    assert not items[1]['duplicate'] and not items[1]['errors']
    assert items[2]['duplicate']
    assert items[3]['errors'] and not items[3]['duplicate']


def test_driver_dataset_cannot_be_imported_as_company():
    with pytest.raises(ValueError):
        prepare_matrix([['driver_name','whatsapp_phone'],['Synthetic Driver','0500000001']])


def test_no_implicit_consent_columns_and_formula_export_safe():
    items=prepare_matrix([['company_name','country','contact_consent'],['Example','SA','granted']])
    assert not items[0]['errors'] and 'contact_consent' not in items[0]['data']
    exported=csv_text(['company_name','phone'],[{'company_name':'=HYPERLINK("https://example.invalid")','phone':'+966500000001'}])
    result=list(csv.reader(io.StringIO(exported.lstrip('\ufeff'))))[1]
    assert all(value.startswith("'") for value in result)


def test_template_contains_no_marketing_or_driver_registration_columns():
    assert not {'offer_consent','driver_name','whatsapp_phone','contact_consent'} & set(COLUMNS)


def test_skipped_duplicate_does_not_reserve_a_valid_later_company_contact():
    items=prepare_matrix([['company_name','country','phone'],['A','SA','0500000001'],['A','SA','0500000002'],['B','SA','0500000002']])
    assert items[1]['duplicate']
    assert not items[2]['errors'] and not items[2]['duplicate']


def test_csv_export_phone_roundtrip_and_excel_dates():
    from datetime import datetime
    from app.carrier_records import read_upload
    row=example(verified_on=datetime(2026,1,1))
    parsed,errors=normalize_record(row)
    assert not errors and parsed['verified_on']=='2026-01-01'
    exported=csv_text(COLUMNS,[parsed]).encode()
    imported=prepare_matrix(read_upload('companies.csv',exported))
    assert not imported[0]['errors'] and imported[0]['data']['phone']==parsed['phone']


def test_bounded_xlsx_and_csv_uploads():
    from app.carrier_records import read_upload
    from openpyxl import Workbook
    workbook=Workbook();sheet=workbook.active
    sheet.append(['company_name','country']);sheet.append(['Example','SA'])
    stream=io.BytesIO();workbook.save(stream)
    assert not prepare_matrix(read_upload('companies.xlsx',stream.getvalue()))[0]['errors']
    with pytest.raises(ValueError):
        read_upload('companies.csv',('company_name,country\n'+'Example,SA\n'*2001).encode())
    with pytest.raises(ValueError):
        read_upload('companies.exe',b'')


def test_database_duplicate_does_not_reserve_unused_contact_in_preview():
    from app.carrier_records import review_candidates
    items=prepare_matrix([['company_name','country','phone'],['Existing A','SA','0500000002'],['New B','SA','0500000002']])
    assert items[1]['errors']
    review_candidates(items,{2:'duplicate'})
    assert items[0]['duplicate']
    assert not items[1]['errors'] and not items[1]['duplicate']


@pytest.mark.parametrize('prefix', ['2','3','4','6','7','9'])
def test_uae_geographic_landlines_preserve_eight_national_digits(prefix):
    # Synthetic subscriber digits; format only, no call or ownership claim.
    expected='+971'+prefix+'0000001'
    assert normalize_phone('0'+prefix+'0000001','AE')==expected
    assert normalize_phone(expected,'AE')==expected
    assert normalize_phone('00971'+prefix+'0000001','SA')==expected


@pytest.mark.parametrize('value',['+971400000001','+9714000001','+97110000001','+97150000001'])
def test_uae_landline_wrong_length_or_prefix_is_not_repaired(value):
    with pytest.raises(ValueError):
        normalize_phone(value,'AE')
