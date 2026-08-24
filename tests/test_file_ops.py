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


# ---- M8.1 阶段 A：bash 环境修复（2026-08-24）----


def test_bash_executable_prefers_git_bash_over_wsl(monkeypatch):
    """which 命中 System32\\bash.exe（WSL 中继）时必须排除——曾致工作区 bash 全挂。"""
    file_ops._bash_executable.cache_clear()
    monkeypatch.setattr(file_ops.shutil, "which", lambda _: r"C:\Windows\System32\bash.exe")
    got = file_ops._bash_executable()
    if got is None:  # 本机无 Git Bash（CI 环境）→ 跳过
        pytest.skip("Git Bash 不可用")
    assert "System32" not in got and "Program Files" in got


def test_bash_executable_fallback_when_no_git_bash(monkeypatch, tmp_path):
    file_ops._bash_executable.cache_clear()
    monkeypatch.setattr(file_ops.shutil, "which", lambda _: None)
    monkeypatch.setattr(file_ops, "_BASH_CANDIDATES", (str(tmp_path / "nonexistent.exe"),))
    assert file_ops._bash_executable() is None


def test_fast_review_rules():
    assert file_ops._fast_review("ls -la") == "allow"
    assert file_ops._fast_review("cat notes.md") == "allow"
    assert file_ops._fast_review("git status") == "allow"
    assert file_ops._fast_review("git diff HEAD") == "allow"
    assert file_ops._fast_review("git push origin main") == "block"
    assert file_ops._fast_review("rm -rf tmp") == "block"
    assert file_ops._fast_review("printenv HOME") == "block"
    assert file_ops._fast_review("git reset --hard") == "block"
    assert file_ops._fast_review("echo hi && ls") is None  # 含元字符 → LLM 审查
    assert file_ops._fast_review('python -c "print(1)"') is None  # 非只读 → LLM 审查
    assert file_ops._fast_review("git checkout -- a.py") is None  # git 写操作 → LLM 审查


def test_review_command_extracts_blocks_content(monkeypatch):
    """DeepSeek v4-flash content blocks 列表 → message_text 提取（str() 会取到 repr）。"""

    class _FakeModel:
        async def ainvoke(self, _msgs):
            class _Resp:
                content = [{"type": "thinking", "text": "推理"}, "ALLOW 只读命令"]

            return _Resp()

    monkeypatch.setattr(file_ops.LLMService, "build_model", lambda _m: _FakeModel())
    import asyncio

    async def _run():
        return await file_ops._review_command("ls -la")

    r = asyncio.run(_run())
    assert r["verdict"] == "allow"


async def test_bash_wsl_error_hint(tmp_path, monkeypatch):
    """非零退出 + stderr 含 WSL 错误 → 附 hint（杜绝「环境坏了」误判）。"""
    set_tool_workspace_root(str(tmp_path))
    try:
        async def _allow(_cmd):
            return {"verdict": "allow", "reason": ""}

        monkeypatch.setattr(file_ops, "_review_command", _allow)

        class _WslFail:
            stdout = ""
            stderr = "<3>WSL (9 - Relay) ERROR: execvpe(/bin/bash) failed: No such file or directory\n"
            returncode = 1

        async def _fake_run(_cmd, _workdir):
            return _WslFail()

        monkeypatch.setattr(file_ops, "_run_shell", _fake_run)
        out = await file_ops.bash_handler("ls -la")
        assert out["returncode"] == 1
        assert "hint" in out and "WSL" in out["hint"]
    finally:
        set_tool_workspace_root(None)


# ---- M8.1 阶段 D：回滚备份（2026-08-24）----


async def test_write_backup_and_undo(tmp_path):
    """write 覆盖旧版 → 自动备份 + note 提示；undo_file 恢复最近一份。"""
    set_tool_workspace_root(str(tmp_path))
    try:
        await file_ops.write_file_handler("a.md", "v1")
        out = await file_ops.write_file_handler("a.md", "v2")
        assert "note" in out and "undo_file" in out["note"]  # 覆盖旧版 → 提示可撤销
        undo_dir = tmp_path / ".agent" / ".undo"
        assert len(list(undo_dir.glob("*.bak"))) == 1
        r = await file_ops.undo_file_handler("a.md")
        assert r["restored"] is True
        content = await file_ops.read_file_handler("a.md")
        assert content["content"] == "v1"
        # 恢复本身也可逆（恢复前备份当前 v2）
        await file_ops.undo_file_handler("a.md")
        content2 = await file_ops.read_file_handler("a.md")
        assert content2["content"] == "v2"
    finally:
        set_tool_workspace_root(None)


async def test_edit_backup_and_undo(tmp_path):
    set_tool_workspace_root(str(tmp_path))
    try:
        await file_ops.write_file_handler("b.md", "hello world")
        await file_ops.edit_file_handler("b.md", "world", "there")
        r = await file_ops.undo_file_handler("b.md")
        assert r["restored"] is True
        content = await file_ops.read_file_handler("b.md")
        assert content["content"] == "hello world"
    finally:
        set_tool_workspace_root(None)


async def test_undo_no_backup(tmp_path):
    """新建文件无备份 → 明确错误（不静默）。"""
    set_tool_workspace_root(str(tmp_path))
    try:
        await file_ops.write_file_handler("c.md", "v1")  # 新建不备份
        r = await file_ops.undo_file_handler("c.md")
        assert "error" in r and "没有可恢复的备份" in r["error"]
    finally:
        set_tool_workspace_root(None)


async def test_undo_backup_cap(tmp_path):
    """备份上限 _UNDO_KEEP_MAX：超限清最旧。"""
    set_tool_workspace_root(str(tmp_path))
    try:
        await file_ops.write_file_handler("d.md", "v0")
        for i in range(file_ops._UNDO_KEEP_MAX + 5):
            await file_ops.write_file_handler("d.md", f"v{i + 1}")
        undo_dir = tmp_path / ".agent" / ".undo"
        assert len(list(undo_dir.glob("*.bak"))) <= file_ops._UNDO_KEEP_MAX
    finally:
        set_tool_workspace_root(None)
