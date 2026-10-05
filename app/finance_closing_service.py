"""Audited draft-only month close inputs. No posting, transfer or external send."""
from calendar import monthrange
from datetime import date
import re
from psycopg.types.json import Jsonb
from app.storage import db, utcnow
from app import finance_core as core, finance_service as ledger
from app import finance_closing_core as closing

AMOUNTS = ('shared_service_income_minor','agency_only_income_minor','saber_revenue_minor','tax_reserve_minor',
           'pass_through_minor','goods_value_minor','shared_actual_cost_minor','agency_only_actual_cost_minor')


def month_dates(month):
    if not isinstance(month,str) or not re.fullmatch(r'\d{4}-\d{2}',month):
        raise ValueError('حدد الشهر بصيغة YYYY-MM')
    start = date.fromisoformat(month+'-01')
    return start,date(start.year,start.month,monthrange(start.year,start.month)[1])


def _revision(raw):
    text = core.clean(raw,19,True)
    if not text.isascii() or not text.isdigit() or int(text)>9223372036854775807:
        raise ValueError('نسخة المراجعة غير صالحة')
    return int(text)


def _detail_issues(mapping,detail):
    issues=[]
    components=detail['components']
    for field,value,label in (
        ('tax_reserve_minor',components['tax'],'احتياطي الضريبة'),
        ('saber_revenue_minor',components['saber'],'إيراد سابر الخاص بالوكالة'),
        ('goods_value_minor',detail['goods_value_minor'],'قيمة البضاعة المعلوماتية')):
        if mapping.get(field) is not None and mapping[field]!=value:
            issues.append(label+' لا يطابق التفصيل المعتمد للمطالبة')
    customs=components['customs_duty']+components['customs_other']
    if mapping.get('pass_through_minor') is not None and mapping['pass_through_minor']<customs:
        issues.append('الرسوم الجمركية الموثقة يجب أن تبقى ضمن المبالغ المحصلة للغير')
    return issues


