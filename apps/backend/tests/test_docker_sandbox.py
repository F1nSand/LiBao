"""Docker 沙箱命令契约测试（Task 2：只验证输入边界，不启动 Docker）。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.tools.sandbox import (
    SandboxCommand,
    SandboxErrorCode,
    SandboxFailure,
    SandboxResult,
    WorkspaceCommand,
)


def test_workspace_command_rejects_absolute_and_parent_workdir():
    for workdir in ("C:/project", "/tmp/project", "../outside", "src/../../etc"):
        with pytest.raises(SandboxFailure) as exc:
            WorkspaceCommand(script="Write-Output ok", workdir=workdir)
        assert exc.value.code == SandboxErrorCode.INVALID_WORKDIR


def test_workspace_command_accepts_relative_workdir_and_internal_env_only():
    command = WorkspaceCommand(
        script="Write-Output ok",
        shell="powershell",
        workdir="src/tools",
        env={"LIBAO_SHELL_REVIEW_NOTE": "reviewed"},
    )
    assert command.shell == "powershell"
    assert command.workdir == "src/tools"
    assert command.env["LIBAO_SHELL_REVIEW_NOTE"] == "reviewed"


@pytest.mark.asyncio
async def test_workspace_runner_uses_stdin_shell_and_bounded_result(monkeypatch, tmp_path):
    from app.tools import sandbox

    calls = []

    class _RunnerProcess(_FakeProcess):
        def __init__(self):
            super().__init__(stdout=b"ok\n")
            self.stdin = _FakeStdin()

    class _FakeStdin:
        def __init__(self):
            self.data = bytearray()
            self.closed = False

        def write(self, data):
            self.data.extend(data)

        async def drain(self):
            return None

        def close(self):
            self.closed = True

    monkeypatch.setattr(sandbox, "_workspace_shell_executable", lambda shell: "pwsh.exe")

    async def fake_exec(*argv, **kwargs):
        calls.append((argv, kwargs))
        return _RunnerProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    result = await sandbox.run_workspace_command(
        WorkspaceCommand(script="Write-Output ok", shell="powershell"),
        workspace_root=str(tmp_path),
        timeout_ms=1000,
        settings=_settings(tool_result_max_chars=16),
    )
    assert result.stdout == "ok\n"
    assert calls[0][0] == ("pwsh.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-")
    assert calls[0][1]["cwd"] == str(tmp_path.resolve())



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


class _FakeStream:
    def __init__(self, data=b"", *, hang=False, error=None):
        self.data = data
        self.hang = hang
        self.error = error
        self.read_count = 0

    async def read(self, _size=-1):
        self.read_count += 1
        if self.error is not None:
            raise self.error
        if self.hang:
            await asyncio.Event().wait()
        if not self.data:
            return b""
        data, self.data = self.data, b""
        return data


class _FakeProcess:
    def __init__(self, *, returncode=0, stdout=b"", stderr=b"", hang=False, stream_error=None):
        self._configured_returncode = returncode
        self.returncode = None if (hang or stream_error is not None) else returncode
        self.stdout = _FakeStream(stdout, hang=hang, error=stream_error)
        self.stderr = _FakeStream(stderr, hang=hang, error=stream_error)
        self.killed = False

    async def communicate(self):
        raise AssertionError("runner must drain stdout/stderr without communicate()")

    async def wait(self):
        return self._configured_returncode

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
    assert "--pull" in argv and argv[argv.index("--pull") + 1] == "never"
    assert "--name" in argv and argv[argv.index("--name") + 1].startswith("libao-sandbox-")
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
    assert mount.endswith(",readonly")
    assert all(secret not in arg for arg in argv for secret in (".env", ".LiBao", "/var/run/docker.sock"))


@pytest.mark.asyncio
async def test_read_write_workspace_mount_uses_default_rw_without_invalid_flag(monkeypatch, tmp_path):
    from app.tools.sandbox import run_docker_command

    calls = []

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    await run_docker_command(
        SandboxCommand(argv=("bash", "-lc", "pwd"), workspace_access="rw"),
        workspace_root=str(tmp_path),
        timeout_ms=1000,
        settings=_settings(),
    )

    mount = calls[0][calls[0].index("--mount") + 1]
    assert mount.endswith("dst=/workspace")
    assert ",rw" not in mount


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
            return _FakeProcess(hang=True)
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
async def test_timeout_removes_named_container_when_cidfile_is_still_empty(monkeypatch, tmp_path):
    from app.tools.sandbox import run_docker_command

    calls = []

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        if len(argv) > 1 and argv[1] == "run":
            return _FakeProcess(hang=True)
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
    assert len(calls) == 2
    assert calls[1][1:3] == ("rm", "-f")
    assert calls[1][3].startswith("libao-sandbox-")


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
async def test_cancellation_removes_named_container_when_cidfile_is_still_empty(monkeypatch, tmp_path):
    from app.tools.sandbox import run_docker_command

    calls = []
    started = asyncio.Event()

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        if len(argv) > 1 and argv[1] == "run":
            started.set()
            return _FakeProcess(hang=True)
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

    assert len(calls) == 2
    assert calls[1][1:3] == ("rm", "-f")
    assert calls[1][3].startswith("libao-sandbox-")


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


@pytest.mark.asyncio
async def test_stream_reader_discards_after_limit_but_continues_to_eof():
    from app.tools.sandbox import _read_stream_bounded

    class RecordingStream:
        def __init__(self):
            self.chunks = [b"abcd", b"efgh", b""]
            self.reads = 0

        async def read(self, _size):
            self.reads += 1
            return self.chunks.pop(0)

    stream = RecordingStream()
    data, truncated = await _read_stream_bounded(stream, max_bytes=4)

    assert data == b"abcd"
    assert truncated is True
    assert stream.reads == 3


@pytest.mark.asyncio
async def test_large_stdout_and_stderr_are_drained_with_bounded_retention():
    from app.tools.sandbox import _communicate_bounded

    script = "import sys; sys.stdout.write('o' * (2 * 1024 * 1024)); sys.stderr.write('e' * (2 * 1024 * 1024))"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr, truncated = await asyncio.wait_for(_communicate_bounded(process, limit_chars=1024), timeout=10)

    assert len(stdout) <= 65536
    assert len(stderr) <= 65536
    assert truncated is True
    assert process.returncode == 0


@pytest.mark.asyncio
async def test_docker_argv_maps_non_root_linux_uid_gid(monkeypatch, tmp_path):
    import app.tools.sandbox as sandbox
    from app.tools.sandbox import run_docker_command

    calls = []

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return _FakeProcess()

    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    monkeypatch.setattr(sandbox.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(sandbox.os, "getgid", lambda: 1001, raising=False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    await run_docker_command(
        SandboxCommand(argv=("bash", "-lc", "true")),
        workspace_root=str(tmp_path),
        timeout_ms=1000,
        settings=_settings(),
    )

    argv = calls[0]
    assert argv[argv.index("--user") + 1] == "1000:1001"


@pytest.mark.asyncio
async def test_docker_argv_falls_back_to_65532_for_root(monkeypatch, tmp_path):
    import app.tools.sandbox as sandbox
    from app.tools.sandbox import run_docker_command

    calls = []

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return _FakeProcess()

    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    monkeypatch.setattr(sandbox.os, "getuid", lambda: 0, raising=False)
    monkeypatch.setattr(sandbox.os, "getgid", lambda: 0, raising=False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    await run_docker_command(
        SandboxCommand(argv=("bash", "-lc", "true")),
        workspace_root=str(tmp_path),
        timeout_ms=1000,
        settings=_settings(),
    )

    argv = calls[0]
    assert argv[argv.index("--user") + 1] == "65532:65532"


@pytest.mark.asyncio
async def test_docker_argv_falls_back_to_65532_without_posix_ids(monkeypatch, tmp_path):
    import app.tools.sandbox as sandbox
    from app.tools.sandbox import run_docker_command

    calls = []

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return _FakeProcess()

    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    monkeypatch.delattr(sandbox.os, "getuid", raising=False)
    monkeypatch.delattr(sandbox.os, "getgid", raising=False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    await run_docker_command(
        SandboxCommand(argv=("bash", "-lc", "true")),
        workspace_root=str(tmp_path),
        timeout_ms=1000,
        settings=_settings(),
    )

    argv = calls[0]
    assert argv[argv.index("--user") + 1] == "65532:65532"


@pytest.mark.asyncio
async def test_stream_read_failure_kills_cli_and_force_removes_container(monkeypatch, tmp_path):
    from app.tools.sandbox import run_docker_command

    calls = []
    processes = []

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        if len(argv) > 1 and argv[1] == "run":
            process = _FakeProcess(stream_error=OSError("pipe broke"))
        else:
            process = _FakeProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(SandboxFailure) as exc:
        await run_docker_command(
            SandboxCommand(argv=("bash", "-lc", "echo ok")),
            workspace_root=str(tmp_path),
            timeout_ms=1000,
            settings=_settings(),
        )

    assert exc.value.code == SandboxErrorCode.START_FAILED
    assert exc.value.retryable is True
    assert processes[0].killed is True
    assert len(calls) == 2
    assert calls[1][1:3] == ("rm", "-f")
    assert calls[1][3].startswith("libao-sandbox-")


@pytest.mark.asyncio
async def test_force_remove_timeout_kills_cleanup_process_without_masking_original_error(monkeypatch, tmp_path):
    import app.tools.sandbox as sandbox
    from app.tools.sandbox import run_docker_command

    calls = []
    processes = []

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        if len(argv) > 1 and argv[1] == "run":
            process = _FakeProcess(stream_error=OSError("pipe broke"))
        else:
            process = _FakeProcess(hang=True)
        processes.append(process)
        return process

    monkeypatch.setattr(sandbox, "_CLEANUP_TIMEOUT_S", 0.01)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(SandboxFailure) as exc:
        await run_docker_command(
            SandboxCommand(argv=("bash", "-lc", "echo ok")),
            workspace_root=str(tmp_path),
            timeout_ms=1000,
            settings=_settings(),
        )

    assert exc.value.code == SandboxErrorCode.START_FAILED
    assert len(calls) == 2
    assert processes[1].killed is True
