from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import real_e2e


@pytest.mark.parametrize(
    ("value", "default_port", "expected"),
    [
        (
            "http://127.0.0.1",
            8000,
            ("127.0.0.1", 8000, "http://127.0.0.1:8000"),
        ),
        (
            "http://127.0.0.1:18000/",
            8000,
            ("127.0.0.1", 18000, "http://127.0.0.1:18000"),
        ),
        (
            "http://127.0.0.1:15173////",
            5173,
            ("127.0.0.1", 15173, "http://127.0.0.1:15173"),
        ),
    ],
)
def test_parse_loopback_url_normalizes_default_and_trailing_slashes(
    value: str,
    default_port: int,
    expected: tuple[str, int, str],
) -> None:
    assert real_e2e.parse_loopback_url(value, default_port) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://0.0.0.0:8000",
        "http://localhost:8000",
        "http://192.168.1.10:8000",
        "http://user:pass@127.0.0.1:8000",
        "http://127.0.0.1:8000/api",
        "http://127.0.0.1:8000?debug=1",
        "http://127.0.0.1:8000#fragment",
        "https://127.0.0.1:8000",
        "http://127.0.0.1:0",
        "http://127.0.0.1:65536",
    ],
)
def test_parse_loopback_url_rejects_non_local_or_ambiguous_urls(value: str) -> None:
    with pytest.raises(ValueError):
        real_e2e.parse_loopback_url(value, 8000)


class FakeProcess:
    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9


def test_custom_backend_port_is_used_for_spawn_health_and_vite_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("E2E_BACKEND_URL", "http://127.0.0.1:18000")
    monkeypatch.setenv("E2E_FRONTEND_URL", "http://127.0.0.1:15173/")
    backend_process = FakeProcess()
    popen_calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    run_calls: list[dict[str, object]] = []
    health_urls: list[str] = []
    health_results = iter([False, True])

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        popen_calls.append((tuple(command), kwargs))
        return backend_process

    def fake_healthy(url: str) -> bool:
        health_urls.append(url)
        return next(health_results)

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        run_calls.append({"command": command, **kwargs})
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(real_e2e.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(real_e2e.subprocess, "run", fake_run)
    monkeypatch.setattr(real_e2e, "healthy", fake_healthy)
    monkeypatch.setattr(real_e2e.time, "sleep", lambda _seconds: None)

    assert real_e2e.run_real_e2e([]) == 0

    assert "--port" in popen_calls[0][0]
    assert popen_calls[0][0][popen_calls[0][0].index("--port") + 1] == "18000"
    assert health_urls == [
        "http://127.0.0.1:18000",
        "http://127.0.0.1:18000",
    ]
    child_env = run_calls[0]["env"]
    assert isinstance(child_env, dict)
    assert child_env["E2E_BACKEND_URL"] == "http://127.0.0.1:18000"
    assert child_env["VITE_API_PROXY"] == "http://127.0.0.1:18000"
    assert child_env["VITE_USE_MOCK"] == "false"
    assert run_calls[0]["cwd"] == real_e2e.FRONTEND


def test_started_backend_is_stopped_on_startup_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("E2E_BACKEND_URL", "http://127.0.0.1:18000")
    backend_process = FakeProcess()
    stopped: list[FakeProcess] = []

    monkeypatch.setattr(real_e2e, "healthy", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(real_e2e.subprocess, "Popen", lambda *_args, **_kwargs: backend_process)
    monkeypatch.setattr(real_e2e, "wait_for_backend", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(real_e2e, "stop_process", lambda process: stopped.append(process))

    assert real_e2e.run_real_e2e([]) != 0
    assert stopped == [backend_process]


def test_started_backend_is_stopped_on_playwright_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("E2E_BACKEND_URL", "http://127.0.0.1:18000")
    backend_process = FakeProcess()
    stopped: list[FakeProcess] = []

    monkeypatch.setattr(real_e2e, "healthy", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(real_e2e.subprocess, "Popen", lambda *_args, **_kwargs: backend_process)
    monkeypatch.setattr(real_e2e, "wait_for_backend", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(real_e2e.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=7))
    monkeypatch.setattr(real_e2e, "stop_process", lambda process: stopped.append(process))

    assert real_e2e.run_real_e2e([]) == 7
    assert stopped == [backend_process]


def test_existing_backend_is_not_stopped_by_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("E2E_BACKEND_URL", "http://127.0.0.1:18000")
    stopped: list[object] = []

    monkeypatch.setattr(real_e2e, "healthy", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(real_e2e, "wait_for_backend", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(real_e2e.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(real_e2e, "stop_process", lambda process: stopped.append(process))

    assert real_e2e.run_real_e2e([]) == 0
    assert stopped == []
