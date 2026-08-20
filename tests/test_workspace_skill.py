"""M7-B 工作区 skills：discover_workspace_skills + load_skill 工作区回退。"""
from __future__ import annotations

from app.services.skill import discover_workspace_skills
from app.tools.builtin.load_skill import load_skill_handler
from app.tools.context import set_tool_org, set_tool_workspace_root

VALID_SKILL = """---
name: kb_strategy
description: 当需从知识库检索资料时用。反例：闲聊。
---
# 步骤
1. 调 kb_search 检索。
"""


def test_discover_workspace_skills(tmp_path):
    (tmp_path / "skills" / "kb_strategy").mkdir(parents=True)
    (tmp_path / "skills" / "kb_strategy" / "SKILL.md").write_text(VALID_SKILL, encoding="utf-8")
    # 非法 skill 跳过
    (tmp_path / "skills" / "bad").mkdir(parents=True)
    (tmp_path / "skills" / "bad" / "SKILL.md").write_text("no frontmatter", encoding="utf-8")
    routes = discover_workspace_skills(str(tmp_path))
    assert len(routes) == 1
    assert routes[0]["name"] == "kb_strategy"


async def test_load_skill_workspace_fallback(tmp_path):
    (tmp_path / "skills" / "kb_strategy").mkdir(parents=True)
    (tmp_path / "skills" / "kb_strategy" / "SKILL.md").write_text(VALID_SKILL, encoding="utf-8")
    set_tool_org(None)  # 无 org → 走工作区回退
    set_tool_workspace_root(str(tmp_path))
    try:
        out = await load_skill_handler("kb_strategy")
        assert out["name"] == "kb_strategy"
        assert "# 步骤" in out["body"]
        assert "error" in await load_skill_handler("nope")
    finally:
        set_tool_workspace_root(None)
        set_tool_org(None)
