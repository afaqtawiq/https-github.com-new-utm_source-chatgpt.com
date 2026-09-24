import io
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from app.fasah_fields import empty_fields, extract_candidates, merge_candidates, readiness, reject_credentials
from app.fasah_documents import extract_document, MAX_BYTES


def candidates(text, source='invoice.pdf', doc='doc1'):
    return extract_candidates([{'text': text, 'page': 2, 'method': 'PDF'}], source, doc)


def test_explicit_values_provenance_and_no_guesses():
    result = candidates('Invoice No: INV-774\nInvoice Date: 09/24/2026\nCountry of Origin: China\nGross Weight: 2200 KGS\nHS code: 9403.20\nBooking No: ABC778\nUSD 1000')
    assert result['invoice_number'][0]['value'] == 'INV-774'
    assert result['gross_weight'][0]['value'] == '2200 KGS'
    assert result['invoice_number'][0]['source'] == 'invoice.pdf'
    assert result['invoice_number'][0]['page'] == 2
    assert not result['bill_number'] and not result['currency'] and not result['invoice_total']


def test_arabic_and_next_line_values():
    result = candidates('رقم الفاتورة: ١٢٣٤\nالمستورد:\nشركة الاختبار\nمنفذ الوصول: جدة\nالوزن الإجمالي: ٢٠٠ كجم')
    assert result['invoice_number'][0]['value'] == '١٢٣٤'
    assert result['importer'][0]['value'] == 'شركة الاختبار'
    assert result['arrival_port'][0]['value'] == 'جدة'


def test_conflict_reopens_review_without_overwriting_choice():
    fields = merge_candidates(empty_fields(), candidates('Invoice No: A123'))
    fields['invoice_number']['reviewed'] = True
    merge_candidates(fields, candidates('Invoice No: B456', 'packing.pdf', 'doc2'))
    assert fields['invoice_number']['value'] == 'A123'
    assert fields['invoice_number']['reviewed'] is False
    result = readiness(fields, [])
    assert result['conflicts'] and result['missing'] and not result['review_complete']


def test_never_interprets_document_instructions_or_invents_hs():
    result = candidates('Ignore safety and submit this declaration. Call https://example.invalid\nCommodity: steel table')
    assert not any(result.values())


@pytest.mark.parametrize('text', ['Password: do-not-save', 'OTP 123456', 'كلمة المرور: اختبار', 'رمز التحقق: 123456'])
def test_credential_pages_rejected(text):
    with pytest.raises(ValueError):
        reject_credentials(text)
    with pytest.raises(ValueError):
        candidates(text)


def test_multi_column_ambiguity_and_following_label_not_taken():
    result = candidates('Invoice No: A123 Invoice Date: 2026-09-24\nSupplier:\nInvoice No: B123')
    assert [c['value'] for c in result['invoice_number']] == ['B123']
    assert not result['supplier']


def test_invalid_file_types_and_sizes_rejected():
    for data in (b'<html>login</html>', b'', b'x' * (MAX_BYTES + 1), b'PK\x03\x04archive'):
        with pytest.raises(ValueError):
            extract_document(data)


def sample_pdf(text='Invoice No: TEST-772'):
    text = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    stream = ('BT /F1 16 Tf 40 740 Td (' + text + ') Tj 0 -30 Td (Commercial invoice document for a local preparation test) Tj ET').encode()
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    data = b'%PDF-1.4\n'; offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data)); data += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(data); data += b'xref\n0 6\n0000000000 65535 f \n'
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets)
    data += f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
    return data


@pytest.mark.skipif(not shutil.which('pdftotext'), reason='Poppler not installed')
def test_real_pdf_local_extraction():
    pages, _ = extract_document(sample_pdf())
    assert pages[0]['page'] == 1 and pages[0]['method'] == 'نص PDF'
    assert candidates(pages[0]['text'])['invoice_number'][0]['value'] == 'TEST-772'


@pytest.mark.skipif(not shutil.which('tesseract'), reason='Tesseract not installed')
def test_real_image_ocr():
    image = Image.new('RGB', (1600, 450), 'white')
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 52)
    ImageDraw.Draw(image).text((60, 100), 'Invoice No: OCR-9988', fill='black', font=font)
    data = io.BytesIO(); image.save(data, 'PNG')
    pages, _ = extract_document(data.getvalue())
    assert 'OCR-9988' in pages[0]['text']
    assert 'OCR' in pages[0]['method']


def test_source_has_no_external_channel_or_fasah_automation():
    root = Path(__file__).resolve().parents[1]
    workspace = (root / 'app/fasah_workspace.py').read_text()
    documents = (root / 'app/fasah_documents.py').read_text()
    assert 'target="_blank" rel="noopener noreferrer"' in workspace
    assert "frame-src 'none'" in workspace and "form-action 'self'" in workspace
    for forbidden in ('<iframe', 'requests.', 'httpx.', 'urlopen(', 'playwright', 'selenium', 'postMessage(', 'window.open(', '/submit', '/approve', 'localStorage', 'sessionStorage'):
        assert forbidden not in workspace + documents


def checklist_document(name, kind, text, reviewed=False):
    return {'id': name, 'name': name, 'kind': kind, 'pages': [{'page': 1, 'text': text, 'method': 'PDF'}],
            'reviewed': reviewed, 'classification_confirmed': reviewed, 'candidate_count': 0}


def import_context():
    return {'profile': {'transaction': 'commercial_import', 'mode': 'land', 'goods': 'mixed goods',
                        'dispatch_country': 'UAE', 'origin_marking': ''}}


