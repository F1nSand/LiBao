"""共享测试基础设施（M2.5 Simplify 收敛：原 8 份 _db_reachable 拷贝 + 3 份 mc_ 清理循环）。

requires_db 供各 DB-backed 测试文件做 pytestmark；clean_mcp_specs 供注册 MCP spec 的 fixture
在 setup 幂等清理历史残留（registry 是进程级全局，async fixture teardown 延迟执行不可靠）。
"""
from __future__ import annotations

import socket

import pytest

from app.tools.builtin import register_builtin_tools
from app.tools.registry import all_tools, unregister


def db_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 5432), timeout=2):
            return True
    except OSError:
        return False


def redis_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 6379), timeout=2):
            return True
    except OSError:
        return False


requires_db = pytest.mark.skipif(not db_reachable(), reason="Docker db 未运行")
requires_redis = pytest.mark.skipif(not redis_reachable(), reason="Docker redis 未运行")


@pytest.fixture
def clean_mcp_specs():
    """幂等清理历史 MCP spec（进程级 registry 防跨测试遮蔽污染）。"""
    register_builtin_tools()
    for spec in [s for s in all_tools() if s.id.startswith("mc_")]:
        unregister(spec.id)
