"""Reporting reads run in one snapshot; never infer customer or profit mappings."""
from app.storage import db
from app import finance_service as ledger
from app import finance_monthly_core as monthly
from app import finance_claim_core as claim_core


def statement_data(owner_id, counterparty_id, currency, start, end):
    start, end = monthly.period(start, end)
    currency = monthly.core.currency_code(currency)
    with db() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        owner, party = ledger.identity(c, owner_id, counterparty_id)
        entries = c.execute('''SELECT e.id,e.document_id,e.phase,e.side,e.signed_minor,e.created_at,
          d.owner_id,d.counterparty_id,d.currency,d.document_date,d.kind,d.invoice_ref,d.customs_ref,d.amount_minor,
          x.id detail_id,x.goods_amount,x.goods_currency,x.exchange_rate,x.goods_value_minor,
          x.currency detail_currency,x.components,x.claim_total_minor
          FROM finance_entries e JOIN finance_documents d ON d.id=e.document_id
          LEFT JOIN LATERAL (SELECT * FROM finance_claim_details WHERE document_id=d.id ORDER BY id DESC LIMIT 1) x ON TRUE
          WHERE d.owner_id=%s AND d.counterparty_id=%s AND d.currency=%s AND e.side='receivable'
          ORDER BY e.id''', (owner_id,counterparty_id,currency)).fetchall()
        for entry in entries:
            if entry['detail_id']:
                if entry['detail_currency'] != currency or entry['claim_total_minor'] != entry['amount_minor']:
                    ledger.fail('تفصيل المطالبة غير مطابق للمستند',409)
                d = claim_core.present_details(dict(entry, id=entry['detail_id']))
                entry['claim_detail'] = dict(revision=d['id'], goods_amount=d['goods_amount'], goods_currency=d['goods_currency'],
                    exchange_rate=d['exchange_rate'], goods_value_display=d['goods_value_display'],
                    registry_display=d['component_display']['registry'], tax_display=d['component_display']['tax'])
        return monthly.build_statement(owner, party, currency, start, end, entries)
