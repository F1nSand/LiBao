"""首启种子测试：seed_if_first_run 幂等（首次落盘 16 工具 + 栗包 agent；二次跳过）。"""
from __future__ import annotations

from app.seed import seed_if_first_run
from app.storage.file.store import get_store


async def test_seed_first_run_creates_data():
    store = get_store()
    assert await seed_if_first_run(store) is True  # 首次
    tools = await store.table("tool_definitions").list()
    assert len(tools) == 16  # 16 个内置工具
    enabled = [t for t in tools if t.enabled]
    assert len(enabled) == 12  # 12 个默认启用（联网/视觉默认关）
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
    assert len(await store.table("tool_definitions").list()) == 16  # 不翻倍
