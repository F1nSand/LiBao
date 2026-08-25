"""M7-A skill 注入（路由描述进前缀）+ tl_load_skill 元工具 + 全局 skills（2026-08-25 两级简化）。"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

from app.orchestration.stream_core import build_initial_state, skills_route_section
from app.services import skill as skill_mod
from app.services.skill import discover_global_skills
from app.tools.builtin.load_skill import load_skill_handler
from app.tools.context import set_tool_workspace_root


def _write_skill(skills_root: Path, name: str, description: str, body: str) -> Path:
    p = skills_root / name / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}\n", encoding="utf-8")
    return p


def _patch_skills_root(monkeypatch, root: str):
    """把全局 skills 根目录指到临时目录（global_skills_dir 经 skill 模块的 get_settings 解析）。"""
    monkeypatch.setattr(skill_mod, "get_settings", lambda: SimpleNamespace(skills_root=str(root)))


def test_skills_route_section_empty():
    assert skills_route_section(None) == ""
    assert skills_route_section([]) == ""


def test_global_skills_dir_expanduser(monkeypatch):
    """默认 skills_root="~/.LiBao/skills" → expanduser 解析到用户主目录（打包后安装根）。"""
    monkeypatch.setattr(skill_mod, "get_settings", lambda: SimpleNamespace(skills_root="~/.LiBao/skills"))
    from app.services.skill import global_skills_dir

    assert str(global_skills_dir()) == str(Path.home() / ".LiBao" / "skills")


def test_skills_route_section_nonempty():
    sec = skills_route_section([{"name": "kb_strategy", "description": "检索知识库时用"}])
    assert "可用 Skills" in sec
    assert "kb_strategy" in sec
    assert "检索知识库" in sec


def test_build_initial_state_no_skills_overlay_none(tmp_path, monkeypatch):
    """全局无 skills → project_overlay 为 None + system_prompt 恒定（零回归，前缀缓存铁律）。"""
    _patch_skills_root(monkeypatch, str(tmp_path))
    agent = SimpleNamespace(
        name="通用助手", model="m", system_prompt="base", tools=[], max_steps=10, org_id=uuid.uuid4()
    )
    st = build_initial_state(agent, "hi")
    assert st["project_overlay"] is None
    assert st["agent_config"]["system_prompt"] == "base"


def test_build_initial_state_injects_global_skills(tmp_path, monkeypatch):
    """主 agent 也能看到全局 skills 路由（放文件夹即自动识别 + 渐进披露）。"""
    _write_skill(tmp_path, "demo", "演示 skill", "# 步骤")
    _patch_skills_root(monkeypatch, str(tmp_path))
    agent = SimpleNamespace(
        name="通用助手", model="m", system_prompt="base", tools=[], max_steps=10, org_id=uuid.uuid4()
    )
    st = build_initial_state(agent, "hi")
    assert "可用 Skills" in st["project_overlay"]
    assert "demo" in st["project_overlay"]
    assert st["agent_config"]["system_prompt"] == "base"


def test_build_initial_state_with_workspace():
    """M7-B：工作区对话 → 文件工具注入 + workspace_root + fragment。"""
    agent = SimpleNamespace(
        name="通用助手", model="m", system_prompt="base", tools=["tl_time_now"], max_steps=10, org_id=uuid.uuid4()
    )
    ws = {"id": "ws-1", "root_path": "/tmp/ws1", "project_instructions": "你是项目助手"}
    st = build_initial_state(agent, "hi", workspace=ws)
    ac = st["agent_config"]
    assert ac["workspace_id"] == "ws-1"
    assert ac["workspace_root"] == "/tmp/ws1"
    assert ac["system_prompt"] == "base"  # system_prompt 恒定；工作区 fragment 走消息通道
    assert "项目助手" in st["project_overlay"]
    for tid in ("tl_read_file", "tl_write_file", "tl_edit_file", "tl_glob", "tl_grep", "tl_bash"):
        assert tid in ac["tools"]
    # 无工作区 → 无 workspace_root / 文件工具
    st2 = build_initial_state(agent, "hi")
    assert st2["agent_config"]["workspace_root"] is None
    assert "tl_bash" not in st2["agent_config"]["tools"]


def test_discover_global_skills(tmp_path):
    """全局 skills 目录自动发现；非法 SKILL.md 跳过。"""
    _write_skill(tmp_path, "demo", "演示 skill", "# 步骤")
    (tmp_path / "bad" / "SKILL.md").parent.mkdir(parents=True)
    (tmp_path / "bad" / "SKILL.md").write_text("无 frontmatter", encoding="utf-8")
    routes = discover_global_skills(tmp_path)
    assert routes == [{"name": "demo", "description": "演示 skill", "path": "skills/demo/SKILL.md"}]


def test_discover_global_skills_skips_bad_files(tmp_path):
    """非 UTF-8 / 目录名与 frontmatter 不一致的 SKILL.md 跳过（不崩、不产生悬空路由）。"""
    _write_skill(tmp_path, "good", "正常", "# 步骤")
    (tmp_path / "gbk" / "SKILL.md").parent.mkdir(parents=True)
    (tmp_path / "gbk" / "SKILL.md").write_bytes("---\nname: gbk\ndescription: 中文\n---\n".encode("gbk"))
    (tmp_path / "mismatch" / "SKILL.md").parent.mkdir(parents=True)
    (tmp_path / "mismatch" / "SKILL.md").write_text(
        "---\nname: other\ndescription: 不一致\n---\n# x\n", encoding="utf-8"
    )
    routes = discover_global_skills(tmp_path)
    assert [r["name"] for r in routes] == ["good"]


def test_discover_global_skills_bom(tmp_path):
    """带 BOM（utf-8-sig）的 SKILL.md 正常识别（Windows 从第三方复制的 md 常见）。"""
    p = _write_skill(tmp_path, "bom", "带 BOM", "# 步骤")
    p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
    routes = discover_global_skills(tmp_path)
    assert [r["name"] for r in routes] == ["bom"]


async def test_load_skill_global_fallback(tmp_path, monkeypatch):
    """无 org/工作区 → 全局 skills 命中；缺失 → 降级错误。"""
    _write_skill(tmp_path, "demo", "演示", "全局正文")
    _patch_skills_root(monkeypatch, str(tmp_path))
    out = await load_skill_handler("demo")
    assert out["body"] == "全局正文"
    assert "error" in await load_skill_handler("nope")


async def test_load_skill_workspace_over_global(tmp_path, monkeypatch):
    """两级优先级：同名 skill 工作区覆盖全局。"""
    gdir = tmp_path / "global"
    _write_skill(gdir, "demo", "全局", "全局正文")
    wdir = tmp_path / "ws"
    _write_skill(wdir / ".agent" / "skills", "demo", "工作区", "工作区正文")
    _patch_skills_root(monkeypatch, str(gdir))
    set_tool_workspace_root(str(wdir))
    try:
        out = await load_skill_handler("demo")
        assert out["body"] == "工作区正文"
    finally:
        set_tool_workspace_root(None)


async def test_load_skill_workspace_before_global_missing(tmp_path, monkeypatch):
    """工作区无同名 → 回退全局。"""
    gdir = tmp_path / "global"
    _write_skill(gdir, "demo", "全局", "全局正文")
    wdir = tmp_path / "ws"
    _write_skill(wdir / ".agent" / "skills", "other", "工作区", "other 正文")
    _patch_skills_root(monkeypatch, str(gdir))
    set_tool_workspace_root(str(wdir))
    try:
        out = await load_skill_handler("demo")
        assert out["body"] == "全局正文"
    finally:
        set_tool_workspace_root(None)
