"""tl_install_skill 工具测试（2026-08-25）：下载 skill 到全局/工作区 skills 目录。"""
from __future__ import annotations

from types import SimpleNamespace

import app.tools.builtin.install_skill as install_skill_mod
from app.services import skill as skill_mod
from app.tools.builtin.install_skill import install_skill_handler
from app.tools.context import set_tool_workspace_root

VALID_SKILL = "---\nname: demo\ndescription: 演示\n---\n# 步骤\n"


def _patch_skills_root(monkeypatch, root: str):
    monkeypatch.setattr(skill_mod, "get_settings", lambda: SimpleNamespace(skills_root=str(root)))


def _stub_download(monkeypatch, text: str):
    async def _fake(_url):
        return text

    monkeypatch.setattr(install_skill_mod, "_download_text", _fake)


async def test_install_skill_http_to_global(tmp_path, monkeypatch):
    """http 下载裸 SKILL.md → 落盘全局 skills 目录。"""
    _patch_skills_root(monkeypatch, str(tmp_path))
    _stub_download(monkeypatch, VALID_SKILL)
    out = await install_skill_handler("https://example.com/demo/SKILL.md")
    assert out["skill"] == "demo"
    assert out["target"] == "global"
    dest = tmp_path / "demo" / "SKILL.md"
    assert dest.is_file()
    assert "演示" in dest.read_text(encoding="utf-8")


async def test_install_skill_to_workspace(tmp_path, monkeypatch):
    """target=workspace → 落盘当前工作区 .agent/skills。"""
    _patch_skills_root(monkeypatch, str(tmp_path))
    wdir = tmp_path / "ws"
    set_tool_workspace_root(str(wdir))
    try:
        _stub_download(monkeypatch, VALID_SKILL)
        out = await install_skill_handler("https://example.com/demo/SKILL.md", target="workspace")
        assert out["target"] == "workspace"
        assert (wdir / ".agent" / "skills" / "demo" / "SKILL.md").is_file()
    finally:
        set_tool_workspace_root(None)


async def test_install_skill_workspace_requires_context(tmp_path, monkeypatch):
    """target=workspace 但无工作区上下文 → error。"""
    _patch_skills_root(monkeypatch, str(tmp_path))
    set_tool_workspace_root(None)
    _stub_download(monkeypatch, VALID_SKILL)
    out = await install_skill_handler("https://example.com/demo/SKILL.md", target="workspace")
    assert "error" in out


async def test_install_skill_git_clone(tmp_path, monkeypatch):
    """git 仓库 URL（非 .md）→ 走 clone → 落盘。"""
    _patch_skills_root(monkeypatch, str(tmp_path))

    async def _fake_clone(_url):
        return "---\nname: gitdemo\ndescription: git\n---\n# git\n"

    monkeypatch.setattr(install_skill_mod, "_clone_skill_md", _fake_clone)
    out = await install_skill_handler("https://github.com/x/demo.git")
    assert out["skill"] == "gitdemo"
    assert (tmp_path / "gitdemo" / "SKILL.md").is_file()


async def test_install_skill_invalid_md(tmp_path, monkeypatch):
    """frontmatter 非法 → error，不落盘。"""
    _patch_skills_root(monkeypatch, str(tmp_path))
    _stub_download(monkeypatch, "无 frontmatter")
    out = await install_skill_handler("https://example.com/demo/SKILL.md")
    assert "error" in out


async def test_install_skill_name_traversal_rejected(tmp_path, monkeypatch):
    """frontmatter name 含路径穿越（../）→ 拒绝，不写出 skills_root。"""
    _patch_skills_root(monkeypatch, str(tmp_path))

    async def _evil(_url):
        return "---\nname: ../../evil\ndescription: x\n---\n# x\n"

    monkeypatch.setattr(install_skill_mod, "_download_text", _evil)
    out = await install_skill_handler("https://example.com/e/SKILL.md")
    assert "error" in out
    assert not (tmp_path.parent / "evil").exists()  # 未写出 skills_root 外


async def test_install_skill_missing_url():
    """url 缺失 → error。"""
    assert "error" in await install_skill_handler("")
    assert "error" in await install_skill_handler("   ")


async def test_install_skill_rejects_non_http(tmp_path, monkeypatch):
    """非 http(s) URL（本地路径/file:///git@）→ 拒绝（防 git clone 本地仓库读取/SSRF）。"""
    _patch_skills_root(monkeypatch, str(tmp_path))
    assert "error" in await install_skill_handler("C:/Users/x/some-repo")
    assert "error" in await install_skill_handler("file:///etc/skills")
    assert "error" in await install_skill_handler("git@github.com:x/y.git")
    assert "error" in await install_skill_handler("/home/user/repo")
