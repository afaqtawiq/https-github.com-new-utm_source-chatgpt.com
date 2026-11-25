"""Settlement of an amount received against the original receipts and invoices (no model, no DB)."""
from app import advance_reconcile as ar


def f(i, check, digest=None):
    return {'id': i, 'name': f'file{i}.jpg', 'digest': digest or f'd{i}', 'check': check}


def chk(kind, amount, ref='', currency='SAR', pays=(), sadad='', issuer='X'):
    return ar.clean_check({'kind': kind, 'amount': amount, 'reference': ref, 'currency': currency, 'pays_refs': list(pays),
                           'sadad_bill': sadad, 'issuer': issuer})


def case():
    return [
        f(1, chk('service_invoice', 10000, ref='INV-٥٥١٢٣')),                     # paid by receipt 2 (reference, Arabic digits)
        f(2, chk('payment_receipt', 10000, ref='R1', pays=['inv 55123'])),
        f(3, chk('customs_fees', 7350.5, ref='D-1', sadad='9001234567')),          # paid by SADAD receipt 4 (same bill)
        f(4, chk('payment_receipt', 7350.5, ref='S1', sadad='9001234567')),
        f(5, chk('service_invoice', 4000, ref='INV-77777')),                      # partly paid: 2500 by receipt 6
        f(6, chk('payment_receipt', 2500, ref='R3', pays=['77777'])),
        f(7, chk('service_invoice', 1200, ref='INV-88888')),                      # no receipt → unpaid
        f(8, chk('payment_receipt', 900, ref='R4')),                              # receipt with no invoice → still paid
        f(9, chk('payment_receipt', 10000, ref='R1', pays=['inv 55123']), digest='d2'),  # same file again → duplicate
        f(10, chk('goods_invoice', 30000, currency='USD')),                       # supplier goods → apart
    ]


def test_three_numbers_final():
    r = ar.reconcile(case(), 41000)
    assert r['paid'] == 20750.5            # 10000 + 7350.5 + 2500 + 900, the duplicate not counted
    assert r['remaining'] == 20249.5
    assert r['unpaid_total'] == 2700       # 1500 left on INV-77777 + 1200 INV-88888
    assert [i['reference'] for i in r['unpaid']] == ['INV-77777', 'INV-88888']
    assert not r['provisional'] and r['duplicates'] == [('file9.jpg', 'file2.jpg')] and len(r['goods']) == 1
    inv1 = r['invoices'][0]
    assert inv1['paid_by'] == [('file2.jpg', 10000, 'بالمرجع')]


def test_missing_and_unclear_currency_make_it_provisional_and_named():
    files = case() + [f(11, chk('payment_receipt', 500, currency='')), f(12, {'error': 'ملف تالف'}),
                      f(13, chk('service_invoice', 300, currency='AED')), f(14, chk('payment_receipt', None))]
    r = ar.reconcile(files, 41000)
    assert r['provisional'] and r['paid'] == 20750.5   # nothing unclear is counted
    names = [n for n, _ in r['missing']]
    assert names == ['file11.jpg', 'file12.jpg', 'file13.jpg', 'file14.jpg']
    text = ar.summary_text(r)
    assert '⚠️ مبدئية' in text and 'file11.jpg: العملة غير واضحة' in text and 'file13.jpg: بعملة AED' in text


def test_amount_only_match_never_settles():
    files = [f(1, chk('service_invoice', 1500, ref='INV-1')), f(2, chk('payment_receipt', 1500, ref='R9'))]
    r = ar.reconcile(files, 5000)
    assert r['paid'] == 1500 and r['unpaid_total'] == 1500 and r['provisional']
    assert r['invoices'][0]['suggested'] == ['file2.jpg'] and 'تأكيد المحاسب' in r['reasons'][0]


def test_receipt_paying_more_than_invoice_counts_once():
    files = [f(1, chk('service_invoice', 1000, ref='A-12345')), f(2, chk('payment_receipt', 1200, pays=['A-12345']))]
    r = ar.reconcile(files, 2000)
    assert r['paid'] == 1200 and r['unpaid_total'] == 0 and r['remaining'] == 800


def test_pdf_builds():
    r = ar.reconcile(case() + [f(11, chk('payment_receipt', 500, currency=''))], 41000)
    assert ar.pdf(r, 'المدير', '2026-11-25').startswith(b'%PDF')
