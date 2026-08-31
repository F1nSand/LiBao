"""共享测试基础设施（M2.5 Simplify 收敛：原 8 份 _db_reachable 拷贝 + 3 份 mc_ 清理循环）。

requires_db 供各 DB-backed 测试文件做 pytestmark；clean_mcp_specs 供注册 MCP spec 的 fixture
在 setup 幂等清理历史残留（registry 是进程级全局，async fixture teardown 延迟执行不可靠）。
本地单机化：`_filestore` autouse 为每个测试初始化独立 FileStore（tmp 目录），测试无需自建。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.tools.builtin import register_builtin_tools
from app.tools.registry import all_tools, unregister


@pytest.fixture(autouse=True)
async def _filestore(tmp_path):
    """文件存储隔离：每个测试独立临时目录（本地单机化）。

    每个测试使用独立的临时 FileStore。
    """
    from app.storage.file.store import FileStore, set_store

    settings = SimpleNamespace(agent_data_dir=str(tmp_path / ".agent"), kb_root=str(tmp_path / "kb"))
    store = FileStore(settings)
    await store.init()
    set_store(store)
    yield store
    set_store(None)


@pytest.fixture
def clean_mcp_specs():
    """幂等清理历史 MCP spec（进程级 registry 防跨测试遮蔽污染）。"""
    register_builtin_tools()
    for spec in [s for s in all_tools() if s.id.startswith("mc_")]:
        unregister(spec.id)