def _data(c,owner_id,month):
    start,end = month_dates(month)
    owner = ledger.identity(c,owner_id)
    docs = c.execute('''SELECT d.id document_id,d.kind,d.currency,d.amount_minor,d.document_date,d.status,
      d.counterparty_id,p.name counterparty_name,d.invoice_ref,d.customs_ref,d.reversed_at,
      x.id mapping_revision,x.mapping,y.id claim_detail_revision,y.components claim_components,y.goods_value_minor claim_goods_value_minor
      FROM finance_documents d JOIN finance_party_display p ON p.id=d.counterparty_id
      LEFT JOIN LATERAL (SELECT id,mapping FROM finance_closing_inputs WHERE document_id=d.id ORDER BY id DESC LIMIT 1) x ON TRUE
      LEFT JOIN LATERAL (SELECT id,components,goods_value_minor FROM finance_claim_details WHERE document_id=d.id ORDER BY id DESC LIMIT 1) y ON TRUE
      WHERE d.owner_id=%s AND (d.document_date BETWEEN %s AND %s OR d.document_date IS NULL)
        AND d.status<>'void' AND d.kind IN ('claim','expense','payable','receivable_adjustment','payable_adjustment')
      ORDER BY d.id''',(owner_id,start,end)).fetchall()
    reversals = c.execute('''SELECT e.id,e.document_id,d.kind,e.created_at FROM finance_entries e
      JOIN finance_documents d ON d.id=e.document_id WHERE d.owner_id=%s AND e.phase='reversal'
      AND (e.created_at AT TIME ZONE 'Asia/Riyadh')::date BETWEEN %s AND %s ORDER BY e.id''',(owner_id,start,end)).fetchall()
    blockers = []
    lines = []
    for d in docs:
        if d['document_date'] is None:
            blockers.append('مستند دون تاريخ قد يؤثر على اكتمال الشهر: #'+str(d['document_id']))
            continue
        if d['mapping'] and d['mapping'].get('claim_detail_revision',0)!=(d['claim_detail_revision'] or 0):
            blockers.append('تغير تفصيل المطالبة بعد تصنيف الإقفال؛ أعد مراجعة التصنيف: #'+str(d['document_id']))
        if d['mapping'] and d['claim_detail_revision']:
            blockers.extend(issue+' #'+str(d['document_id']) for issue in _detail_issues(d['mapping'],dict(components=d['claim_components'],goods_value_minor=d['claim_goods_value_minor'])))
        if d['status'] not in ('posted','reversed'):
            blockers.append('مستند غير مرحّل يحتاج استكمالًا أو إلغاءً: #'+str(d['document_id']))
            continue
        if d['kind'] not in ('claim','expense'):
            blockers.append('حركة تحتاج تحديد أثرها على إقفال الشهر: #'+str(d['document_id']))
            continue
        if d['status']=='reversed':
            blockers.append('مستند معكوس يحتاج مراجعة أثره على فترة الربح: #'+str(d['document_id']))
            continue
        lines.append(d)
    # A later actual cost must not silently duplicate a prior month's approved
    # reporting-only fixed cost for the same linked shipment/claim.
    line_ids={line['document_id'] for line in lines}
    for line in lines:
        mapping=line.get('mapping') or {}
        related=mapping.get('related_document_id')
        if line['kind']=='expense' and related and related not in line_ids and (mapping.get('agency_only_actual_cost_minor') or 0)>0:
            prior=c.execute('SELECT mapping FROM finance_closing_inputs WHERE document_id=%s ORDER BY id DESC LIMIT 1',(related,)).fetchone()
            if prior and (prior['mapping'].get('saber_fixed_cost_minor') or 0)>0:
                blockers.append('تكلفة فعلية مرتبطة بمطالبة سبق اعتماد تكلفة سابر ثابتة لها؛ يلزم منع التكرار: #'+str(line['document_id']))
    if reversals:
        blockers.append('توجد قيود عكسية خلال الشهر تحتاج مطابقة أثرها على الربح')
    snapshot = ledger.fingerprint(dict(owner_id=owner_id,month=month,documents=docs,reversals=reversals))
    review = c.execute('SELECT * FROM finance_closing_reviews WHERE owner_id=%s AND month=%s ORDER BY id DESC LIMIT 1',(owner_id,month)).fetchone()
    completeness = review['completeness'] if review and review['snapshot_hash']==snapshot else None
    report = closing.calculate_monthly_close(month,lines,completeness=completeness)
    if review and review['snapshot_hash']!=snapshot:
        blockers.append('تغيرت مستندات الشهر أو تصنيفاتها بعد مراجعة الاكتمال؛ أعد المراجعة')
    report['blockers'] = blockers+report['blockers']
    if blockers:
        report['ready_for_distribution']=False
        for bucket in report['currencies']:
            bucket['ready_for_distribution']=False
            bucket['blockers']=blockers+bucket['blockers']
            for key in ('shared_profit_minor','agency_only_profit_minor','profit_minor','agency_share_minor','partner_share_minor','rounding_minor'):
                bucket[key]=None
    report.update(owner_id=owner_id,owner_name=owner['name'],documents=docs,snapshot_hash=snapshot,
                  review_revision=review['id'] if review else 0,review_current=bool(completeness))
    return report


def report_data(owner_id,month):
    with db() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return _data(c,owner_id,month)


