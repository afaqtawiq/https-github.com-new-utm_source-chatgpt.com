"""Regression for the acceptance fixture's simulated follow-up clock; no I/O."""
import datetime as dt
import importlib.util
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GrowthAcceptanceClockTests(unittest.TestCase):
    def test_simulated_send_clock_reaches_exact_four_day_boundary(self):
        fixture = load_module('growth_clock_fixture', ROOT / 'tests/growth_acceptance.py')
        storage = ModuleType('app.storage')
        storage.db = MagicMock()
        storage.utcnow = lambda: dt.datetime.now(dt.timezone.utc)
        with patch.dict('sys.modules', {'app.storage': storage}):
            pf = load_module('growth_clock_followups', ROOT / 'app/prospect_followups.py')
        original_clock = pf.utcnow
        work = dt.datetime(2026, 11, 8, 6, 35, tzinfo=dt.timezone.utc)
        later = work + dt.timedelta(days=4)
        self.assertTrue(pf.in_hours(work))
        self.assertTrue(pf.in_hours(later))
        row = {'id': 1, 'last_step': 1, 'last_at': None,
               'decided_at': work - dt.timedelta(days=4)}
        connection = MagicMock()
        storage.db.return_value.__enter__.return_value = connection

        def execute(query, params=None):
            result = MagicMock()
            if 'SELECT COUNT(*)' in query:
                result.fetchone.return_value = {'n': 0}
            elif 'SELECT d.*' in query:
                result.fetchall.return_value = [row]
            elif 'to_regclass' in query:
                result.fetchone.return_value = {'t': None}
            return result

        connection.execute.side_effect = execute
        # Old fixture: the real send happened just after the supplied start time.
        row['last_at'] = work + dt.timedelta(microseconds=1)
        self.assertEqual(pf.due(later), [])

        async def record_send(when):
            row['last_at'] = pf.utcnow()
            self.assertEqual(row['last_at'], when)
            return {'sent': 1}

        with patch.object(pf, 'run', record_send):
            self.assertEqual(fixture.run_followups_at(pf, work), {'sent': 1})
            self.assertIs(pf.utcnow, original_clock)
            self.assertEqual(pf.due(later - dt.timedelta(microseconds=1)), [])
            self.assertEqual(pf.due(later), [(row, 2)])
            fixture.run_followups_at(pf, later)
            self.assertEqual(row['last_at'], later)
            self.assertIs(pf.utcnow, original_clock)


if __name__ == '__main__':
    unittest.main()
