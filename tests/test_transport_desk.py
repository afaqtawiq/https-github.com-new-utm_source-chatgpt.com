import importlib.util, json, pathlib, sys, types
from unittest.mock import Mock, patch
_storage = types.ModuleType('app.storage'); _storage.db = Mock(side_effect=AssertionError('db')); _storage.utcnow = Mock()
with patch.dict(sys.modules, {'app.storage': _storage}):
    _spec = importlib.util.spec_from_file_location('_td', pathlib.Path(__file__).resolve().parents[1] / 'app' / 'transport_desk.py')
    td = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(td)


def test_phone_forms():
    assert td.digits('0505810826') == '966505810826'
    assert td.digits('+966 50 581 0826') == '966505810826'
    assert td.phones_in('رقمه ٠٥٠٥٨١٠٨٢٦ والثاني 0530130435') == ['966505810826', '966530130435']


def test_phone_message_only_bare_numbers():
    assert td.phone_message('0505810826') == '966505810826'
    assert td.phone_message('رقم صاحب الحمولة: +966505810826') == '966505810826'
    assert td.phone_message('حول 500 ريال للرقم 0505810826 بكرة') is None
    assert td.phone_message('0505810826 0530130435') is None


def test_listing_seed_from_vision_record():
    load = {'weight_tons': 25.0, 'vehicle_type': 'سطحة', 'distance_km': 960,
            'description': 'البضاعة: حاوية 40\nالسعر المعروض: 3,500 ريال', 'raw_text': json.dumps({'payment': 'كاش عند التنزيل'})}
    seed = td.listing(load)
    assert seed['weight'] == '25' and seed['vehicle'] == 'سطحة' and seed['goods'] == 'حاوية 40'
    assert seed['price'].startswith('3,500') and seed['payment'] == 'كاش عند التنزيل'


def test_link_messages_share_both_contacts():
    b = {'id': 7, 'origin': 'رابغ', 'destination': 'الرياض', 'driver_price': '3,200.00', 'payment': 'كاش'}
    driver = {'phone': '966551234567', 'driver_name': 'أحمد', 'vehicle_type': 'سطحة'}
    negotiation = {'phone': '966505810826', 'fields': json.dumps({'loading_point': 'خارج الميناء', 'loading_date': 'الخميس'})}
    to_driver, to_owner = td.link_messages(b, driver, negotiation)
    assert 'AFT-7' in to_driver and '+966505810826' in to_driver and 'خارج الميناء' in to_driver
    assert '+966551234567' in to_owner and 'أحمد' in to_owner and 'سطحة' in to_owner
    assert td.link_messages(b, driver, None)[1] is None


def test_driver_accept_ignores_unrelated_text():
    assert td.driver_accept('966551234567', 'السلام عليكم') is None
    assert td.driver_accept('966551234567', 'AFT-7') is None  # no acceptance word
