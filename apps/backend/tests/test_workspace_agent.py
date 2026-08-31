"""M7-B T7a/T8 重定位：`.agent/` 目录机制（skills 发现迁移 + agent.md/memory/knowledge 注入）。"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

from app.orchestration.stream_core import build_initial_state
from app.services import skill as skill_mod
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
    # P3：memory/knowledge 只返回索引（title 优先 frontmatter，summary = 正文首行），正文不进内存
    assert ov["memory"] == [{"name": "facts", "title": "facts", "summary": "事实 A"}]
    assert ov["knowledge"] == [{"name": "domain", "title": "domain", "summary": "领域知识 B"}]


def test_discover_workspace_agent_frontmatter_title(tmp_path):
    """带 frontmatter 的项目记忆 md → 索引 title 取 frontmatter.title。"""
    (tmp_path / ".agent" / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".agent" / "memory" / "arch.md").write_text(
        "---\ntitle: 架构决策\ntopic_key: arch\n---\n\n决定用 FastAPI。", encoding="utf-8"
    )
    ov = discover_workspace_agent(str(tmp_path))
    assert ov["memory"] == [{"name": "arch", "title": "架构决策", "summary": "决定用 FastAPI。"}]


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
    """前缀缓存铁律：system_prompt 恒为 agent.system_prompt；工作区叠加走消息通道 project_overlay。
    项目记忆/知识只进 project_memory_index（消息通道），绝不拼 system_prompt。"""
    ws = {
        "id": "ws-1",
        "root_path": "/tmp/ws1",
        "project_instructions": "项目助手",
        "skills": [{"name": "s1", "description": "d1"}],
        "agent_md": "# 项目约定内容",
        "memory": [{"name": "facts", "title": "事实", "summary": "事实 A"}],
        "knowledge": [{"name": "domain", "title": "领域", "summary": "知识 B"}],
    }
    state = build_initial_state(_agent(), "hi", workspace=ws)
    sp = state["agent_config"]["system_prompt"]
    # system_prompt 逐字节恒定（跨会话前缀缓存共享的前提）
    assert sp == "base"
    assert "[项目约定]" not in sp and "项目约定内容" not in sp
    assert "项目助手" not in sp and "可用 Skills" not in sp
    # 工作区/项目级叠加走消息通道 project_overlay
    ov = state["project_overlay"]
    assert "[工作区]" in ov and "项目助手" in ov
    assert "[项目约定]" in ov and "项目约定内容" in ov
    assert "s1: d1" in ov
    # 铁律断言：project_overlay 不含任何记忆/知识内容与文件名
    assert "[项目记忆]" not in ov and "事实 A" not in ov and "facts" not in ov
    assert "[项目知识]" not in ov and "知识 B" not in ov and "domain" not in ov
    # 索引走 state 字段（context_builder 渲染为尾部 SystemMessage）
    idx = state["project_memory_index"]
    assert "[项目记忆]" in idx and "事实: 事实 A" in idx
    assert "[项目知识]" in idx and "领域: 知识 B" in idx


def test_build_context_renders_project_index_after_history():
    """project_memory_index 渲染为历史后 SystemMessage（消息通道，非 system prompt）。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.orchestration.context_builder import build_context

    state = {
        "agent_config": {"system_prompt": "base", "tools": []},
        "messages": [HumanMessage(content="hi")],
        "project_memory_index": "[项目记忆]\n- 事实: 事实 A",
    }
    msgs = build_context(state)
    assert msgs[0].content == "base"  # system prompt 原样
    sys_msgs = [m for m in msgs[1:] if isinstance(m, SystemMessage)]
    assert any("项目记忆" in m.content for m in sys_msgs)
    human_idx = next(i for i, m in enumerate(msgs) if isinstance(m, HumanMessage))
    assert any(isinstance(m, SystemMessage) and "项目记忆" in m.content for m in msgs[human_idx + 1 :])


def test_build_initial_state_project_skill_overrides_global(tmp_path, monkeypatch):
    """同名 skill：工作区覆盖全局（注入去重，只出现一次）。"""
    (tmp_path / "s1" / "SKILL.md").parent.mkdir(parents=True)
    (tmp_path / "s1" / "SKILL.md").write_text(
        "---\nname: s1\ndescription: 全局描述\n---\n# g\n", encoding="utf-8"
    )
    monkeypatch.setattr(skill_mod, "get_settings", lambda: SimpleNamespace(skills_root=str(tmp_path)))
    ws = {"id": "ws-1", "root_path": "/tmp/ws1", "skills": [{"name": "s1", "description": "项目级描述"}]}
    ov = build_initial_state(_agent(), "hi", workspace=ws)["project_overlay"]
    assert "项目级描述" in ov
    assert "全局描述" not in ov
    assert ov.count("s1") == 1  # 同名去重，只出现一次


def test_build_context_renders_project_overlay_after_history():
    """project_overlay（工作区/项目约定/skills 路由）渲染为历史后 SystemMessage，system_prompt 原样。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.orchestration.context_builder import build_context

    state = {
        "agent_config": {"system_prompt": "base", "tools": []},
        "messages": [HumanMessage(content="hi")],
        "project_overlay": "[工作区]\n项目助手\n\n[项目约定]\n规则 X",
    }
    msgs = build_context(state)
    assert msgs[0].content == "base"  # system prompt 原样
    human_idx = next(i for i, m in enumerate(msgs) if isinstance(m, HumanMessage))
    assert any(isinstance(m, SystemMessage) and "项目约定" in m.content for m in msgs[human_idx + 1 :])


def test_session_workspace_injects_file_tools(tmp_path, monkeypatch):
    """方案 A（2026-08-25）：非工作区对话 → 隐式临时工作区（文件工具注入 + root 指向 cache/sessions/<conv_id>）。"""
    from app.api.routers.chat import _session_workspace

    monkeypatch.setattr(
        "app.api.routers.chat.get_settings", lambda: SimpleNamespace(cache_dir=str(tmp_path / "cache"))
    )
    monkeypatch.setattr(skill_mod, "get_settings", lambda: SimpleNamespace(skills_root=str(tmp_path / "no_skills")))
    ws = _session_workspace("conv-1")
    assert ws["id"] is None
    assert ws["root_path"] == str(tmp_path / "cache" / "sessions" / "conv-1")
    assert Path(ws["root_path"]).is_dir()  # 临时目录已建
    assert ws["project_instructions"] == ""  # 不注入 [工作区] overlay
    st = build_initial_state(
        _agent(), "hi", workspace=ws
    )
    ac = st["agent_config"]
    assert ac["workspace_root"] == ws["root_path"]
    for tid in ("tl_shell", "tl_read_file", "tl_write_file"):
        assert tid in ac["tools"]
    # 无 skills/项目 overlay（隐式工作区不叠加）
    assert "可用 Skills" not in (st["project_overlay"] or "")


def test_build_initial_state_model_falls_back_to_settings(monkeypatch):
    """模型切换去固化（2026-08-27）：agent.model 为空 → 回落 settings.llm_model（激活 provider 值）。"""
    from app.orchestration import stream_core

    monkeypatch.setattr(
        stream_core, "get_settings", lambda: SimpleNamespace(llm_model="deepseek-chat", llm_vision_declared=None)
    )
    agent = SimpleNamespace(
        name="通用助手", model="", system_prompt="base", tools=[], max_steps=10, org_id=uuid.uuid4()
    )
    st = build_initial_state(agent, "hi", workspace=None)
    assert st["agent_config"]["model"] == "deepseek-chat"
