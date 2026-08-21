"""M7-B 文件操作工具测试：路径强限制 + read/write/edit/glob/grep + bash 审查。"""
from __future__ import annotations

import pytest

from app.core.errors import AppError
from app.tools.builtin import file_ops
from app.tools.context import set_tool_workspace_root
from app.tools.filesystem import resolve_workspace_path


def test_resolve_workspace_path_within(tmp_path):
    p = resolve_workspace_path(tmp_path, "a/b.txt")
    assert str(p) == str((tmp_path / "a/b.txt").resolve())


def test_resolve_workspace_path_escape(tmp_path):
    with pytest.raises(AppError) as exc:
        resolve_workspace_path(tmp_path, "../etc/passwd")
    assert exc.value.code == 40302


def test_resolve_workspace_path_absolute(tmp_path):
    with pytest.raises(AppError) as exc:
        resolve_workspace_path(tmp_path, "/etc/passwd")
    assert exc.value.code == 40302


async def test_file_ops_roundtrip(tmp_path):
    set_tool_workspace_root(str(tmp_path))
    try:
        await file_ops.write_file_handler("notes.md", "hello\nworld\n")
        out = await file_ops.read_file_handler("notes.md")
        assert "hello" in out["content"]
        await file_ops.edit_file_handler("notes.md", "world", "there")
        out2 = await file_ops.read_file_handler("notes.md")
        assert "there" in out2["content"]
        g = await file_ops.glob_handler("*.md")
        assert "notes.md" in g["matches"]
        r = await file_ops.grep_handler("there")
        assert r["matches"] and r["matches"][0]["file"] == "notes.md"
        # 路径逃逸 → 降级错误
        assert "error" in await file_ops.read_file_handler("../etc/passwd")
    finally:
        set_tool_workspace_root(None)


async def test_bash_review_block(tmp_path, monkeypatch):
    set_tool_workspace_root(str(tmp_path))
    try:
        async def _block(_cmd):
            return {"verdict": "block", "reason": "破坏性删除"}

        monkeypatch.setattr(file_ops, "_review_command", _block)
        out = await file_ops.bash_handler("rm -rf /")
        assert out["verdict"] == "block"
        assert "审查拦截" in out["error"]
    finally:
        set_tool_workspace_root(None)


async def test_bash_review_allow_exec(tmp_path, monkeypatch):
    set_tool_workspace_root(str(tmp_path))
    try:
        async def _allow(_cmd):
            return {"verdict": "allow", "reason": ""}

        monkeypatch.setattr(file_ops, "_review_command", _allow)
        out = await file_ops.bash_handler("echo hi")
        assert out["returncode"] == 0
        assert "hi" in out["stdout"]
    finally:
        set_tool_workspace_root(None)


async def test_bash_no_workspace():
    set_tool_workspace_root(None)
    out = await file_ops.bash_handler("echo hi")
    assert "不在工作区" in out["error"]


async def test_bash_silent_success_note(tmp_path, monkeypatch):
    """C 方案：退出码 0 但无 stdout/stderr → 附 note 提示可能未真正执行。"""
    set_tool_workspace_root(str(tmp_path))
    try:
        async def _allow(_cmd):
            return {"verdict": "allow", "reason": ""}

        monkeypatch.setattr(file_ops, "_review_command", _allow)

        class _Silent:
            stdout = ""
            stderr = ""
            returncode = 0

        async def _fake_run(_cmd, _workdir):
            return _Silent()

        monkeypatch.setattr(file_ops, "_run_shell", _fake_run)

        out = await file_ops.bash_handler("some-silent-cmd")
        assert out["returncode"] == 0
        assert out["stdout"] == ""
        assert "note" in out
        assert "未真正执行" in out["note"]
    finally:
        set_tool_workspace_root(None)


async def test_bash_multiline_python_c(tmp_path, monkeypatch):
    """A 方案回归：Windows 走 Git Bash 后，多行 -c 脚本正确执行（cmd 双引号不跨行会拆散）。"""
    if file_ops._bash_executable() is None:
        pytest.skip("Git Bash 不可用，跳过 A 方案回归")
    set_tool_workspace_root(str(tmp_path))
    try:
        async def _allow(_cmd):
            return {"verdict": "allow", "reason": ""}

        monkeypatch.setattr(file_ops, "_review_command", _allow)
        # bash 双引号可跨行：整个多行脚本作为单一 -c 参数传给 python
        cmd = 'python -c "\nprint(\'AAA\')\nprint(\'BBB\')\n"'
        out = await file_ops.bash_handler(cmd)
        assert out["returncode"] == 0, out
        assert "AAA" in out["stdout"] and "BBB" in out["stdout"], out
    finally:
        set_tool_workspace_root(None)
