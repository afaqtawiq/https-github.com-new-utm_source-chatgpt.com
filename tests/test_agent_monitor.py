import importlib
import sys
import types
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import agent_monitor as monitor


def test_stale_running_is_not_reported_as_success():
    now = datetime.now(timezone.utc)
    run = {'status': 'running', 'updated_at': now - timedelta(minutes=6), 'result': '{}'}
    assert monitor.run_view(run, now)['status'] == 'stale'
    run['updated_at'] = now
    assert monitor.run_view(run, now)['status'] == 'running'
    run['status'] = 'partial'
    assert monitor.run_view(run, now)['status'] == 'partial'
    assert monitor.run_view(None)['status'] == 'idle'


def test_api_requires_session_and_never_caches():
    app = FastAPI()
    app.include_router(monitor.router)
    storage = types.ModuleType('app.storage')
    storage.get_session = Mock(return_value=None)
    with patch.dict(sys.modules, {'app.storage': storage}), patch.object(monitor, 'snapshot', return_value={'run': {}}) as snap:
        client = TestClient(app)
        assert client.get('/api/agent-monitor').status_code == 401
        snap.assert_not_called()
        storage.get_session.return_value = {'user_id': 1}
        response = client.get('/api/agent-monitor')
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'


def test_run_updates_persist_and_end_only_when_terminal():
    storage = types.ModuleType('app.storage')
    storage.execute, storage.log = Mock(), Mock()
    storage.utcnow = lambda: datetime.now(timezone.utc)
    with patch.dict(sys.modules, {'app.storage': storage}):
        monitor.update_run(7, 'فحص المصدر', 2, 4, {'signals': 3})
        assert storage.execute.call_args.args[1][-2] is None
        monitor.update_run(7, 'انتهى', 4, 4, {'errors': 1}, 'partial')
        values = storage.execute.call_args.args[1]
        assert values[0] == 'partial'
        assert values[-2] is not None
        assert values[-1] == 7


def test_failed_cycle_records_failure_without_claiming_completion():
    # Load the real discovery code with an isolated storage dependency.
    from app import discovery
    storage = types.ModuleType('app.storage')
    storage.db = Mock()
    storage.db.return_value.__enter__ = Mock()
    storage.db.return_value.__exit__ = Mock(return_value=False)
    conn = storage.db.return_value.__enter__.return_value
    conn.execute.return_value.fetchone.return_value = {'acquired': True}
    with patch.dict(sys.modules, {'app.storage': storage}), patch.object(monitor, 'start_run', return_value=7), patch.object(monitor, 'update_run') as update, patch.object(discovery, '_run_discovery_cycle', side_effect=RuntimeError('private provider details')):
        with pytest.raises(RuntimeError):
            discovery.run_discovery_cycle()
        assert update.call_args.kwargs['status'] == 'failed'
        assert 'private provider details' not in update.call_args.args[1]
        conn.execute.return_value.fetchone.return_value = {'acquired': False}
        update.reset_mock()
        assert discovery.run_discovery_cycle() == {'skipped': 'cycle_already_running'}
        update.assert_not_called()


def test_widget_renders_untrusted_text_as_text_and_handles_disconnect():
    widget = monitor.monitor_widget()
    assert 'innerHTML' not in widget
    assert 'textContent' in widget
    assert 'البيانات المعروضة قديمة' in widget
    assert 'setTimeout(refresh,5000)' in widget
