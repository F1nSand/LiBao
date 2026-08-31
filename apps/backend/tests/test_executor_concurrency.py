"""M4 完整版：ToolSpec.max_concurrency 信号量测试——并发 N 调时同时执行数 ≤ max_concurrency。"""
from __future__ import annotations

import asyncio

from app.tools import executor
from app.tools.registry import ToolSpec, register, unregister


async def test_max_concurrency_limits_concurrent_executions():
    running = 0
    peak = 0

    async def slow_handler() -> str:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.2)
        running -= 1
        return "done"

    spec = ToolSpec(
        id="tl_conc_test", name="conc_test", description="并发测试工具", handler=slow_handler,
        max_concurrency=2, timeout_ms=5000,
    )
    register(spec)
    try:
        results = await asyncio.gather(*[executor.execute(spec, {}) for _ in range(5)])
        assert all(r.ok for r in results)
        assert peak <= 2, f"并发超过 max_concurrency=2，观测 peak={peak}"
        assert peak == 2, f"期望有并发（peak=2），观测 peak={peak}（可能是串行限流）"
    finally:
        unregister(spec.id)
        executor._SEMAPHORES.pop(spec.id, None)  # 清理信号量，防跨测试串扰


async def test_max_concurrency_one_serializes():
    running = 0
    peak = 0

    async def slow_handler() -> str:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.1)
        running -= 1
        return "done"

    spec = ToolSpec(
        id="tl_conc_one", name="conc_one", description="并发串行测试工具", handler=slow_handler,
        max_concurrency=1, timeout_ms=5000,
    )
    register(spec)
    try:
        results = await asyncio.gather(*[executor.execute(spec, {}) for _ in range(3)])
        assert all(r.ok for r in results)
        assert peak == 1  # max_concurrency=1 → 严格串行
    finally:
        unregister(spec.id)
        executor._SEMAPHORES.pop(spec.id, None)
