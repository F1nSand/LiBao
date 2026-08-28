"""Docker 沙箱命令契约测试（Task 2：只验证输入边界，不启动 Docker）。"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.tools.sandbox import SandboxCommand, SandboxErrorCode, SandboxFailure, SandboxResult


@pytest.mark.parametrize("workdir", ["C:\\workspace", "D:\\tmp\\project", "/tmp/project"])
def test_sandbox_command_rejects_host_absolute_workdir(workdir):
    with pytest.raises(SandboxFailure) as exc:
        SandboxCommand(argv=("bash", "-lc", "pwd"), workdir=workdir)
    assert exc.value.code == SandboxErrorCode.INVALID_WORKDIR


@pytest.mark.parametrize("workdir", ["../outside", "/workspace/../etc", "/workspace/src/../../etc"])
def test_sandbox_command_rejects_parent_escape(workdir):
    with pytest.raises(SandboxFailure) as exc:
        SandboxCommand(argv=("bash", "-lc", "pwd"), workdir=workdir)
    assert exc.value.code == SandboxErrorCode.INVALID_WORKDIR


def test_sandbox_command_accepts_workspace_relative_workdir():
    command = SandboxCommand(argv=("bash", "-lc", "pwd"), workdir="/workspace/src/tools")
    assert command.argv == ("bash", "-lc", "pwd")
    assert command.workdir == "/workspace/src/tools"
    assert command.workspace_access == "rw"


def _settings(**overrides):
    values = {
        "sandbox_docker_cli": "docker",
        "sandbox_docker_image": "libao-sandbox:py312-v1",
        "sandbox_docker_memory": "512m",
        "sandbox_docker_cpus": "1",
        "sandbox_docker_pids_limit": 128,
        "sandbox_docker_tmpfs_mb": 64,
        "tool_result_max_chars": 8000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _FakeProcess:
    def __init__(self, *, returncode=0, stdout=b"", stderr=b"", communicate_error=None):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.communicate_error = communicate_error
        self.killed = False

    async def communicate(self):
        if self.communicate_error is not None:
            raise self.communicate_error
        return self.stdout, self.stderr

    def kill(self):
        self.killed = True


@pytest.mark.asyncio
async def test_docker_argv_has_security_defaults(monkeypatch, tmp_path):
    from app.tools.sandbox import run_docker_command

    calls = []

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    result = await run_docker_command(
        SandboxCommand(argv=("bash", "-lc", "echo ok")),
        workspace_root=str(tmp_path),
        timeout_ms=1000,
        settings=_settings(),
    )

    assert isinstance(result, SandboxResult)
    argv = calls[0]
    for expected in (
        ("--network", "none"),
        ("--memory", "512m"),
        ("--cpus", "1"),
        ("--pids-limit", "128"),
        ("--read-only",),
        ("--tmpfs", "/tmp:rw,noexec,nosuid,size=64m"),
        ("--cap-drop", "ALL"),
        ("--security-opt", "no-new-privileges"),
        ("--user", "65532:65532"),
        ("--label", "libao.sandbox=true"),
    ):
        if len(expected) == 1:
            assert expected[0] in argv
        else:
            assert expected[0] in argv and argv[argv.index(expected[0]) + 1] == expected[1]


@pytest.mark.asyncio
async def test_windows_workspace_is_the_only_bind_mount(monkeypatch, tmp_path):
    from app.tools.sandbox import run_docker_command

    workspace = tmp_path / "workspace with spaces"
    workspace.mkdir()
    calls = []

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    await run_docker_command(
        SandboxCommand(argv=("bash", "-lc", "touch ok"), workspace_access="ro"),
        workspace_root=str(workspace),
        timeout_ms=1000,
        settings=_settings(),
    )

    argv = calls[0]
    assert argv.count("--mount") == 1
    mount = argv[argv.index("--mount") + 1]
    assert f"src={workspace.resolve()}" in mount
    assert "dst=/workspace" in mount
    assert mount.endswith(",ro")
    assert all(secret not in arg for arg in argv for secret in (".env", ".LiBao", "/var/run/docker.sock"))


@pytest.mark.asyncio
async def test_relative_cwd_maps_under_container_workspace(monkeypatch, tmp_path):
    from app.tools.sandbox import run_docker_command

    (tmp_path / "src" / "tools").mkdir(parents=True)
    calls = []

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    await run_docker_command(
        SandboxCommand(argv=("bash", "-lc", "pwd"), workdir="/workspace/src/tools"),
        workspace_root=str(tmp_path),
        timeout_ms=1000,
        settings=_settings(),
    )

    argv = calls[0]
    assert argv[argv.index("--workdir") + 1] == "/workspace/src/tools"
    assert str(tmp_path.resolve()) not in argv[argv.index("--workdir") + 1]


@pytest.mark.asyncio
async def test_invalid_workspace_or_cwd_does_not_start_docker(monkeypatch, tmp_path):
    from app.tools.sandbox import run_docker_command

    calls = []

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(SandboxFailure) as missing:
        await run_docker_command(
            SandboxCommand(argv=("bash", "-lc", "pwd")),
            workspace_root=str(tmp_path / "missing"),
            timeout_ms=1000,
            settings=_settings(),
        )
    assert missing.value.code == SandboxErrorCode.INVALID_WORKDIR

    for workdir in ("C:\\host", "/tmp/outside", "../outside"):
        with pytest.raises(SandboxFailure) as invalid:
            command = SandboxCommand(argv=("bash", "-lc", "pwd"), workdir=workdir)
            await run_docker_command(command, workspace_root=str(tmp_path), timeout_ms=1000, settings=_settings())
        assert invalid.value.code == SandboxErrorCode.INVALID_WORKDIR
    assert calls == []


@pytest.mark.asyncio
async def test_missing_image_returns_stable_failure_without_pull(monkeypatch, tmp_path):
    from app.tools.sandbox import run_docker_command

    calls = []

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return _FakeProcess(returncode=125, stderr=b"Unable to find image 'libao-sandbox:py312-v1' locally")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(SandboxFailure) as exc:
        await run_docker_command(
            SandboxCommand(argv=("bash", "-lc", "true")),
            workspace_root=str(tmp_path),
            timeout_ms=1000,
            settings=_settings(),
        )
    assert exc.value.code == SandboxErrorCode.IMAGE_MISSING
    assert all(argv[1] != "pull" for argv in calls)


@pytest.mark.asyncio
async def test_daemon_unavailable_returns_stable_failure(monkeypatch, tmp_path):
    from app.tools.sandbox import run_docker_command

    async def fake_exec(*argv, **kwargs):
        return _FakeProcess(returncode=125, stderr=b"Cannot connect to the Docker daemon")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(SandboxFailure) as exc:
        await run_docker_command(
            SandboxCommand(argv=("bash", "-lc", "true")),
            workspace_root=str(tmp_path),
            timeout_ms=1000,
            settings=_settings(),
        )
    assert exc.value.code == SandboxErrorCode.UNAVAILABLE


@pytest.mark.asyncio
async def test_timeout_force_removes_cidfile_container(monkeypatch, tmp_path):
    from app.tools.sandbox import run_docker_command

    calls = []
    cidfile = None

    async def fake_exec(*argv, **kwargs):
        nonlocal cidfile
        calls.append(argv)
        if "--cidfile" in argv:
            cidfile = Path(argv[argv.index("--cidfile") + 1])
            cidfile.write_text("container-123", encoding="utf-8")
            return _FakeProcess(communicate_error=TimeoutError())
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(SandboxFailure) as exc:
        await run_docker_command(
            SandboxCommand(argv=("bash", "-lc", "sleep 10")),
            workspace_root=str(tmp_path),
            timeout_ms=1,
            settings=_settings(),
        )
    assert exc.value.code == SandboxErrorCode.TIMEOUT
    assert exc.value.retryable is False
    assert ("rm", "-f", "container-123") == tuple(calls[1][1:])
    assert cidfile is not None and not cidfile.exists()


@pytest.mark.asyncio
async def test_cancellation_cleans_container_and_reraises(monkeypatch, tmp_path):
    from app.tools.sandbox import run_docker_command

    calls = []
    started = asyncio.Event()

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        if "--cidfile" in argv:
            cidfile = Path(argv[argv.index("--cidfile") + 1])
            cidfile.write_text("container-cancel", encoding="utf-8")
            started.set()
            await asyncio.Event().wait()
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    task = asyncio.create_task(
        run_docker_command(
            SandboxCommand(argv=("bash", "-lc", "sleep 10")),
            workspace_root=str(tmp_path),
            timeout_ms=1000,
            settings=_settings(),
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ("rm", "-f", "container-cancel") == tuple(calls[1][1:])


@pytest.mark.asyncio
async def test_success_nonzero_and_output_are_bounded(monkeypatch, tmp_path):
    from app.tools.sandbox import run_docker_command

    responses = [
        _FakeProcess(stdout=b"ok", stderr=b""),
        _FakeProcess(returncode=2, stdout=b"out", stderr=b"err"),
        _FakeProcess(stdout=b"123456789", stderr=b"abcdef"),
    ]

    async def fake_exec(*argv, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    result = await run_docker_command(
        SandboxCommand(argv=("bash", "-lc", "true")),
        workspace_root=str(tmp_path),
        timeout_ms=1000,
        settings=_settings(tool_result_max_chars=10),
    )
    assert result.exit_code == 0 and result.stdout == "ok"

    with pytest.raises(SandboxFailure) as nonzero:
        await run_docker_command(
            SandboxCommand(argv=("bash", "-lc", "false")),
            workspace_root=str(tmp_path),
            timeout_ms=1000,
            settings=_settings(tool_result_max_chars=10),
        )
    assert nonzero.value.code == SandboxErrorCode.EXIT_NONZERO
    assert nonzero.value.output["exit_code"] == 2

    bounded = await run_docker_command(
        SandboxCommand(argv=("bash", "-lc", "printf")),
        workspace_root=str(tmp_path),
        timeout_ms=1000,
        settings=_settings(tool_result_max_chars=10),
    )
    assert bounded.truncated is True
    assert len(bounded.stdout) + len(bounded.stderr) <= 10
