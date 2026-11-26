"""Import vs transit from the final consignee (owner, 26 Nov 2026). Pure: no network, model or database."""
from app import customs_movement as cm

# CMA CGM B/L ETG0138695 the owner sent: Djibouti → Jeddah, consignee in Doha, notify party = us in Riyadh.
CMA_BL = {
    'consignee': 'AHEMD IMAM FOR GENERAL TRADING',
    'consignee_address': 'ADDRESS:MUAITHER PLOT NO-53 STREET NO: 790 BUILDING: 216 DOHA QATAR',
    'notify_party': 'AFAQ TAWEEQ CONTRACTING AL AWAZAI STREET AR RIYAD SAUDI ARABIA',
    'marks': 'TCNU8381090 SEAL KO683837 AHMED IMAM GENERAL TRADING LLC CROP YEAR :2025/2026 NET WEIGHT: 60KG\nDEST: QUATR',
    'pod': 'JEDDAH',
}
# Chad certificate of origin 0029925: consignee in Dubai.
CHAD_COO = {'consignee': 'KOBAC GENERAL TRADING LLC DUBAI UAE AL RAS DEIRA DUBAI SHOP NO 6'}


def test_owner_bill_of_lading_is_transit_to_qatar_despite_saudi_port_and_notify_party():
    result = cm.infer(CMA_BL)
    assert result['movement'] == 'transit'
    assert result['destination'] == 'QA' and result['exit_port'] == 'منفذ سلوى'
    assert any('الطرف المُخطَر' in e for e in result['evidence'])
    line = cm.summary_ar(result, 'جدة')
    assert 'ترانزيت' in line and 'قطر' in line and 'استيراد' in line  # «لا تُطبق عليه خطوات الاستيراد»


def test_certificate_of_origin_to_dubai_is_transit_via_batha():
    result = cm.infer(CHAD_COO)
    assert (result['movement'], result['destination'], result['exit_port']) == ('transit', 'AE', 'منفذ البطحاء')


def test_saudi_consignee_is_import():
    for fields in ({'consignee': 'شركة السيراميك الحديثة - الرياض', 'notify_party': 'آفاق طويق جدة'},
                   {'consignee': 'Riyadh Ceramics Co', 'consignee_address': 'Al Sulay, Riyadh, Saudi Arabia', 'pod': 'Jeddah'}):
        assert cm.infer(fields)['movement'] == 'import'


def test_notify_party_alone_never_decides():
    assert cm.infer({'notify_party': 'AFAQ TAWEEQ RIYADH SAUDI ARABIA', 'pod': 'JEDDAH'})['movement'] == ''
    assert cm.infer({'consignee': 'TO ORDER', 'notify_party': 'X TRADING JEDDAH'})['movement'] == ''


def test_conflicting_destinations_need_review():
    result = cm.infer({'consignee': 'ABC LLC Dubai UAE', 'final_destination': 'Riyadh'})
    assert result['movement'] == 'review' and result['conflicts']
    assert 'حدّده' in cm.summary_ar(result)


def test_staff_wording():
    assert cm.normalize('ترانزيت إلى قطر') == 'transit' and cm.normalize('عبور') == 'transit'
    assert cm.normalize('استيراد') == 'import' and cm.normalize('') == ''
    assert cm.country_of('ترانزيت إلى قطر') == 'QA'
    assert cm.country_of('Amman, Jordan') == 'JO' and cm.country_of('عمان الاردن') == 'JO'
