"""Synthetic date-bound, privacy and presentation tests; never live financial data."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
from unittest.mock import patch

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import finance_monthly_core as core, finance_monthly_view as view, finance_monthly_pdf as pdf

OWNER={'id':1,'name':'وكيل تجريبي','identity_ref':'PRIVATE-ID'}
PARTY={'id':2,'name':'عميل اختباري','identity_ref':'PRIVATE-ID'}


def entry(id,kind,amount,day,**changes):
    return dict(id=id,document_id=id,kind=kind,signed_minor=amount,document_date=day,phase='posting',side='receivable',
                owner_id=1,counterparty_id=2,currency='SAR',created_at=datetime(2026,1,2,tzinfo=timezone.utc),
                invoice_ref='DEMO-INV-'+str(id),customs_ref='DEMO-CUSTOMS-'+str(id),**changes)


def statement(entries=None,start='2026-10-01',end='2026-10-31'):
    return core.build_statement(OWNER,PARTY,'SAR',start,end,entries if entries is not None else [
        entry(1,'opening_receivable',100000,'2026-09-29'),entry(2,'claim',20000,'2026-10-03'),
        entry(3,'receipt',-5000,'2026-10-04'),entry(4,'receivable_adjustment',-1000,'2026-10-05')])


def test_period_summary_opening_and_later_month_carry_forward():
    r=statement();assert r['opening_minor']==100000
    assert r['claims_minor']==20000 and r['receipts_minor']==5000 and r['adjustments_minor']==-1000
    assert r['closing_minor']==114000
    assert [x['running_minor'] for x in r['movements']]==[120000,115000,114000]
    r=statement(start='2026-11-01',end='2026-11-30')
    assert r['opening_minor']==114000 and r['closing_minor']==114000 and r['movements']==[]
    r=statement(start='2026-09-01',end='2026-09-30')
    assert r['opening_minor']==0 and r['opening_movements_minor']==100000 and r['claims_minor']==0


def test_reversal_has_own_riyadh_date_and_does_not_backdate():
    base=entry(1,'claim',10000,'2026-09-10')
    reversal=dict(base,id=2,phase='reversal',signed_minor=-10000,created_at=datetime(2026,10,31,22,0,tzinfo=timezone.utc))
    r=statement([base,reversal]);assert r['opening_minor']==10000 and r['closing_minor']==10000
    r=statement([base,reversal],start='2026-11-01',end='2026-11-30')
    assert r['opening_minor']==10000 and r['reversals_minor']==-10000 and r['closing_minor']==0
    assert r['movements'][0]['effective_date']=='2026-11-01'


def test_allocations_do_not_reduce_receipt_a_second_time():
    e=entry(1,'receipt',-1000,'2026-10-10',allocated_minor=1000,allocations=[{'amount_minor':1000}])
    assert statement([e])['closing_minor']==-1000


@pytest.mark.parametrize('change',[{'currency':'USD'},{'side':'payable'},{'owner_id':9},{'counterparty_id':9}])
def test_isolation_rejects_wrong_ledger(change):
    e=entry(1,'claim',100,'2026-10-10');e.update(change)
    with pytest.raises(ValueError):statement([e])


@pytest.mark.parametrize('start,end',[('2026-10-32','2026-11-01'),('2026-11-01','2026-10-01'),('2024-01-01','2026-01-01'),('20261001','2026-10-31')])
def test_bad_or_excessively_long_period_rejected(start,end):
    with pytest.raises(ValueError):statement([],start,end)


def test_duplicate_journal_rows_rejected_and_inputs_unchanged():
    e=entry(1,'claim',100,'2026-10-01')
    with pytest.raises(ValueError):statement([e,e])
    before=deepcopy(e);statement([e]);assert e==before


def test_customer_projection_and_pdf_ignore_internal_information():
    e=entry(1,'claim',92000,'2026-10-01',notes='PRIVATE-NOTES',audit='PRIVATE-AUDIT',cost='PRIVATE-COST')
    e['claim_detail']=dict(revision=2,goods_amount='1000.00',goods_currency='AED',exchange_rate='1.02',goods_value_display='1020.00',registry_display='800.00',tax_display='120.00',zakat='PRIVATE-ZAKAT',cost='PRIVATE-COST',profit='PRIVATE-PROFIT')
    r=statement([e]);raw=repr(r)
    assert 'PRIVATE' not in raw
    page=view.render_statement({'role':'finance'},r)
    assert 'PRIVATE' not in page and '800.00' in page
    assert 'dir="rtl"' in page and 'نسخة التفصيل' in page
    baseline=pdf.render_statement(r)
    mutated=deepcopy(r);mutated.update(notes='PRIVATE-NOTES',profit='PRIVATE-PROFIT')
    mutated['movements'][0]['claim_detail']['zakat']='PRIVATE-ZAKAT'
    with patch('socket.socket',side_effect=AssertionError('External network forbidden')):
        assert pdf.render_statement(mutated)==baseline
    assert baseline.startswith(b'%PDF-') and b'/FontFile2' in baseline
    assert b'/Annots' not in baseline and b'/JavaScript' not in baseline


def test_missing_detail_is_honest_not_inferred():
    r=statement([entry(1,'claim',12345,'2026-10-01')])
    output=view.render_statement({'role':'finance'},r)
    assert 'غير موثق لهذه المطالبة' in output
    assert '800.00' not in output and '120.00' not in output


def test_html_escaped_and_pdf_paginates_long_references():
    entries=[]
    for i in range(1,31):
        e=entry(i,'claim',12345,'2026-10-01')
        e['invoice_ref']='<script>PRIVATE</script>'+('Arabic العربية '*10)
        entries.append(e)
    r=statement(entries)
    assert '<script>' not in view.render_statement({'role':'finance'},r)
    drawn=[]
    original=pdf.canvas.Canvas.drawRightString
    def record(self,x,y,text,*args,**kwargs):
        drawn.append((x,y,text));return original(self,x,y,text,*args,**kwargs)
    with patch.object(pdf.canvas.Canvas,'drawRightString',record):data=pdf.render_statement(r)
    assert b'/Count 1\n' not in data
    assert all(20<=y<=810 for _,y,_ in drawn)


def test_selectors_are_unique_and_customer_pdf_has_no_internal_link():
    output=view.selector_forms([dict(OWNER,kind='owner',confirmed=True),dict(PARTY,kind='counterparty',confirmed=True)],can_view_profit=True)
    import re
    ids=re.findall(r' id="([^"]+)"',output)
    assert len(ids)==len(set(ids))
    assert '/finance/monthly-statement' in output and '/finance/monthly-closing' in output
