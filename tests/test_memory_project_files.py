"""P3 项目记忆文件化测试：提取分支 project 落盘（frontmatter/同主题合并/非法字符 slug）、
memory_extract project 项走 md 而非卡片。"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from app.services.memory_extract import _slugify, _write_project_md, extract_and_store
from app.storage.file.store import get_store


class FakeExtractModel:
    def __init__(self, content: str) -> None:
        self.content = content

    async def ainvoke(self, messages):
        return AIMessage(content=self.content)


async def _memory_files(ws_root: Path) -> list[Path]:
    return sorted((ws_root / ".agent" / "memory").glob("*.md"))


async def test_project_extract_writes_md_with_frontmatter(tmp_path):
    """提取判定 project → 工作区 .agent/memory/ 落 md（frontmatter 完整，无卡片写入）。"""
    ws_root = Path(tmp_path)
    plan = {
        "items": [
            {
                "scope": "project",
                "title": "架构决策",
                "content": "决定用 FastAPI + 文件存储",
                "importance": 0.8,
                "topic_key": "arch",
                "type": "decision",
                "tags": ["架构"],
            }
        ]
    }
    result = await extract_and_store(
        messages=[AIMessage(content=""), HumanMessage(content="我们决定用 FastAPI 做后端")],
        user_id=str(uuid.uuid4()),
        workspace_id=str(uuid.uuid4()),
        workspace_root=str(ws_root),
        trace_id="trace-1",
        model=FakeExtractModel(json.dumps(plan)),
    )
    assert result["status"] == "ok"
    assert result["project_stored"] == 1
    files = await _memory_files(ws_root)
    assert [f.name for f in files] == ["arch.md"]
    text = files[0].read_text(encoding="utf-8")
    assert "---" in text
    assert "type: decision" in text
    assert "title: 架构决策" in text
    assert "topic_key: arch" in text
    assert "source_conversation: trace-1" in text
    assert "决定用 FastAPI + 文件存储" in text
    # project 不写卡片
    assert await get_store().table("memory_cards").list() == []


async def test_project_same_topic_merges_update(tmp_path):
    """同 topic_key 二次提取 → 追加「更新记录」段 + updated_at 刷新（不新建文件）。"""
    ws_root = Path(tmp_path)

    def item(content: str) -> dict:
        return {
            "scope": "project", "title": "架构", "content": content, "importance": 0.7,
            "topic_key": "arch", "type": "progress",
        }

    await _write_project_md(str(ws_root), item("第一版决策：用 FastAPI"), "t1")
    first = (await _memory_files(ws_root))[0]
    first_text = first.read_text(encoding="utf-8")
    await _write_project_md(str(ws_root), item("第二版：改用文件存储"), "t2")
    files = await _memory_files(ws_root)
    assert len(files) == 1  # 不新建
    text = files[0].read_text(encoding="utf-8")
    assert "第一版决策：用 FastAPI" in text
    assert "## " in text and "更新" in text  # 更新记录段
    assert "第二版：改用文件存储" in text
    assert "source_conversation: t2" in text  # 来源刷新
    assert text != first_text


async def test_project_topic_slug_invalid_chars(tmp_path):
    """topic_key 含非法文件名字符 → slug 折叠为下划线。"""
    ws_root = Path(tmp_path)
    await _write_project_md(
        str(ws_root),
        {"scope": "project", "title": "t", "content": "c", "topic_key": "a/b:c*d", "type": "note"},
        None,
    )
    assert (await _memory_files(ws_root))[0].name == "a_b_c_d.md"
    assert _slugify("   ") == "memory"  # 全空退化


async def test_project_different_topic_creates_new_file(tmp_path):
    """不同 topic_key → 各自独立文件。"""
    ws_root = Path(tmp_path)
    await _write_project_md(str(ws_root), {"topic_key": "arch", "title": "a", "content": "x", "type": "note"}, None)
    await _write_project_md(str(ws_root), {"topic_key": "plan", "title": "p", "content": "y", "type": "note"}, None)
    assert sorted(f.name for f in await _memory_files(ws_root)) == ["arch.md", "plan.md"]


async def test_project_write_deep_root_auto_created(tmp_path):
    """workspace_root 深层不存在 → mkdir parents 自动创建，项目落盘成功。"""
    result = await extract_and_store(
        messages=[AIMessage(content=""), HumanMessage(content="我们定个架构")],
        user_id=str(uuid.uuid4()),
        workspace_id=str(uuid.uuid4()),
        workspace_root=str(tmp_path / "nope" / "deep"),  # 目录创建应成功（mkdir parents）
        model=FakeExtractModel(
            json.dumps(
                {
                    "items": [
                        {
                            "scope": "project", "title": "t", "content": "c",
                            "topic_key": "t", "type": "note",
                        }
                    ]
                }
            )
        ),
    )
    assert result["status"] == "ok"
    assert result["project_stored"] == 1
