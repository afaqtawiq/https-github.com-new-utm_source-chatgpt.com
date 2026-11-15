"""Positive receivable checkpoints preserve economic-date accounting."""
from datetime import date
import unittest
from fastapi import HTTPException
from app import finance_core as core
from app import finance_service as service
from app import finance_monthly_core as monthly


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


def ledger(ident, when, signed, *, phase='posting', recorded='2025-04-20T12:00:00+00:00'):
    return {'id':ident, 'document_id':ident, 'document_date':date.fromisoformat(when),
            'signed_minor':signed, 'phase':phase, 'created_at':recorded,
            'owner_id':1, 'counterparty_id':2, 'currency':'SAR', 'side':'receivable',
            'kind':'claim'}


class Connection:
    def __init__(self, entries, *, evidence=None, active=None):
        self.entries = entries
        self.evidence = evidence
        self.active = active or []

    def execute(self, sql, args):
        if 'FROM finance_entries e' in sql:
            assert args == (1,2,'SAR') and "e.side='receivable'" in sql
            return Cursor(self.entries)
        if 'FROM finance_reconciliation_evidence' in sql:
            assert args == (30,)
            return Cursor([self.evidence] if self.evidence else [])
        if 'FROM finance_documents' in sql:
            assert args == (1,2,'SAR',30)
            return Cursor(self.active)
        raise AssertionError(sql)


class TestReconciliation(unittest.TestCase):
    cutoff = date(2025, 3, 31)

    def setUp(self):
        self.entries = [
            ledger(1,'2025-03-31',50000),
            ledger(2,'2025-04-01',1700),
            ledger(3,'2025-03-31',-5000,phase='reversal',recorded='2025-03-31T21:00:00+00:00'),
        ]
        self.recon = dict(id=30, owner_id=1,counterparty_id=2,currency='SAR',
                          kind=core.RECONCILIATION_KIND, amount_minor=8000, document_date=self.cutoff)

    def test_economic_cutoff_and_later_effect(self):
        prior,later,_ = service.reconciliation_snapshot(Connection(self.entries),1,2,'SAR',self.cutoff)
        self.assertEqual((prior,later),(50000,-3300))
        self.assertEqual(58000+later,54700)

    def test_regular_create_rejects_special_kind(self):
        with self.assertRaises(ValueError):
            core.parse_document({'kind':core.RECONCILIATION_KIND})

    def test_ack_and_stale_snapshot(self):
        prior,later,digest = service.reconciliation_snapshot(Connection(self.entries),1,2,'SAR',self.cutoff)
        evidence = dict(cutoff=self.cutoff,target_minor=58000,prior_minor=prior,later_minor=later,
                        delta_minor=8000,snapshot_hash=digest)
        conn = Connection(list(self.entries),evidence=evidence)
        with self.assertRaises(HTTPException):
            service.check_reconciliation(conn,self.recon,{})
        self.assertEqual(service.check_reconciliation(conn,self.recon,{'reconciliation_ack':'1'}),evidence)
        conn.entries.extend([ledger(4,'2025-04-02',110),ledger(5,'2025-04-02',-110)])
        with self.assertRaises(HTTPException) as err:
            service.check_reconciliation(conn,self.recon,{'reconciliation_ack':'1'})
        self.assertEqual(err.exception.status_code,409)  # even if later balance nets to same value

    def test_cutoff_blocks_same_side_and_exact_date_not_later_or_payable(self):
        posted = [dict(id=20, kind=core.RECONCILIATION_KIND, opening_cutoff=None, document_date=self.cutoff)]
        conn = Connection([],active=posted)
        with self.assertRaises(HTTPException) as err:
            service.guard_opening_period(conn,dict(self.recon,kind='claim'))
        self.assertEqual(err.exception.status_code,409)
        service.guard_opening_period(conn,dict(self.recon,kind='payable'))
        service.guard_opening_period(conn,dict(self.recon,kind='claim',document_date=date(2025,4,1)))
        with self.assertRaises(HTTPException):
            service.guard_opening_period(conn,self.recon)  # replacement cannot double-post same cutoff

    def test_monthly_projection_classifies_increase_as_adjustment(self):
        rows = self.entries+[dict(ledger(30,'2025-03-31',8000),kind=core.RECONCILIATION_KIND)]
        r = monthly.build_statement(dict(id=1,name='Owner'),dict(id=2,name='Counterparty'),
                                    'SAR','2025-03-01','2025-03-31',rows)
        self.assertEqual((r['claims_minor'],r['adjustments_minor'],r['opening_movements_minor'],r['closing_minor']),
                         (50000,8000,0,58000))
        self.assertEqual(r['movements'][-1]['debit_minor'],8000)


if __name__ == '__main__':
    unittest.main()
