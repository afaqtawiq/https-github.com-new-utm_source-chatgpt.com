"""Server-rendered document inventory and review controls."""
from app.fasah_fields import DOCUMENT_TYPES
from app.fasah_checklist import (PROFILE_OPTIONS, REQUIREMENTS, STATES, IMPORT_SOURCE,
    checklist, profile_of, detected_kinds, suggested_kind, classification_issue, document_flags)


def options(choices, selected, esc):
    return ''.join(f'<option value="{esc(key)}" {"selected" if key == selected else ""}>{esc(label)}</option>' for key, label in choices.items())


def reason_inputs(esc, value=None, required=True):
    value = value or {}
    attributes = 'required minlength="5"' if required else ''
    return f'''<label>سبب القرار لهذه المعاملة<input name="reason" maxlength="500" value="{esc(value.get('reason', ''))}" {attributes}></label>
    <label>مرجع التحقق (جهة / تعليمات / مستند وتاريخه)<input name="source" maxlength="300" value="{esc(value.get('source', ''))}" {attributes}></label>'''


def extra_form(case, hidden, esc, extra=None):
    extra = extra or {}
    file_options = {'': 'لم يرفع مستند يغطي المتطلب', **{d['id']: d['name'] for d in case['documents']}}
    return f'''<form method="post" action="/fasah-workspace/{case['id']}/extra-requirements">{hidden}
    <input type="hidden" name="extra_id" value="{esc(extra.get('id', ''))}">
    <label>اسم الشهادة أو التصريح المحدد<input name="label" value="{esc(extra.get('label', ''))}" maxlength="120" required></label>
    <label>انطباقه<select name="choice">{options({'required':'مطلوب', 'not_required':'غير مطلوب لهذه المعاملة'}, 'required' if extra.get('required', True) else 'not_required', esc)}</select></label>
    <label>الملف الذي يغطي هذا المتطلب<select name="document_id">{options(file_options, extra.get('document_id', ''), esc)}</select></label>
    {reason_inputs(esc, extra)}<button class="btn">حفظ المتطلب</button></form>'''


