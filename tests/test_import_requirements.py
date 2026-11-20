import asyncio

from app import import_requirements as ir


def test_render_leads_with_blockers_and_ends_with_message():
    tariff = [{'code': '250810000001', 'desc_ar': 'بنتونيت منتفخ', 'duty': '5%'}]
    saber = {'250810000001': {'status': 'no_results', 'results': []}}
    found = {'blockers': ['المورد مصنع سعودي'], 'hs_code': '250810000001', 'duty': '5%',
             'authorities': [{'name': 'هيئة المواصفات', 'requirement': 'إقرار ذاتي', 'source': 'https://saber.sa'}],
             'documents': ['فاتورة تجارية'], 'unverified': ['متطلب إضافي'], 'questions_for_customer': ['بلد المنشأ؟'],
             'customer_message': 'أهلًا — فريق آفاق طويق — 0507665873'}
    text = ir.render('بنتونيت', tariff, saber, found)
    assert text.index('قبل أي شيء') < text.index('سابر') < text.index('رسالة جاهزة')
    assert '25 08 10 00 00 01' in text and 'عدم الظهور ليس إعفاءً' in text and 'غير متحقق' in text


def test_without_research(monkeypatch):
    monkeypatch.setattr(ir, 'enabled', lambda: False)
    monkeypatch.setattr(ir, 'tariff_candidates', lambda *a: [{'code': '250810000001', 'desc_ar': 'بنتونيت', 'duty': '5%'}])
    async def fake(codes):
        return {c: {'status': 'unavailable'} for c in codes}
    monkeypatch.setattr(ir, 'saber_for', fake)
    text = asyncio.run(ir.requirements('بنتونيت'))
    assert 'لم يكتمل' in text and 'تعذر الوصول لسابر' in text
    assert asyncio.run(ir.requirements('')) == 'اكتب اسم المادة أو وصفها.'
