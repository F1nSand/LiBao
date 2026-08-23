"""P4 记忆工具测试：remember/recall/forget × global/project、auto 作用域推断、工具上下文。"""
from __future__ import annotations

import uuid

import pytest

from app.storage.file.store import get_store
from app.storage.repositories.memory_vectors import reset_memory_lance
from app.tools.builtin import register_builtin_tools
from app.tools.builtin.memory_tool import (
    forget_memory_handler,
    recall_memory_handler,
    remember_memory_handler,
)
from app.tools.context import (
    set_tool_user_id,
    set_tool_workspace_id,
    set_tool_workspace_root,
)
from app.tools.registry import get, get_by_name

UID = uuid.UUID(int=1)
WS_ID = uuid.UUID(int=2)


@pytest.fixture(autouse=True)
def _tool_ctx(tmp_path):
    """工具上下文隔离：user/workspace 注入 + 清理（root 落 tmp，防误写仓库）。"""
    set_tool_user_id(str(UID))
    set_tool_workspace_id(str(WS_ID))
    set_tool_workspace_root(str(tmp_path))
    yield
    set_tool_user_id(None)
    set_tool_workspace_id(None)
    set_tool_workspace_root(None)


@pytest.fixture(autouse=True)
def _reset_lance():
    reset_memory_lance()
    yield
    reset_memory_lance()


def test_tools_registered():
    register_builtin_tools()  # 注册表进程级，测试内幂等
    assert get("tl_remember_memory") is not None
    assert get("tl_recall_memory") is not None
    assert get("tl_forget_memory") is not None
    assert get_by_name("remember_memory") is not None
    assert get_by_name("recall_memory") is not None
    assert get_by_name("forget_memory") is not None


async def test_remember_global_creates_card():
    """remember_memory(scope=global) → 卡片（source=tool）+ 向量同步。"""
    result = await remember_memory_handler("用户喜欢喝咖啡", scope="global", title="偏好", importance=0.8)
    assert result["ok"] is True and result["scope"] == "global"
    cards = await get_store().table("memory_cards").list()
    assert len(cards) == 1
    card = cards[0]
    assert card.source == "tool"
    assert card.title == "偏好"
    assert card.importance == 0.8
    assert card.workspace_id is None
    assert result["card_id"] == str(card.id)


async def test_remember_auto_no_workspace_goes_global():
    """auto + 无工作区 root → global 卡片。"""
    set_tool_workspace_root(None)
    result = await remember_memory_handler("我喜欢吃火锅")
    assert result["scope"] == "global"


async def test_remember_auto_with_workspace_goes_project(tmp_path, monkeypatch):
    """auto + 有工作区 root → 项目 md 文件。"""
    monkeypatch.setattr("app.tools.builtin.memory_tool.get_tool_workspace_root", lambda: str(tmp_path))
    result = await remember_memory_handler("决定用 FastAPI 架构", title="架构决策", scope="auto")
    assert result["ok"] is True and result["scope"] == "project"
    files = list((tmp_path / ".agent" / "memory").glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "架构决策" in text and "决定用 FastAPI 架构" in text
    # project 不写卡片
    assert await get_store().table("memory_cards").list() == []


async def test_recall_global_semantic(monkeypatch):
    """recall(scope=global) → RAG 语义检索卡片。"""
    from app.core.embeddings import EmbeddingService

    async def fake_embed(self, text):
        return [1.0] + [0.0] * 1023 if "咖啡" in text else [0.0] * 1024

    monkeypatch.setattr(EmbeddingService, "embed_query", fake_embed)
    await remember_memory_handler("用户喜欢喝咖啡", scope="global", title="偏好")
    result = await recall_memory_handler("喝咖啡", scope="global")
    assert result["hits"][0]["title"] == "偏好"
    assert "咖啡" in result["hits"][0]["content"]


async def test_recall_project_keyword_scan(tmp_path, monkeypatch):
    """recall(scope=project) → 工作区 md 关键词扫描 + 片段。"""
    monkeypatch.setattr("app.tools.builtin.memory_tool.get_tool_workspace_root", lambda: str(tmp_path))
    await remember_memory_handler("决定用 FastAPI 做后端", title="架构", scope="project")
    result = await recall_memory_handler("FastAPI", scope="project")
    assert len(result["hits"]) == 1
    hit = result["hits"][0]
    assert hit["scope"] == "project"
    assert "架构" in hit["title"]
    assert "FastAPI" in hit["snippet"]


async def test_recall_no_hits():
    result = await recall_memory_handler("不存在的关键词", scope="global")
    assert result["hits"] == []


async def test_forget_global_soft_delete():
    """forget(scope=global) 按标题匹配软删 + 向量删除。"""
    await remember_memory_handler("用户喜欢喝咖啡", scope="global", title="喝咖啡偏好")
    result = await forget_memory_handler("喝咖啡偏好", scope="global")
    assert result["deleted"] == 1
    cards = await get_store().table("memory_cards").list()
    assert cards[0].deleted_at is not None  # 软删


async def test_forget_global_no_match():
    result = await forget_memory_handler("不存在", scope="global")
    assert result["deleted"] == 0


async def test_forget_project_archives_to_trash(tmp_path, monkeypatch):
    """forget(scope=project) → md 移入 .trash（不硬删）。"""
    monkeypatch.setattr("app.tools.builtin.memory_tool.get_tool_workspace_root", lambda: str(tmp_path))
    await remember_memory_handler("项目用 FastAPI", title="架构", scope="project")
    result = await forget_memory_handler("架构", scope="project")
    assert result["archived"] == 1
    memory_dir = tmp_path / ".agent" / "memory"
    assert list(memory_dir.glob("*.md")) == []  # 原目录清空
    assert len(list((memory_dir / ".trash").glob("*.md"))) == 1  # 归档可恢复


async def test_no_user_returns_error():
    """无 user 上下文 → 错误结果（不抛）。"""
    set_tool_user_id(None)
    result = await remember_memory_handler("x")
    assert "error" in result
