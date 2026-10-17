"""Exercise real thread helper bodies without bootstrapping production storage."""
import ast
import asyncio
from contextvars import copy_context
from pathlib import Path
import threading
import sys
from types import SimpleNamespace

from app import zernio_whatsapp as z


def function(path, name, namespace):
    tree = ast.parse(Path(path).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, 'exec'), namespace)
    return namespace[name]


def test_manager_thread_retains_immutable_ingress_generation():
    async def send(*args, **kwargs):
        return z._automation_origin.get()
    deliver = function('app/manager_actions.py', 'deliver', {
        'asyncio': asyncio, 'threading': threading, 'copy_context': copy_context,
        'wa': SimpleNamespace(send=send), 'TEMPLATE_INTRO': 'test', 'TEMPLATE_OUTRO': 'test'})
    with z.automation_origin('test-account', '966500000001', 7):
        assert deliver('966500000001', 'Synthetic only') == ('test-account', '966500000001', 7)
    assert z._automation_origin.get() is None


def test_load_workflow_thread_copies_context(monkeypatch):
    done = threading.Event()
    observed = []
    async def contact_owner(shipment_id, approved):
        observed.append((shipment_id, approved, z._automation_origin.get()))
        done.set()
    monkeypatch.setitem(sys.modules, 'app.freight_workflow', SimpleNamespace(contact_owner=contact_owner))
    start = function('app/load_vision.py', '_start_workflow', {
        'asyncio': asyncio, 'threading': threading, 'copy_context': copy_context})
    with z.automation_origin('test-account', '966500000001', 7):
        start(42)
    assert done.wait(2)
    assert observed == [(42, True, ('test-account', '966500000001', 7))]
    assert z._automation_origin.get() is None
