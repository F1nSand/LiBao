"""Docker 沙箱命令契约测试（Task 2：只验证输入边界，不启动 Docker）。"""
from __future__ import annotations

import pytest

from app.tools.sandbox import SandboxCommand, SandboxErrorCode, SandboxFailure


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