def save_input(doc_id,actor,form):
    allowed = {'csrf','idempotency_key','expected_revision','expected_detail_revision','reason','confirmation','basis_status','basis_ref','allocation_ref','costs_complete','related_document_id','saber_fixed_cost_minor','saber_fixed_cost_approved','saber_fixed_cost_ref'} | set(AMOUNTS)
    if set(form)-allowed or form.get('confirmation')!='1':
        raise ValueError('أكد مراجعة التصنيف والتكاليف دون إنشاء قيد أو إثبات سداد')
    revision = _revision(form.get('expected_revision'))
    key = ledger.token(form.get('idempotency_key'))
    with db() as c:
        ledger.lock(c)
        d = ledger.document(c,doc_id)
        if d['kind'] not in ('claim','expense') or d['status']!='posted':
            raise ValueError('مدخلات الإقفال متاحة لمطالبة أو مصروف مرحّل نشط فقط')
        ledger.identity(c,d['owner_id'],d['counterparty_id'])
        detail=c.execute('SELECT id,components,goods_value_minor FROM finance_claim_details WHERE document_id=%s ORDER BY id DESC LIMIT 1',(doc_id,)).fetchone()
        detail_revision=detail['id'] if detail else 0
        if _revision(form.get('expected_detail_revision'))!=detail_revision:
            ledger.fail('تغير تفصيل المطالبة منذ فتح النموذج؛ حدّث الصفحة',409)
        mapping = {name:core.clean(form.get(name),1000,name!='related_document_id') for name in ('basis_status','basis_ref','allocation_ref')}
        mapping['claim_detail_revision']=detail_revision
        mapping['costs_complete']=form.get('costs_complete')=='1'
        mapping['related_document_id']=None
        if form.get('related_document_id'):
            related = _revision(form['related_document_id'])
            target = c.execute("SELECT id FROM finance_documents WHERE id=%s AND owner_id=%s AND currency=%s AND kind='claim' AND status='posted'",(related,d['owner_id'],d['currency'])).fetchone()
            if d['kind']!='expense' or not target:
                raise ValueError('ربط التكلفة يتطلب مطالبة نشطة بنفس المالك والعملة')
            mapping['related_document_id']=related
        for name in AMOUNTS:
            raw = core.clean(form.get(name),32)
            mapping[name] = None if raw=='' else 0 if raw in ('0','0.0','0.00','0.000') else core.exact_minor(raw,d['currency'])
        raw_fixed=core.clean(form.get('saber_fixed_cost_minor'),32)
        mapping['saber_fixed_cost_minor']=(0 if 'saber_fixed_cost_minor' not in form else None if raw_fixed=='' else 0 if raw_fixed in ('0','0.0','0.00','0.000') else core.exact_minor(raw_fixed,d['currency']))
        mapping['saber_fixed_cost_approved']=form.get('saber_fixed_cost_approved')=='1'
        mapping['saber_fixed_cost_ref']=core.clean(form.get('saber_fixed_cost_ref'),1000)
        if detail:
            issues=_detail_issues(mapping,detail)
            if issues:raise ValueError('؛ '.join(issues))
        # Strict calculation validation; missing fields remain visible blockers.
        closing.calculate_monthly_close(str(d['document_date'])[:7],[dict(document_id=doc_id,**{k:d[k] for k in ('kind','currency','amount_minor','document_date')},mapping=mapping)])
        payload = dict(document_id=doc_id,previous_revision=revision,mapping=mapping,reason=core.clean(form.get('reason'),1000,True))
        digest = ledger.fingerprint(payload)
        prior = ledger.replay(c,'finance_closing_inputs',key,digest)
        if prior:return prior['id']
        current = c.execute('SELECT id FROM finance_closing_inputs WHERE document_id=%s ORDER BY id DESC LIMIT 1',(doc_id,)).fetchone()
        if revision!=(current['id'] if current else 0):ledger.fail('تغير التصنيف منذ فتح النموذج؛ حدّث الصفحة',409)
        row = c.execute('''INSERT INTO finance_closing_inputs(document_id,previous_revision,mapping,reason,idempotency_key,payload_hash,created_by,created_at)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',(doc_id,revision,Jsonb(mapping),payload['reason'],key,digest,actor,utcnow())).fetchone()
        ledger.audit(c,actor,'closing_input_saved','document',doc_id,dict(revision=row['id'],**payload))
        return row['id']


def save_review(owner_id,month,actor,form):
    allowed = {'csrf','idempotency_key','expected_revision','snapshot_hash','income_complete','expenses_complete','mapping_complete','confirmation_ref','confirmation'}
    if set(form)-allowed or form.get('confirmation')!='1':
        raise ValueError('أكد أن هذه مراجعة إعداد تقرير فقط دون اعتماد أرباح أو تحويل')
    month_dates(month)
    revision = _revision(form.get('expected_revision'))
    completeness = {k:form.get(k)=='1' for k in ('income_complete','expenses_complete','mapping_complete')}
    completeness['confirmation_ref']=core.clean(form.get('confirmation_ref'),1000,True)
    payload = dict(owner_id=owner_id,month=month,previous_revision=revision,snapshot_hash=core.clean(form.get('snapshot_hash'),64,True),completeness=completeness)
    key,digest = ledger.token(form.get('idempotency_key')),ledger.fingerprint(payload)
    with db() as c:
        ledger.lock(c)
        prior = ledger.replay(c,'finance_closing_reviews',key,digest)
        if prior:return prior['id']
        current = _data(c,owner_id,month)
        if current['review_revision']!=revision or current['snapshot_hash']!=payload['snapshot_hash']:
            ledger.fail('تغيرت بيانات الشهر؛ حدّث التقرير قبل مراجعة الاكتمال',409)
        row = c.execute('''INSERT INTO finance_closing_reviews(owner_id,month,snapshot_hash,completeness,previous_revision,idempotency_key,payload_hash,created_by,created_at)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',(owner_id,month,payload['snapshot_hash'],Jsonb(completeness),revision,key,digest,actor,utcnow())).fetchone()
        ledger.audit(c,actor,'closing_review_saved','closing',row['id'],payload)
        return row['id']
