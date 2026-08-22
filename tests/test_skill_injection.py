"""M7-A skill 注入（路由描述进前缀）+ tl_load_skill 元工具测试。"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.api.schemas.skill import CreateSkillRequest
from app.core.security import hash_password
from app.orchestration.stream_core import build_initial_state, skills_route_section
from app.services.skill import SkillService
from app.storage.db import init_db, set_sessionmaker
from app.storage.file.store import get_store
from app.storage.models import Org, User
from app.tools.builtin import register_builtin_tools
from app.tools.builtin.load_skill import load_skill_handler
from app.tools.context import set_tool_org
from tests.conftest import requires_db

pytestmark = requires_db


def test_skills_route_section_empty():
    assert skills_route_section(None) == ""
    assert skills_route_section([]) == ""


def test_skills_route_section_nonempty():
    sec = skills_route_section([{"name": "kb_strategy", "description": "检索知识库时用"}])
    assert "可用 Skills" in sec
    assert "kb_strategy" in sec
    assert "检索知识库" in sec


def test_build_initial_state_injects_skills():
    agent = SimpleNamespace(
        name="通用助手", model="m", system_prompt="base-prompt", tools=[], max_steps=10, org_id=uuid.uuid4()
    )
    st = build_initial_state(agent, "hi", enabled_skills=[{"name": "s1", "description": "d1"}])
    assert "可用 Skills" in st["agent_config"]["system_prompt"]
    assert "s1" in st["agent_config"]["system_prompt"]
    # 无 skills 零回归：system_prompt 不含路由段
    st2 = build_initial_state(agent, "hi")
    assert "可用 Skills" not in st2["agent_config"]["system_prompt"]
    assert st2["agent_config"]["system_prompt"] == "base-prompt"


def test_build_initial_state_with_workspace():
    """M7-B：工作区对话 → 文件工具注入 + workspace_root + fragment。"""
    agent = SimpleNamespace(
        name="通用助手", model="m", system_prompt="base", tools=["tl_time_now"], max_steps=10, org_id=uuid.uuid4()
    )
    ws = {"id": "ws-1", "root_path": "/tmp/ws1", "system_prompt_fragment": "你是项目助手"}
    st = build_initial_state(agent, "hi", workspace=ws)
    ac = st["agent_config"]
    assert ac["workspace_id"] == "ws-1"
    assert ac["workspace_root"] == "/tmp/ws1"
    assert "项目助手" in ac["system_prompt"]
    for tid in ("tl_read_file", "tl_write_file", "tl_edit_file", "tl_glob", "tl_grep", "tl_bash"):
        assert tid in ac["tools"]
    # 无工作区 → 无 workspace_root / 文件工具
    st2 = build_initial_state(agent, "hi")
    assert st2["agent_config"]["workspace_root"] is None
    assert "tl_bash" not in st2["agent_config"]["tools"]


async def test_load_skill_handler():
    register_builtin_tools()
    engine, sessionmaker = init_db()
    set_sessionmaker(sessionmaker)
    uid = uuid.uuid4().hex[:8]
    try:
        async with get_store().session(sessionmaker) as session:
            org = Org(name=f"测试组织-loadskill-{uid}")
            session.add(org)
            await session.flush()
            user = User(
                username=f"ls_{uid}", password_hash=hash_password("x"), name="L", role="admin", org_id=org.id
            )
            session.add(user)
            await session.commit()
            row = await SkillService().create(
                session, user, CreateSkillRequest(name="kb_strategy", description="d", body="# 步骤")
            )
            await SkillService().set_enabled(session, user, str(row.id), True)

        set_tool_org(str(org.id))
        out = await load_skill_handler("kb_strategy")
        assert out["body"] == "# 步骤"
        assert out["name"] == "kb_strategy"
        # 未启用/缺失 → 降级错误
        assert "error" in await load_skill_handler("nope")
    finally:
        set_tool_org(None)
        set_sessionmaker(None)
        await engine.dispose()
