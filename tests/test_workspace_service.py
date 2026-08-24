"""M7-B workspace 服务层测试：建目录、重名 40908、更新、软删 40416。"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from app.api.schemas.workspace import CreateWorkspaceRequest, UpdateWorkspaceRequest
from app.core.config import Settings
from app.core.errors import AppError
from app.services import workspace as ws_module
from app.services.serializers import serialize_workspace
from app.services.workspace import WorkspaceService
from app.storage.file.store import get_store
from app.storage.models import (
    AgentConfig,
    LongTermMemory,
    LongTermMemoryVersion,
    User,
)
from app.storage.repositories.attachment import AttachmentRepository
from app.storage.repositories.conversation import ConversationRepository
from app.storage.repositories.message import MessageRepository
from app.storage.repositories.run_log import RunLogRepository
from app.tools.builtin import register_builtin_tools


@pytest.fixture
async def workspace_fixture(tmp_path, monkeypatch):
    # 测试用临时 workspaces_root，避免污染真实 data/workspaces
    monkeypatch.setattr(ws_module, "get_settings", lambda: Settings(workspaces_root=str(tmp_path)))
    register_builtin_tools()
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(
            username=f"ws_{uid}", password_hash="hashed", name="W", role="admin", org_id=uuid.UUID(int=0)
        )
        session.add(user)
        await session.commit()
    yield user


async def test_create_workspace_creates_directory(workspace_fixture, tmp_path):
    user = workspace_fixture
    async with get_store().session() as session:
        row = await WorkspaceService().create(
            session, user, CreateWorkspaceRequest(name="proj-a", description="desc")
        )
        assert serialize_workspace(row)["name"] == "proj-a"
        assert row.root_path == str(tmp_path / f"proj-a-{str(row.id)[:8]}")  # 可读前缀 + uuid 前8
        assert os.path.isdir(row.root_path)  # 真实本地目录已建


def test_slugify_name():
    assert ws_module._slugify_name("GitHub 热点") == "github"  # 中文被剥，保留 ASCII
    assert ws_module._slugify_name("proj-a") == "proj-a"
    assert ws_module._slugify_name("热点收集") == "workspace"  # 纯中文兜底


async def test_create_duplicate_name_conflict(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="dup"))
        with pytest.raises(AppError) as exc:
            await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="dup"))
        assert exc.value.code == 40908


async def test_update_workspace(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        row = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="a"))
        updated = await WorkspaceService().update(
            session, user, str(row.id), UpdateWorkspaceRequest(description="new", project_instructions="你是项目助手")
        )
        assert updated.description == "new"
        assert updated.project_instructions == "你是项目助手"


async def test_hard_delete_cascades_all_workspace_rows(workspace_fixture, tmp_path):
    """硬删：级联清空工作区全部关联表 + 删 root 目录 + 附件磁盘文件（交接板 2026-08-21）。"""
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="doomed"))
        wid, root = ws.id, ws.root_path
        agent = AgentConfig(
            org_id=uuid.UUID(int=0), name="a", model="fake", system_prompt="x",
            tools=[], max_steps=5, status="published",
        )
        session.add(agent)
        await session.flush()
        conv = await ConversationRepository(session).create(
            user_id=user.id, agent_id=agent.id, title="ws-conv", workspace_id=wid
        )
        conv_id = conv.id
        attach_file = tmp_path / f"att-{uuid.uuid4().hex}.bin"
        attach_file.write_bytes(b"x")
        await MessageRepository(session).create(conversation_id=conv_id, role="user", content="hi")
        trace_id = f"t-{uuid.uuid4().hex}"
        await RunLogRepository(session).create(trace_id=trace_id, session_id=conv_id)
        att = await AttachmentRepository(session).create(
            user_id=user.id,
            filename="f.bin",
            content_type="application/octet-stream",
            size_bytes=1,
            storage_path=str(attach_file),
        )
        att.conversation_id = conv_id  # 消息回填归属（硬删按 conversation_id 级联）
        mem = LongTermMemory(user_id=user.id, workspace_id=wid, card_type="note", content={"text": "m"})
        get_store().table("memory_cards").register(mem)
        mem_id = mem.id
        await get_store().jsonl_append(
            f"memory/default/cards/{mem_id}.versions.jsonl",
            LongTermMemoryVersion(memory_id=mem_id, version=1, content={"text": "m"}).to_dict(),
        )
        await session.commit()

        await WorkspaceService().hard_delete(session, user, str(wid))

        # 文件化实体：按文件断言归零
        store = get_store()
        assert await MessageRepository().count(conv_id) == 0
        assert len(await RunLogRepository().list_by_trace_id(trace_id)) == 0  # 轨迹 JSONL 已随会话删除
        trace_file = store.root / "memory" / "default" / "trace" / f"{conv_id}.jsonl"
        assert not trace_file.exists()
        assert await store.table("conversations").get(conv_id) is None
        # 文件实体：按表断言归零
        atts = await store.table("attachments").list(filter_fn=lambda a: a.conversation_id == conv_id)
        assert len(atts) == 0
        assert await store.table("memory_cards").get(mem_id) is None
        assert not (store.root / "memory" / "default" / "cards" / f"{mem_id}.versions.jsonl").exists()
        assert await store.table("workspaces").get(wid) is None
        assert not os.path.exists(root)  # root 目录已删
        assert not os.path.exists(attach_file)  # 附件磁盘文件已删（用户拍板：连删）


async def test_hard_delete_does_not_touch_other_workspace(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws_a = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="keep-a"))
        ws_b = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="delete-b"))
        agent = AgentConfig(
            org_id=uuid.UUID(int=0), name="a", model="fake", system_prompt="x",
            tools=[], max_steps=5, status="published",
        )
        session.add(agent)
        await session.flush()
        await ConversationRepository(session).create(
            user_id=user.id, agent_id=agent.id, title="a", workspace_id=ws_a.id
        )
        await ConversationRepository(session).create(
            user_id=user.id, agent_id=agent.id, title="b", workspace_id=ws_b.id
        )
        get_store().table("memory_cards").register(
            LongTermMemory(user_id=user.id, workspace_id=ws_a.id, card_type="note", content={"text": "a"})
        )
        await session.commit()

        await WorkspaceService().hard_delete(session, user, str(ws_b.id))

        store = get_store()
        ws_a_convs = await store.table("conversations").list(
            filter_fn=lambda c: c.workspace_id == ws_a.id
        )
        ws_b_convs = await store.table("conversations").list(
            filter_fn=lambda c: c.workspace_id == ws_b.id
        )
        assert len(ws_a_convs) == 1
        assert len(ws_b_convs) == 0
        assert len(await store.table("memory_cards").list(filter_fn=lambda m: m.workspace_id == ws_a.id)) == 1
        assert os.path.exists(ws_a.root_path)


async def test_hard_delete_unknown_workspace_40416(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        with pytest.raises(AppError) as exc:
            await WorkspaceService().hard_delete(session, user, str(uuid.uuid4()))
        assert exc.value.code == 40416


async def test_file_ops_org_isolation_40416(workspace_fixture):
    """越权方（另一 org 用户）访问工作区文件端点 / 硬删 → 全部 40416（review I3 补测 org 边界）。"""
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="iso"))
        other = User(
            username=f"ws_other_{uuid.uuid4().hex[:8]}",
            password_hash="hashed",
            name="O",
            role="admin",
            org_id=uuid.uuid4(),  # 另一 org（单机折叠后 org 仅剩隔离语义字段）
        )
        session.add(other)
        await session.commit()
        wid = str(ws.id)
        ops = [
            lambda: WorkspaceService().list_files(session, other, wid, ""),
            lambda: WorkspaceService().read_file_content(session, other, wid, "x.md"),
            lambda: WorkspaceService().write_file(session, other, wid, "x.md", "x"),
            lambda: WorkspaceService().rename_file(session, other, wid, "x.md", "y.md"),
            lambda: WorkspaceService().delete_file(session, other, wid, "x.md"),
            lambda: WorkspaceService().hard_delete(session, other, wid),
        ]
        for op in ops:
            with pytest.raises(AppError) as exc:
                await op()
            assert exc.value.code == 40416


async def test_hard_delete_twice_second_40416(workspace_fixture):
    """重复硬删串行化（review M1 行锁语义）：第二次返回 40416。"""
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="dd"))
        wid = str(ws.id)
        await WorkspaceService().hard_delete(session, user, wid)
        with pytest.raises(AppError) as exc:
            await WorkspaceService().hard_delete(session, user, wid)
        assert exc.value.code == 40416


async def test_delete_symlink_removes_link_not_target(workspace_fixture):
    """符号链接删除：删链接本身，真实目标保留（review M2）。无符号链接权限则跳过。"""
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="sym-del"))
        wid = str(ws.id)
        root = Path(ws.root_path)
        (root / "real.txt").write_text("secret", encoding="utf-8")
        try:
            (root / "link.txt").symlink_to("real.txt")
        except (OSError, NotImplementedError):
            pytest.skip("当前环境不支持创建符号链接（需开发者模式/管理员）")
        await WorkspaceService().delete_file(session, user, wid, "link.txt")
        assert not (root / "link.txt").exists()
        assert (root / "real.txt").read_text(encoding="utf-8") == "secret"


async def test_rename_symlink_renames_link_not_target(workspace_fixture):
    """符号链接重命名：链接本身移动，真实目标保留（review M2）。无符号链接权限则跳过。"""
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="sym-rn"))
        wid = str(ws.id)
        root = Path(ws.root_path)
        (root / "real.txt").write_text("secret", encoding="utf-8")
        try:
            (root / "link.txt").symlink_to("real.txt")
        except (OSError, NotImplementedError):
            pytest.skip("当前环境不支持创建符号链接（需开发者模式/管理员）")
        await WorkspaceService().rename_file(session, user, wid, "link.txt", "renamed.txt")
        assert (root / "renamed.txt").is_symlink()
        assert not (root / "link.txt").exists()
        assert (root / "real.txt").read_text(encoding="utf-8") == "secret"


async def test_rename_case_only(workspace_fixture):
    """大小写仅改名（a.md → A.md）：Windows 特例应成功而非误报目标已存在（review M3）；POSIX 下是普通改名。"""
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="rn-case"))
        wid = str(ws.id)
        await WorkspaceService().write_file(session, user, wid, "readme.md", "x")
        await WorkspaceService().rename_file(session, user, wid, "readme.md", "README.md")
        out = await WorkspaceService().read_file_content(session, user, wid, "README.md")
        assert "x" in out["content"]


async def test_file_ops_roundtrip(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="files"))
        wid = str(ws.id)
        res = await WorkspaceService().write_file(session, user, wid, "a/notes.md", "hello")
        assert res["is_dir"] is False and res["path"] == "a/notes.md" and res["size"] == 5  # WorkspaceFile 形状
        entries = await WorkspaceService().list_files(session, user, wid, "")
        assert any(e["name"] == "a" and e["is_dir"] for e in entries)
        sub = await WorkspaceService().list_files(session, user, wid, "a")
        assert sub[0]["name"] == "notes.md"
        out = await WorkspaceService().read_file_content(session, user, wid, "a/notes.md")
        assert "hello" in out["content"]
        await WorkspaceService().delete_file(session, user, wid, "a/notes.md")
        assert not os.path.exists(os.path.join(ws.root_path, "a", "notes.md"))
        # 越界路径 → 40302
        with pytest.raises(AppError) as exc:
            await WorkspaceService().read_file_content(session, user, wid, "../secret.txt")
        assert exc.value.code == 40302


async def test_reveal(workspace_fixture, monkeypatch):
    user = workspace_fixture
    captured: dict[str, str] = {}
    monkeypatch.setattr(ws_module, "_open_folder", lambda p: captured.setdefault("path", p))
    async with get_store().session() as session:
        row = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="reveal-me"))
        await WorkspaceService().reveal(session, user, str(row.id))
        assert captured["path"] == row.root_path
        # 不存在 → 40416
        with pytest.raises(AppError) as exc:
            await WorkspaceService().reveal(session, user, str(uuid.uuid4()))
        assert exc.value.code == 40416


# ---- rename（PATCH /files/rename，交接板 2026-08-21）----

async def test_rename_file_preserves_content(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="rn"))
        wid = str(ws.id)
        await WorkspaceService().write_file(session, user, wid, "a/notes.md", "hello")
        await WorkspaceService().rename_file(session, user, wid, "a/notes.md", "a/docs.md")
        out = await WorkspaceService().read_file_content(session, user, wid, "a/docs.md")
        assert "hello" in out["content"]
        assert not os.path.exists(os.path.join(ws.root_path, "a", "notes.md"))


async def test_rename_dir_follows_children(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="rndir"))
        wid = str(ws.id)
        await WorkspaceService().write_file(session, user, wid, "dir/x.txt", "x")
        await WorkspaceService().write_file(session, user, wid, "dir/sub/y.txt", "y")
        await WorkspaceService().rename_file(session, user, wid, "dir", "moved")
        root = Path(ws.root_path)
        assert (root / "moved" / "x.txt").is_file()
        assert (root / "moved" / "sub" / "y.txt").is_file()
        assert not (root / "dir").exists()


async def test_rename_not_found_40302(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="rn-nf"))
        with pytest.raises(AppError) as exc:
            await WorkspaceService().rename_file(session, user, str(ws.id), "nope.md", "other.md")
        assert exc.value.code == 40302


async def test_rename_target_exists_40302(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="rn-ex"))
        wid = str(ws.id)
        await WorkspaceService().write_file(session, user, wid, "a.md", "a")
        await WorkspaceService().write_file(session, user, wid, "b.md", "b")
        with pytest.raises(AppError) as exc:
            await WorkspaceService().rename_file(session, user, wid, "a.md", "b.md")
        assert exc.value.code == 40302
        out = await WorkspaceService().read_file_content(session, user, wid, "a.md")
        assert "a" in out["content"]  # 源文件原样保留


async def test_rename_same_path_noop(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="rn-same"))
        wid = str(ws.id)
        await WorkspaceService().write_file(session, user, wid, "a.md", "a")
        await WorkspaceService().rename_file(session, user, wid, "a.md", "a.md")  # 不报错
        out = await WorkspaceService().read_file_content(session, user, wid, "a.md")
        assert "a" in out["content"]


async def test_rename_into_own_subtree_40302(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="rn-loop"))
        wid = str(ws.id)
        await WorkspaceService().write_file(session, user, wid, "a/x.txt", "x")
        with pytest.raises(AppError) as exc:
            await WorkspaceService().rename_file(session, user, wid, "a", "a/b")
        assert exc.value.code == 40302


async def test_rename_escape_blocked_40302(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="rn-esc"))
        wid = str(ws.id)
        await WorkspaceService().write_file(session, user, wid, "a.md", "a")
        with pytest.raises(AppError) as exc:
            await WorkspaceService().rename_file(session, user, wid, "a.md", "../esc.md")
        assert exc.value.code == 40302


async def test_rename_root_40302(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="rn-root"))
        with pytest.raises(AppError) as exc:
            await WorkspaceService().rename_file(session, user, str(ws.id), "", "x")
        assert exc.value.code == 40302


# ---- mkdir（POST /files {is_dir:true}，交接板 2026-08-21）----

async def test_create_dir_returns_workspace_file(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="mkdir"))
        wid = str(ws.id)
        res = await WorkspaceService().write_file(session, user, wid, "assets", "", True)
        assert res["path"] == "assets" and res["is_dir"] is True and res["size"] == 0
        assert os.path.isdir(os.path.join(ws.root_path, "assets"))


async def test_create_dir_idempotent(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="mkdir-idem"))
        wid = str(ws.id)
        await WorkspaceService().write_file(session, user, wid, "assets", "", True)
        await WorkspaceService().write_file(session, user, wid, "assets", "", True)  # 幂等不报错


async def test_create_dir_conflicts_with_file_40302(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="mkdir-conf"))
        wid = str(ws.id)
        await WorkspaceService().write_file(session, user, wid, "a", "file-content")
        with pytest.raises(AppError) as exc:
            await WorkspaceService().write_file(session, user, wid, "a", "", True)
        assert exc.value.code == 40302


async def test_create_dir_nested_creates_parents(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="mkdir-nest"))
        wid = str(ws.id)
        res = await WorkspaceService().write_file(session, user, wid, "x/y/z", "", True)
        assert res["is_dir"] is True
        assert os.path.isdir(os.path.join(ws.root_path, "x", "y", "z"))


# ---- 目录递归删（DELETE /files?path=，交接板 2026-08-21）----

async def test_delete_dir_recursive(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="del-dir"))
        wid = str(ws.id)
        await WorkspaceService().write_file(session, user, wid, "dir/a.txt", "a")
        await WorkspaceService().write_file(session, user, wid, "dir/sub/b.txt", "b")
        await WorkspaceService().delete_file(session, user, wid, "dir")
        assert not os.path.exists(os.path.join(ws.root_path, "dir"))


async def test_delete_root_forbidden_40302(workspace_fixture):
    user = workspace_fixture
    async with get_store().session() as session:
        ws = await WorkspaceService().create(session, user, CreateWorkspaceRequest(name="del-root"))
        with pytest.raises(AppError) as exc:
            await WorkspaceService().delete_file(session, user, str(ws.id), "")
        assert exc.value.code == 40302
