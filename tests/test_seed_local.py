"""首启种子测试：seed_if_first_run 幂等（首次落盘 19 工具 + 栗包 agent；二次跳过）+ 升级合并。"""
from __future__ import annotations

from app.seed import ensure_seed_tools, seed_if_first_run
from app.storage.file.store import get_store


async def test_seed_first_run_creates_data():
    store = get_store()
    assert await seed_if_first_run(store) is True  # 首次
    tools = await store.table("tool_definitions").list()
    assert len(tools) == 19  # 16 个内置工具 + 3 个主动记忆工具
    enabled = [t for t in tools if t.enabled]
    assert len(enabled) == 15  # 12 个默认启用 + remember/recall/forget（联网/视觉默认关）
    agents = await store.table("agents").list()
    assert len(agents) == 1
    agent = agents[0]
    assert agent.name == "通用助手"
    assert agent.is_default is True
    assert agent.status == "published"
    versions = await store.table("agent_versions").list()
    assert len(versions) == 1
    assert versions[0].prefix_hash  # 快照 prefix_hash 已计算


async def test_seed_idempotent_second_run_skips():
    store = get_store()
    await seed_if_first_run(store)
    assert await seed_if_first_run(store) is False  # 二次跳过
    assert len(await store.table("tool_definitions").list()) == 19  # 不翻倍


async def test_ensure_seed_tools_upgrades_legacy_env():
    """老数据环境（已 seed 但缺新工具）：ensure_seed_tools 补齐工具行 + agent.tools（幂等）。"""
    store = get_store()
    await seed_if_first_run(store)
    # 模拟老环境：删掉 3 个记忆工具行 + 从 agent.tools 移除
    tools = await store.table("tool_definitions").list()
    for t in tools:
        if t.name in ("remember_memory", "recall_memory", "forget_memory"):
            store.table("tool_definitions").delete_row(t)
    agent = (await store.table("agents").list())[0]
    agent.tools = [
        tid for tid in agent.tools
        if tid not in ("tl_remember_memory", "tl_recall_memory", "tl_forget_memory")
    ]
    from app.storage.file.store import FileContext

    await FileContext(store).commit()
    assert len(await store.table("tool_definitions").list()) == 16
    # 升级合并：补齐 3 行 + 3 个工具 id
    await ensure_seed_tools(store)
    assert len(await store.table("tool_definitions").list()) == 19
    agent2 = (await store.table("agents").list())[0]
    for tid in ("tl_remember_memory", "tl_recall_memory", "tl_forget_memory"):
        assert tid in agent2.tools
    # 幂等：再跑一遍不重复
    await ensure_seed_tools(store)
    assert len(await store.table("tool_definitions").list()) == 19
    assert len(agent2.tools) == 21  # AGENT_TOOLS 精选工具总数（含 2026-08-25 新增 tl_install_skill）


async def test_ensure_seed_tools_upgrades_engineering_prompt():
    """老 seed prompt（缺工程工作流引导，含旧尾部标记）→ ensure_seed_tools 升级为 AGENT_SYSTEM_PROMPT（幂等）。"""
    from app.seed import AGENT_SYSTEM_PROMPT

    store = get_store()
    await seed_if_first_run(store)
    agent = (await store.table("agents").list())[0]
    # 模拟旧版 prompt：工程引导被移除，其余保持 seed 基线（含旧尾部标记）
    agent.system_prompt = agent.system_prompt.replace("工程/代码任务工作流", "旧版无工程引导")
    from app.storage.file.store import FileContext

    await FileContext(store).commit()
    assert "工程/代码任务工作流" not in agent.system_prompt

    await ensure_seed_tools(store)
    agent2 = (await store.table("agents").list())[0]
    assert "工程/代码任务工作流" in agent2.system_prompt
    assert agent2.system_prompt == AGENT_SYSTEM_PROMPT
    # 幂等：再跑不重复改写
    await ensure_seed_tools(store)
    agent3 = (await store.table("agents").list())[0]
    assert agent3.system_prompt == AGENT_SYSTEM_PROMPT