def document_panel(case, hidden, esc):
    context, docs = case['context'], case['documents']
    result = checklist(docs, context)
    root = f'/fasah-workspace/{case["id"]}'
    body = '<section id="document-check"><div class="card"><h2>المستندات المرفوعة وفحص الاكتمال</h2>'
    body += f'<div class="doc-counts"><div><strong>{len(docs)}</strong><span>ملفات مرفوعة</span></div>'
    for key, label in STATES.items():
        body += f'<div class="doc-state-{key}"><strong>{result["counts"][key]}</strong><span>{label}</span></div>'
    body += f'''</div><form method="post" action="{root}/check">{hidden}<button class="btn">فحص اكتمال المستندات</button></form>
    <p>المرفوع يعني أن الملف وصل. مكتمل يعني أن متطلبه حُدد وأن المستند روجع؛ لا يعني اعتماد المعاملة في فسح.</p>'''
    if context.get('checked_at'):
        body += '<p role="status">تم فحص المستندات الحالية. وقت الفحص: <bdi>' + esc(context['checked_at']) + '</bdi></p>'
    if result['complete']:
        body += '<p class="good">اكتملت قائمة المستندات الداخلية وفق نطاق المراجعة المسجل. راجع الحقول والبنود قبل الإدخال.</p>'
    else:
        body += '<p class="warn">لم يكتمل فحص متطلبات المعاملة بعد. راجع الناقص والتنبيهات أدناه.</p>'
    body += '</div><div class="card"><h3>ما الذي رُفع؟</h3><div class="scroll"><table class="doc-table"><thead><tr><th>الملف</th><th>النوع المسجل / محتواه</th><th>الصفحات</th><th>المراجعة والتصحيح</th></tr></thead><tbody>'
    for doc in docs:
        evidence = detected_kinds(doc)
        hint = suggested_kind(doc)
        notes = document_flags(doc)
        if classification_issue(doc):
            notes.append('اختلاف في التصنيف؛ النوع المقترح للمراجعة: ' + DOCUMENT_TYPES[hint])
        if doc.get('candidate_count', 0) == 0:
            notes.append('لم تستخرج حقول؛ هذا لا يعني أن الملف غير مرفوع.')
        review_text = 'تمت مراجعة الأصل' if doc.get('reviewed') and doc.get('classification_confirmed') and not document_flags(doc) and not classification_issue(doc) else 'يحتاج مراجعة'
        content = ''.join('<p>ظهر بالنص: ' + esc(DOCUMENT_TYPES[key]) + ' — صفحة ' + esc('، '.join(map(str, pages))) + '</p>' for key, pages in evidence.items())
        notes_html = ''.join('<p class="warn">' + esc(n) + '</p>' for n in notes)
        covers = ''.join(f'<label class="review"><input type="checkbox" name="covers_{key}" value="yes" {"checked" if key in doc.get("covers", []) else ""}>{esc(label)}</label>' for key, label in REQUIREMENTS.items())
        body += f'''<tr><td><b>مرفوع</b><br><a href="#doc-{esc(doc['id'])}">{esc(doc['name'])}</a></td>
        <td>{esc(DOCUMENT_TYPES[doc['kind']])}{content}</td><td>{len(doc['pages'])}</td><td>{review_text}{notes_html}
        <details><summary>تصحيح النوع ومراجعة المستند</summary><form method="post" action="{root}/documents/{esc(doc['id'])}/review">{hidden}
        <label>النوع الأساسي بعد مطابقة الأصل<select name="kind">{options(DOCUMENT_TYPES, doc['kind'], esc)}</select></label>
        <details><summary>الملف يتضمن أكثر من مستند (مثل فاتورة داخل شهادة منشأ)</summary>{covers}</details>
        <label class="review"><input type="checkbox" name="reviewed" value="yes" {"checked" if doc.get('reviewed') else ""}>راجعت الأصل واكتمال صفحاته وصحته وانتماءه لهذه المعاملة وجميع الأنواع المحددة</label>
        <label>ملاحظة المراجعة<input name="note" maxlength="500" value="{esc(doc.get('review_note', ''))}"></label>
        <button class="btn">حفظ التصنيف والمراجعة</button></form></details></td></tr>'''
    body += ('<tr><td colspan="4">لم ترفع ملفات بعد.</td></tr>' if not docs else '') + '</tbody></table></div></div>'
    profile = profile_of(context)
    body += f'<div class="card"><h3>بيانات تحديد المستندات المطلوبة</h3><p>لا نفترض قائمة موحدة؛ إذا لم تُحسم معلومة تظهر «يحتاج مراجعة».</p><form method="post" action="{root}/profile">{hidden}<div class="profile-grid">'
    for key, (label, choices) in PROFILE_OPTIONS.items():
        body += f'<label>{esc(label)}<select name="{key}">{options(choices, profile[key], esc)}</select></label>'
    body += f'''<label>بلد الإرسال (ليس بلد منشأ الأصناف)<input name="dispatch_country" maxlength="120" value="{esc(profile['dispatch_country'])}"></label>
    <label>وصف جميع أصناف الشحنة<textarea name="goods" maxlength="500">{esc(profile['goods'])}</textarea></label></div>
    <button class="btn">حفظ بيانات المعاملة</button><p class="muted">تغيير هذه البيانات يعيد قرارات المتطلبات واشتراطات البضاعة السابقة للمراجعة.</p></form></div>'''
    body += '<div class="card"><h3>ما المطلوب وما الناقص؟</h3>'
    body += ''.join('<p class="warn">' + esc(blocker) + '</p>' for blocker in result['blockers'])
    body += '<div class="scroll"><table class="doc-table"><thead><tr><th>المستند / المتطلب</th><th>هل رُفع؟</th><th>الحالة</th><th>السبب وما يلزم</th></tr></thead><tbody>'
    for row in result['rows']:
        state = row['state']
        files = '<br>'.join(f'<a href="#doc-{esc(d["id"])}">{esc(d["name"])}</a>' for d in row['documents']) or 'لم يُرفع'
        action = {'missing': 'أضف المستند المطلوب من نموذج الرفع أدناه.', 'review': 'احسم سبب الطلب، والتصنيف، ومراجعة الأصل بحسب التنبيه.', 'complete': 'المستند مرفوع وتمت مراجعته داخليًا.', 'not_required': 'لا يلزم رفعه وفق السبب المسجل لهذه المعاملة.'}[state]
        source = f'<a href="{IMPORT_SOURCE}" target="_blank" rel="noopener noreferrer">إرشادات زاتكا للاستيراد — تحققت القاعدة في 2026-09-24</a>' if row['source'] == IMPORT_SOURCE else esc(row['source'])
        body += f'<tr><td>{esc(row["label"])}</td><td>{files}</td><td><span class="doc-badge doc-state-{state}">{STATES[state]}</span></td><td>{esc(row["reason"])}<p>{source}</p><p>{action}</p>'
        if row.get('extra'):
            extra = next(e for e in context['extras'] if e['id'] == row['key'])
            body += '<details><summary>تعديل المتطلب وربط المستند</summary>' + extra_form(case, hidden, esc, extra) + '</details>'
        else:
            decision = context.get('decisions', {}).get(row['key'], {})
            body += f'''<details><summary>تحديد المتطلب بعد مراجعة المختص</summary><form method="post" action="{root}/requirements/{row['key']}">{hidden}
            <label>القرار<select name="choice">{options({'auto':'حسب قواعد المعاملة', 'required':'مطلوب', 'not_required':'غير مطلوب', 'review':'يحتاج مراجعة'}, decision.get('choice', 'auto'), esc)}</select></label>
            {reason_inputs(esc, decision, required=False)}<button class="btn">حفظ قرار المتطلب</button></form></details>'''
        body += '</td></tr>'
    body += '</tbody></table></div><details><summary>إضافة شهادة أو تصريح مطلوب بحسب البضاعة</summary>' + extra_form(case, hidden, esc) + '</details>'
    scope = context.get('scope_review', {})
    body += f'''<details><summary>مراجعة اشتراطات جميع أصناف البضاعة</summary><p>أضف كل شهادة أو تصريح خاص باسم مستقل، ثم وثق مراجعة نطاق المتطلبات.</p><form method="post" action="{root}/scope-review">{hidden}
    {reason_inputs(esc, scope)}<label class="review"><input type="checkbox" name="confirmed" value="yes" required>راجعت اشتراطات جميع الأصناف وأدرجت كل المستندات المطلوبة</label><button class="btn">تسجيل مراجعة الاشتراطات</button></form></details></div></section>'''
    body += '''<style>.doc-counts{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}.doc-counts>div{border:1px solid var(--line);border-radius:12px;padding:14px;min-width:110px}.doc-counts strong{font-size:28px;display:block}.doc-counts span{display:block}.doc-badge{display:inline-block;padding:6px 10px;border-radius:8px;font-weight:700;white-space:nowrap}.doc-state-complete{background:#e6f4ea!important;color:#135c31!important}.doc-state-missing{background:#fff0ed!important;color:#9b231a!important}.doc-state-review{background:#fff5d9!important;color:#684900!important}.doc-state-not_required{background:#edf0f5!important;color:#374151!important}.doc-table{width:100%;min-width:760px}.doc-table td{vertical-align:top;white-space:normal;overflow-wrap:anywhere}.doc-table td:first-child{min-width:150px}.doc-table td:last-child{min-width:290px}.doc-table form{min-width:270px}.doc-table details{max-width:460px}.profile-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}#document-check{scroll-margin-top:24px}#document-check a{color:var(--gold2);text-decoration:underline}#document-check .warn{color:#b45309}#document-check label{display:block;margin:10px 0}#document-check input[type=checkbox]{width:auto}#document-check .scroll{overflow-x:auto}</style>'''
    return body
