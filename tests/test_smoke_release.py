from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import smoke_release


class FakeProcess:
    pid = 9753

    def __init__(self) -> None:
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


def _prepare_smoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[FakeProcess, list[str]]:
    archive = tmp_path / "release.zip"
    archive.write_bytes(b"zip stub")
    extracted = tmp_path / "extracted"
    (extracted / "backend").mkdir(parents=True)
    process = FakeProcess()
    paths: list[str] = []

    monkeypatch.setattr(smoke_release, "extract_archive", lambda *_args: extracted)
    monkeypatch.setattr(smoke_release, "free_loopback_port", lambda: 18080)
    monkeypatch.setattr(smoke_release.shutil, "which", lambda name: name)
    monkeypatch.setattr(smoke_release.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(smoke_release.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(smoke_release, "wait_for_backend", lambda *_args, **_kwargs: True)

    def fetch(url: str) -> str:
        paths.append(url)
        return "<html><body>LiBao</body></html>" if url.endswith(("/", "/workspace/smoke")) else '{"status":"ok"}'

    monkeypatch.setattr(smoke_release, "fetch_text", fetch)
    return process, paths


def test_smoke_release_checks_health_root_and_deep_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process, paths = _prepare_smoke(monkeypatch, tmp_path)

    smoke_release.smoke_release(tmp_path / "release.zip")

    assert paths == [
        "http://127.0.0.1:18080/api/v1/system/health",
        "http://127.0.0.1:18080/",
        "http://127.0.0.1:18080/workspace/smoke",
    ]
    assert process.returncode == 0


@pytest.mark.parametrize("failure", ["health-timeout", "malformed-spa"])
def test_smoke_release_always_stops_owned_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    process, paths = _prepare_smoke(monkeypatch, tmp_path)
    if failure == "health-timeout":
        monkeypatch.setattr(smoke_release, "wait_for_backend", lambda *_args, **_kwargs: False)
    else:
        def malformed_fetch(url: str) -> str:
            paths.append(url)
            return "not html" if url.endswith("/workspace/smoke") else "<html>ok</html>"

        monkeypatch.setattr(smoke_release, "fetch_text", malformed_fetch)

    with pytest.raises(RuntimeError):
        smoke_release.smoke_release(tmp_path / "release.zip")

    assert process.returncode == 0
