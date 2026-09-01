from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from scripts import bootstrap, run_checks


def _load_start_backend():
    path = Path(__file__).parents[1] / "apps" / "backend" / "scripts" / "start_backend.py"
    spec = importlib.util.spec_from_file_location("libao_start_backend", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_runs_uv_projects_and_npm_ci_in_repo_root(monkeypatch):
    calls: list[tuple[list[str], Path]] = []

    def fake_run(argv, *, cwd, check):
        calls.append((list(argv), cwd))
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    assert bootstrap.run_bootstrap(which=lambda name: None if name == "npm.cmd" else name, run=fake_run) == 0
    assert [argv for argv, _ in calls] == [
        ["uv", "sync", "--project", "apps/backend"],
        ["uv", "sync", "--project", "tools/devpanel"],
        ["npm", "ci", "--prefix", "apps/frontend"],
    ]
    assert all(cwd == bootstrap.ROOT for _, cwd in calls)


def test_bootstrap_returns_first_nonzero_exit_code():
    calls: list[list[str]] = []

    def fake_run(argv, *, cwd, check):
        calls.append(list(argv))
        return type("Completed", (), {"returncode": 17 if len(calls) == 2 else 0})()

    assert bootstrap.run_bootstrap(which=lambda name: name, run=fake_run) == 17
    assert len(calls) == 2


def test_run_checks_uses_identical_check_list_on_windows_and_posix(monkeypatch):
    captured: list[tuple[list[str], Path]] = []

    def fake_run(argv, *, cwd, check):
        captured.append((list(argv), cwd))
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(run_checks, "ROOT", Path("C:/repo"))
    monkeypatch.setattr(run_checks, "BACKEND", Path("C:/repo/apps/backend"))
    monkeypatch.setattr(run_checks, "FRONTEND", Path("C:/repo/apps/frontend"))

    assert run_checks.run_checks(which=lambda name: "npm.cmd" if name == "npm.cmd" else name, run=fake_run) == 0
    assert [argv for argv, _ in captured] == [
        ["uv", "run", "ruff", "check", "."],
        ["uv", "run", "pytest", "tests/"],
        ["npm.cmd", "run", "lint:check"],
        ["npm.cmd", "run", "typecheck"],
        ["npm.cmd", "run", "build"],
        ["npm.cmd", "run", "test:unit"],
        ["npm.cmd", "run", "test:e2e"],
    ]
    assert [cwd for _, cwd in captured] == [run_checks.BACKEND] * 2 + [run_checks.FRONTEND] * 5


def test_start_backend_rejects_non_loopback_host(monkeypatch):
    start_backend = _load_start_backend()
    monkeypatch.setenv("LIBAO_BACKEND_HOST", "0.0.0.0")

    with pytest.raises(SystemExit):
        start_backend.main([])


def test_start_backend_uses_environment_port(monkeypatch):
    start_backend = _load_start_backend()
    monkeypatch.setenv("LIBAO_BACKEND_PORT", "18000")
    monkeypatch.setattr(start_backend, "runtime_state", lambda url: "current")
    called = {}
    monkeypatch.setattr(start_backend, "run_uvicorn", lambda port: called.setdefault("port", port))

    assert start_backend.main([]) == 0
    assert called == {}
    assert start_backend.backend_url(18000) == "http://127.0.0.1:18000/api/v1/system/health"


@pytest.mark.parametrize("state", ["foreign", "stale", "legacy"])
def test_start_backend_never_reuses_foreign_or_stale_instance(monkeypatch, state):
    start_backend = _load_start_backend()
    monkeypatch.setattr(start_backend, "runtime_state", lambda url: state)
    called = []
    monkeypatch.setattr(start_backend, "run_uvicorn", lambda port: called.append(port))

    assert start_backend.main([]) == 1
    assert called == []
