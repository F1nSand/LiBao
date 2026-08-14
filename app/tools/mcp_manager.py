"""MCP 连接管理器（docs 01 §7.2 / I7 熔断）。

进程级单例（同幂等缓存接缝，文档化）：server_id → 惰性连接（首次 call 时建连，
per-server asyncio.Lock 串行化）+ 熔断器（连续失败达阈值 → OPEN，冷却后 HALF_OPEN
放行一次，成功复位 / 失败重新计时）。熔断期间执行返回"熔断中"，不静默使用。
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings
from app.tools.mcp_client import McpConnConfig, McpConnection, McpConnectError, McpToolInfo


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
        return (
            self._consecutive >= self.threshold
            and self._opened_at is not None
            and time.monotonic() - self._opened_at < self.cooldown_s
        )

    def allow(self) -> bool:
        """CLOSED 恒放行；冷却结束后的首次调用 HALF_OPEN 放行一次，之后拒绝等待复位。"""
        if self._consecutive < self.threshold:
            return True
        if self._opened_at is not None and time.monotonic() - self._opened_at >= self.cooldown_s:
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
    """连接池 + 熔断。`_conn_factory` 为测试注入点（默认 McpConnection）。"""

    def __init__(
        self,
        connection_factory: Callable[[str, McpConnConfig], McpConnection] | None = None,
    ) -> None:
        self._conn_factory = connection_factory
        self._connections: dict[str, McpConnection] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._breakers: dict[str, CircuitBreaker] = {}

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

    async def _get_connection(self, server_id: str, cfg: McpConnConfig) -> McpConnection:
        conn = self._connections.get(server_id)
        if conn is not None:
            return conn
        conn = self._create_connection(server_id, cfg)
        try:
            await conn.connect()
        except Exception:
            self._connections.pop(server_id, None)  # 建连失败 → 下次重新建连
            raise
        self._connections[server_id] = conn
        return conn

    async def call(
        self, server_id: str, cfg: McpConnConfig, tool_name: str, args: dict[str, Any]
    ) -> tuple[bool, str]:
        """执行远程工具 → (ok, 文本)。熔断中直接拒绝（I7：不静默使用）。"""
        breaker = self._breaker(server_id)
        if breaker.is_open() or not breaker.allow():
            return False, f"MCP 源熔断中（{server_id}）"
        lock = self._locks.setdefault(server_id, asyncio.Lock())
        async with lock:
            try:
                conn = await self._get_connection(server_id, cfg)
                ok, text = await conn.call_tool(tool_name, args)
                breaker.record_success()
                return ok, text
            except Exception as exc:  # noqa: BLE001  连接/执行失败 → 计数熔断
                breaker.record_failure()
                return False, str(exc)

    async def validate(self, cfg: McpConnConfig) -> list[McpToolInfo]:
        """注册验证：连接 → list_tools → 立即关闭（不驻留子进程）。失败抛 McpConnectError。"""
        conn = self._create_connection("validate", cfg)
        try:
            await conn.connect()
            return await conn.list_tools()
        except Exception as exc:
            raise McpConnectError(str(exc)) from exc
        finally:
            await conn.close()

    async def close_all(self) -> None:
        """关停/测试清理：关闭全部连接并清空状态。"""
        for conn in self._connections.values():
            try:
                await conn.close()
            except Exception:  # noqa: BLE001  关闭尽力而为
                pass
        self._connections.clear()
        self._locks.clear()
        self._breakers.clear()


# 进程级单例（同幂等缓存接缝，见 README M2.5 接缝表）
manager = MCPManager()
