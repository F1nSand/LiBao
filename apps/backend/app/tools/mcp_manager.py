"""MCP 连接管理器（《02》后端设计 §7.2 / I7 熔断 / M4 完整版会话复用）。

进程级单例：server_id → 常驻 owner-task 池 + 熔断器（连续失败达阈值 → OPEN，冷却后
HALF_OPEN 放行一次，成功复位 / 失败重新计时）。熔断期间执行返回"熔断中"，不静默使用。

会话复用（M4 完整版）：mcp 2.0 ClientSession 的 cancel scope 绑定创建它的 asyncio 任务，
跨 ASGI 请求复用会触发 anyio "exit cancel scope" 错误导致连接死亡（实测）——故每个 server
用**独立 owner-task** 承载连接生命周期（connect 在 owner 内完成、cancel scope 常驻该任务），
工具调用经 asyncio.Queue 投递给 owner 串行执行，规避跨请求复用报错。stdio 免每次起子进程（~1s）。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings
from app.tools.mcp_client import McpConnConfig, McpConnectError, McpConnection, McpToolInfo


class _PoolEntry:
    """owner-task 池条目：常驻连接任务 + 请求队列（(tool_name, args, future) 或 None=关闭）。"""

    __slots__ = ("owner", "queue")

    def __init__(self, owner: asyncio.Task, queue: asyncio.Queue) -> None:
        self.owner = owner
        self.queue = queue


class CircuitBreaker:
    """状态机：CLOSED（连续失败 < 阈值）→ OPEN（达阈值，冷却中拒绝）→ HALF_OPEN（冷却后放行一次）。"""

    def __init__(self, threshold: int, cooldown_s: float) -> None:
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self._consecutive = 0
        self._opened_at: float | None = None
        self._half_open_used = False

    def is_open(self) -> bool:
        """OPEN 且仍在冷却期内 → True（拒绝）。"""
        return self._consecutive >= self.threshold and time.monotonic() - self._opened_at < self.cooldown_s

    def allow(self) -> bool:
        """CLOSED 恒放行；冷却结束后的首次调用 HALF_OPEN 放行一次，之后拒绝等待复位。

        不变量：_consecutive >= threshold ⟹ _opened_at 非 None（record_failure 达阈值必设）。
        """
        if self._consecutive < self.threshold:
            return True
        if time.monotonic() - self._opened_at >= self.cooldown_s:
            if not self._half_open_used:
                self._half_open_used = True
                return True
        return False

    def record_failure(self) -> None:
        self._consecutive += 1
        if self._consecutive >= self.threshold:
            self._opened_at = time.monotonic()  # 达阈值/失败即刷新冷却起点
            self._half_open_used = False

    def record_success(self) -> None:
        self._consecutive = 0
        self._opened_at = None
        self._half_open_used = False


class MCPManager:
    """owner-task 会话池 + 熔断。`_conn_factory` 为测试注入点（默认 McpConnection）。"""

    def __init__(
        self,
        connection_factory: Callable[[str, McpConnConfig], McpConnection] | None = None,
    ) -> None:
        self._conn_factory = connection_factory
        self._breakers: dict[str, CircuitBreaker] = {}
        self._pool: dict[str, _PoolEntry] = {}
        self._pool_lock: asyncio.Lock | None = None  # 懒建（须在运行中的 loop 内）

    def _lock(self) -> asyncio.Lock:
        if self._pool_lock is None:
            self._pool_lock = asyncio.Lock()
        return self._pool_lock

    def _create_connection(self, server_id: str, cfg: McpConnConfig) -> McpConnection:
        if self._conn_factory is not None:
            return self._conn_factory(server_id, cfg)
        return McpConnection(cfg)

    def _breaker(self, server_id: str) -> CircuitBreaker:
        breaker = self._breakers.get(server_id)
        if breaker is None:
            s = get_settings()
            breaker = CircuitBreaker(s.mcp_breaker_threshold, s.mcp_breaker_cooldown_s)
            self._breakers[server_id] = breaker
        return breaker

    def _start_owner(self, server_id: str, cfg: McpConnConfig) -> _PoolEntry:
        """起 owner-task：常驻连接生命周期 + 串行处理请求队列。

        connect 在 owner 内完成（cancel scope 绑定 owner 任务，规避跨请求复用报错）；
        连接失败 → 队列里等待的请求全部返回失败，owner 退出（下次 call 重建）。
        """
        queue: asyncio.Queue = asyncio.Queue()
        breaker = self._breaker(server_id)

        async def _owner() -> None:
            conn = self._create_connection(server_id, cfg)
            try:
                await conn.connect()
            except Exception as exc:  # noqa: BLE001  连接失败 → 全部请求失败 + 退出
                breaker.record_failure()
                while True:
                    try:
                        req = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if req is not None:
                        _tool, _args, future = req
                        if not future.done():
                            future.set_result((False, f"MCP 连接失败: {str(exc)[:200]}"))
                return
            try:
                while True:
                    req = await queue.get()
                    if req is None:  # 关闭信号
                        break
                    tool_name, args, future = req
                    try:
                        ok, text = await conn.call_tool(tool_name, args)
                        breaker.record_success()
                    except Exception as exc:  # noqa: BLE001  传输/协议异常 → 熔断计数
                        breaker.record_failure()
                        ok, text = False, str(exc)
                    if not future.done():
                        future.set_result((ok, text))
            finally:
                with contextlib.suppress(Exception):
                    await conn.close()

        owner = asyncio.create_task(_owner())
        entry = _PoolEntry(owner, queue)
        self._pool[server_id] = entry
        return entry

    async def _get_or_start_owner(self, server_id: str, cfg: McpConnConfig) -> _PoolEntry:
        """取池中存活 owner；无/已死 → 重建（加锁防并发重复建连）。"""
        async with self._lock():
            entry = self._pool.get(server_id)
            if entry is None or entry.owner.done():
                if entry is not None:
                    self._pool.pop(server_id, None)
                entry = self._start_owner(server_id, cfg)
            return entry

    async def call(
        self, server_id: str, cfg: McpConnConfig, tool_name: str, args: dict[str, Any]
    ) -> tuple[bool, str]:
        """执行远程工具 → (ok, 文本)。熔断中直接拒绝（I7：不静默使用）。

        经 owner-task 池复用会话：请求入队 → owner 串行执行 → future 取结果。
        """
        breaker = self._breaker(server_id)
        if not breaker.allow():  # CLOSED 恒放行；OPEN 冷却内拒绝；HALF_OPEN 探针放行一次
            return False, f"MCP 源熔断中（{server_id}）"
        entry = await self._get_or_start_owner(server_id, cfg)
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        entry.queue.put_nowait((tool_name, args, future))
        return await future

    async def validate(self, cfg: McpConnConfig) -> list[McpToolInfo]:
        """注册验证：连接 → list_tools → 立即关闭（不驻留子进程，不占池）。失败抛 McpConnectError。"""
        conn = self._create_connection("validate", cfg)
        try:
            await conn.connect()
            return await conn.list_tools()
        except Exception as exc:
            raise McpConnectError(str(exc)) from exc
        finally:
            await conn.close()

    async def close_connection(self, server_id: str) -> None:
        """注销/清理单源：关 owner-task + 清池条目 + 移除熔断（重注册后重新计数）。"""
        self._breakers.pop(server_id, None)
        await self._shutdown_entry(server_id)

    async def close_all(self) -> None:
        """关停/测试清理：关闭全部 owner-task + 清池 + 清熔断。"""
        self._breakers.clear()
        for sid in list(self._pool):
            await self._shutdown_entry(sid)

    async def _shutdown_entry(self, server_id: str) -> None:
        entry = self._pool.pop(server_id, None)
        if entry is None:
            return
        entry.owner.cancel()  # owner finally 关 conn
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await entry.owner
        # 失败仍排队等待的请求（避免 future 悬挂）
        while True:
            try:
                req = entry.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if req is not None:
                _tool, _args, future = req
                if not future.done():
                    future.set_result((False, "MCP 会话已关闭"))


# 进程级单例（同幂等缓存接缝，见 README M2.5 接缝表）
manager = MCPManager()
