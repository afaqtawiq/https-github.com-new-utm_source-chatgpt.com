"""10 de-identified clearance cases, one port (Jeddah Islamic Port), shaped like the real tables
(shipment_files, fasah_status, shipment_tracks, container_returns, staff_documents). Customers, bills, declarations and
containers are replaced by neutral labels; no real person, company, phone or reference appears here.
Clock of the pilot: 25/11/2026 09:00 Riyadh; last successful FASAH list read 08:30."""
import datetime as dt

R = dt.timezone(dt.timedelta(hours=3))
NOW = dt.datetime(2026, 11, 25, 9, 0, tzinfo=R)
LAST_READ = dt.datetime(2026, 11, 25, 8, 30, tzinfo=R)
PORT = 'ميناء جدة الإسلامي'


def t(day, hour=8, minute=30):
    return dt.datetime(2026, 11, day, hour, minute, tzinfo=R)


# bill, customer label, team stage, declaration no., containers
FILES = [
    ('ANONBL001', 'عميل أ', 'released', '700101', ['ANUU1000011', 'ANUU1000012']),
    ('ANONBL002', 'عميل ب', 'duties', '700102', ['ANUU1000021']),
    ('ANONBL003', 'عميل ج', 'inspection', '700103', ['ANUU1000031']),
    ('ANONBL004', 'عميل د', 'declared', '700104', ['ANUU1000041']),       # stale FASAH status
    ('ANONBL005', 'عميل هـ', 'declared', '700105', ['ANUU1000051']),
    ('ANONBL006', 'عميل و', 'arrived', '', ['ANUU1000061']),
    ('ANONBL007', 'عميل ز', 'delivered', '700107', ['ANUU1000071']),
    ('ANONBL008', 'عميل ح', 'delivered', '700108', ['ANUU1000081']),
    ('ANONBL009', 'عميل ط', 'returned', '700109', ['ANUU1000091']),
    ('ANONBL010', 'عميل ي', 'released', '700110', ['ANUU1000101']),
]
# declaration, ref (bill), stage, FASAH text, seen_at, changed_at, duties_since
FASAH = [
    ('700101', 'ANONBL001', 'released', 'جاهز لطباعة اشعار الفسح', t(25), t(24, 14), None),
    ('700102', 'ANONBL002', 'duties_due', 'بانتظار تحصيل الرسوم', t(25), t(24, 10), t(24, 10)),
    ('700103', 'ANONBL003', 'inspection', 'تحويل للكشف', t(25), t(25, 6), None),
    ('700104', 'ANONBL004', 'under_review', 'تحت المعالجة', t(22, 11), t(21, 16), None),   # last seen 3 days ago
    ('700105', 'ANONBL005', 'not_arrived', 'لم يصل الى المنفذ', t(25), t(23, 9), None),
    ('700107', 'ANONBL007', 'released', 'فسح كلي', t(25), t(20, 9), None),
    ('700108', 'ANONBL008', 'released', 'فسح كلي', t(25), t(21, 9), None),
    ('700109', 'ANONBL009', 'released', 'فسح كلي', t(25), t(15, 9), None),
    ('700110', 'ANONBL010', 'released', 'جاهز لطباعة اشعار الفسح', t(25), t(25, 7), None),
]
# bill, arrived, eta, checked_at
TRACKS = [
    ('ANONBL004', True, t(21, 6, 0), t(24, 20, 0)),
    ('ANONBL005', False, t(27, 18, 0), t(25, 7, 0)),
    ('ANONBL006', True, t(23, 22, 0), t(24, 9, 0)),
]
# container, bill, free_until, estimated?, delivered_on, status
CONTAINERS = [
    ('ANUU1000011', 'ANONBL001', dt.date(2026, 11, 26), False, None, 'open'),
    ('ANUU1000012', 'ANONBL001', dt.date(2026, 11, 26), False, None, 'open'),
    ('ANUU1000071', 'ANONBL007', dt.date(2026, 11, 24), False, dt.date(2026, 11, 22), 'delivered'),
    ('ANUU1000081', 'ANONBL008', dt.date(2026, 11, 25), True, dt.date(2026, 11, 23), 'delivered'),
    ('ANUU1000091', 'ANONBL009', dt.date(2026, 11, 20), False, dt.date(2026, 11, 17), 'returned'),
    ('ANUU1000101', 'ANONBL010', dt.date(2026, 11, 30), False, None, 'open'),
]
# WhatsApp documents (staff_documents.fields as read by the agent)
DOCS = [
    ('اشعار-وصول-A.pdf', {'document_kind': 'shipping_document', 'bill_no': 'ANON-BL-001'}),                  # → ANONBL001
    ('صورة-فاتورة.jpg', {'document_kind': 'invoice', 'goods': 'قطع غيار'}),                                   # no reference
    ('بيان-مختلط.pdf', {'document_kind': 'customs', 'bill_no': 'ANONBL003', 'container_numbers': ['ANUU1000101']}),  # 003 vs 010
    ('اشعار-فسح.pdf', {'document_kind': 'customs', 'declaration_number': '700102'}),                         # → ANONBL002
]