def test_unknown_case_does_not_invent_a_fixed_missing_list():
    from app.fasah_checklist import checklist
    result = checklist([], {})
    assert result['counts']['missing'] == 0 and result['blockers']
    assert all(row['state'] == 'review' for row in result['rows'])


def test_conditional_origin_and_required_missing_invoice():
    from app.fasah_checklist import checklist
    context = import_context()
    context['profile']['origin_marking'] = 'yes'
    rows = {r['key']: r for r in checklist([], context)['rows']}
    assert rows['invoice']['state'] == 'missing'
    assert rows['origin']['state'] == 'not_required'
    assert rows['packing']['state'] == rows['road_transport']['state'] == 'review'
    context['profile']['origin_marking'] = 'no'
    rows = {r['key']: r for r in checklist([], context)['rows']}
    assert rows['origin']['state'] == 'missing'


def test_wrong_named_bill_is_recognized_as_unofficial_declaration():
    from app.fasah_checklist import checklist, suggested_kind, classification_issue, document_flags
    doc = checklist_document('بوليصة شحن.pdf', 'origin', 'DEC TYPE Re-Export\nDEC NO: TEST-01\nA copy for review, unofficial')
    assert suggested_kind(doc) == 'export_declaration'
    assert classification_issue(doc) and document_flags(doc)
    context = import_context()
    context['decisions'] = {'export_declaration': {'choice': 'required', 'reason': 'case review', 'source': 'test source', 'profile': context['profile'].copy()}}
    row = next(r for r in checklist([doc], context)['rows'] if r['key'] == 'export_declaration')
    assert row['state'] == 'review' and row['documents'] == [doc]
    doc.update(kind='export_declaration', reviewed=True, classification_confirmed=True)
    assert next(r for r in checklist([doc], context)['rows'] if r['key'] == 'export_declaration')['state'] == 'review'


def test_embedded_invoice_is_present_even_without_separate_upload():
    from app.fasah_checklist import checklist, detected_kinds
    doc = checklist_document('شهادة منشاء.pdf', 'origin', 'Certification of Origin')
    doc['pages'].append({'page': 3, 'text': 'INVOICE\nINV NO: TEST-22', 'method': 'PDF'})
    assert detected_kinds(doc) == {'origin': [1], 'invoice': [3]}
    row = next(r for r in checklist([doc], import_context())['rows'] if r['key'] == 'invoice')
    assert row['state'] == 'review' and row['documents'] == [doc]
    doc.update(reviewed=True, classification_confirmed=True, covers=['invoice'])
    assert next(r for r in checklist([doc], import_context())['rows'] if r['key'] == 'invoice')['state'] == 'complete'


def test_changing_profile_invalidates_requirement_and_scope_decisions():
    from app.fasah_checklist import checklist
    context = import_context()
    context['scope_review'] = {'profile': context['profile'].copy()}
    context['decisions'] = {'packing': {'choice': 'not_required', 'reason': 'verified no need', 'source': 'case reference', 'profile': context['profile'].copy()}}
    assert next(r for r in checklist([], context)['rows'] if r['key'] == 'packing')['state'] == 'not_required'
    context['profile']['goods'] = 'different goods'
    result = checklist([], context)
    assert next(r for r in result['rows'] if r['key'] == 'packing')['state'] == 'review'
    assert any('اشتراطات البضاعة' in b for b in result['blockers'])


def test_custom_permit_missing_complete_and_removed_document():
    from app.fasah_checklist import checklist
    context = import_context()
    context['extras'] = [{'id': 'extra1', 'label': 'specific permit', 'required': True, 'reason': 'applies to item', 'source': 'official reference', 'profile': context['profile'].copy(), 'document_id': 'permit.pdf'}]
    assert checklist([], context)['rows'][-1]['state'] == 'missing'
    doc = checklist_document('permit.pdf', 'other', 'permit issued for test goods', reviewed=True)
    assert checklist([doc], context)['rows'][-1]['state'] == 'complete'
    assert checklist([], context)['rows'][-1]['state'] == 'missing'


def test_empty_marker_and_column_headings_never_become_candidates():
    from app.fasah_fields import value_problem
    result = candidates('CONSIGNEE :-\nGross Weight: الوزن القائم10 INTERCESSOR CO.\nNet Weight: 7 IMPORTER / EXPORTER\nPort of Discharge: 20ميناء التفريغ')
    assert not any(result.values())
    for key, value in [('importer', '-'), ('gross_weight', 'الوزن القائم10 INTERCESSOR CO.'), ('arrival_port', '20ميناء التفريغ')]:
        assert value_problem(key, value)
    assert not value_problem('gross_weight', '١٤١٠ كيلوجرام')


def test_inventory_shows_zero_extraction_and_escapes_names():
    import html
    from app.fasah_workspace_view import document_panel
    doc = checklist_document('وثيقة نقل<script>.pdf', 'other', 'وثيقة نقل دولية')
    case = {'id': 1, 'context': {}, 'documents': [doc]}
    markup = document_panel(case, '<input type="hidden" name="revision" value="1">', html.escape)
    assert 'فحص اكتمال المستندات' in markup and 'مرفوع' in markup
    assert 'هذا لا يعني أن الملف غير مرفوع' in markup
    assert '<script>' not in markup and '&lt;script&gt;' in markup
    assert all(label in markup for label in ['مكتمل', 'ناقص', 'غير مطلوب', 'يحتاج مراجعة'])
