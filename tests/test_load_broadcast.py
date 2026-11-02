import importlib.util, pathlib, sys, types
from unittest.mock import Mock, patch
_storage = types.ModuleType('app.storage'); _storage.db = Mock(side_effect=AssertionError('db')); _storage.utcnow = Mock()
with patch.dict(sys.modules, {'app.storage': _storage}):
    _spec = importlib.util.spec_from_file_location('_lb', pathlib.Path(__file__).resolve().parents[1] / 'app' / 'load_broadcast.py')
    lb = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(lb)


def test_message_matches_approved_template():
    from app.zernio_whatsapp import required_templates, template_parameters
    template = next(t for t in required_templates() if t['name'] == 'afaaq_transport_driver_offer_v1_ar')
    load, missing = lb.normalize({'origin': 'جدة', 'destination': 'الرياض', 'weight': '25', 'driver_price': '4350', 'payment': 'نقدًا'})
    assert not missing
    params = template_parameters(template, lb.message('AFT-7', load))
    assert params and 'AFT-7' in params[0] if isinstance(params, list) else params


def test_missing_fields():
    _, missing = lb.normalize({'origin': 'جدة'})
    assert 'الوجهة' in missing and 'سعر السائق' in missing
