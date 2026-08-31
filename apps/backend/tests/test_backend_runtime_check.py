from __future__ import annotations

import json

from scripts.check_backend_runtime import check


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_runtime_checker_states(monkeypatch):
    import scripts.check_backend_runtime as checker

    current = {"data": {"service": "agent-backend", "runtime": {"instance_id": "x", "restart_required": False}}}
    monkeypatch.setattr(checker.urllib.request, "urlopen", lambda *args, **kwargs: _Response(current))
    assert check("http://test", "x") == "current"
    stale = {"data": {"service": "agent-backend", "runtime": {"instance_id": "x", "restart_required": True}}}
    monkeypatch.setattr(checker.urllib.request, "urlopen", lambda *args, **kwargs: _Response(stale))
    assert check("http://test", "x") == "stale"
    legacy = {"data": {"service": "agent-backend"}}
    monkeypatch.setattr(checker.urllib.request, "urlopen", lambda *args, **kwargs: _Response(legacy))
    assert check("http://test") == "legacy"
