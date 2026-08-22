"""M7-B T7a/T8 重定位：`.agent/` 目录机制（skills 发现迁移 + agent.md/memory/knowledge 注入）。"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.orchestration.stream_core import build_initial_state
from app.services.skill import discover_workspace_agent, discover_workspace_skills
from app.services.workspace import init_agent_skeleton


def _write_skill(root, name, description, content="body", skills_dir=".agent/skills"):
    d = root / skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{content}", encoding="utf-8"
    )


def test_discover_workspace_skills_dot_agent(tmp_path):
    _write_skill(tmp_path, "s1", "d1")
    routes = discover_workspace_skills(str(tmp_path))
    assert [r["name"] for r in routes] == ["s1"]


def test_discover_workspace_skills_legacy_compat(tmp_path):
    _write_skill(tmp_path, "legacy", "d", skills_dir="skills")
    routes = discover_workspace_skills(str(tmp_path))
    assert [r["name"] for r in routes] == ["legacy"]


def test_discover_workspace_skills_dot_agent_priority(tmp_path):
    """同名 skill 同时存在于 .agent/ 与旧 skills/ → .agent/ 优先（项目级覆盖）。"""
    _write_skill(tmp_path, "dup", "dot-agent", skills_dir=".agent/skills")
    _write_skill(tmp_path, "dup", "legacy", skills_dir="skills")
    routes = discover_workspace_skills(str(tmp_path))
    assert len(routes) == 1
    assert routes[0]["description"] == "dot-agent"


def test_discover_workspace_agent(tmp_path):
    _write_skill(tmp_path, "s1", "d1")
    (tmp_path / ".agent" / "agent.md").write_text("# 约定", encoding="utf-8")
    (tmp_path / ".agent" / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".agent" / "memory" / "facts.md").write_text("事实 A", encoding="utf-8")
    (tmp_path / ".agent" / "knowledge").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".agent" / "knowledge" / "domain.md").write_text("领域知识 B", encoding="utf-8")
    ov = discover_workspace_agent(str(tmp_path))
    assert [s["name"] for s in ov["skills"]] == ["s1"]
    assert ov["agent_md"] == "# 约定"
    assert ov["memory"] == [{"name": "facts", "content": "事实 A"}]
    assert ov["knowledge"] == [{"name": "domain", "content": "领域知识 B"}]


def test_discover_workspace_agent_no_dot_agent(tmp_path):
    assert discover_workspace_agent(str(tmp_path)) == {"skills": [], "agent_md": "", "memory": [], "knowledge": []}


def test_init_agent_skeleton(tmp_path):
    init_agent_skeleton(tmp_path)
    agent_dir = tmp_path / ".agent"
    assert (agent_dir / "agent.md").is_file()
    assert (agent_dir / "README.md").is_file()
    for sub in ("skills", "memory", "knowledge"):
        assert (agent_dir / sub).is_dir()
    # 幂等：再跑一次不覆盖用户已改的 agent.md
    (agent_dir / "agent.md").write_text("custom", encoding="utf-8")
    init_agent_skeleton(tmp_path)
    assert (agent_dir / "agent.md").read_text(encoding="utf-8") == "custom"


def _agent():
    return SimpleNamespace(
        name="通用助手", model="m", system_prompt="base", tools=["tl_time_now"], max_steps=10, org_id=uuid.uuid4()
    )


def test_build_initial_state_injects_dot_agent():
    ws = {
        "id": "ws-1",
        "root_path": "/tmp/ws1",
        "system_prompt_fragment": "项目助手",
        "skills": [{"name": "s1", "description": "d1"}],
        "agent_md": "# 项目约定内容",
        "memory": [{"name": "facts", "content": "事实 A"}],
        "knowledge": [{"name": "domain", "content": "知识 B"}],
    }
    sp = build_initial_state(_agent(), "hi", workspace=ws)["agent_config"]["system_prompt"]
    assert "[项目约定]" in sp and "项目约定内容" in sp
    assert "[项目记忆]" in sp and "事实 A" in sp
    assert "[项目知识]" in sp and "知识 B" in sp
    assert "项目助手" in sp


def test_build_initial_state_project_skill_overrides_global():
    ws = {"id": "ws-1", "root_path": "/tmp/ws1", "skills": [{"name": "s1", "description": "项目级描述"}]}
    sp = build_initial_state(
        _agent(), "hi", enabled_skills=[{"name": "s1", "description": "全局描述"}], workspace=ws
    )["agent_config"]["system_prompt"]
    assert "项目级描述" in sp
    assert "全局描述" not in sp
    assert sp.count("s1") == 1  # 同名去重，只出现一次
