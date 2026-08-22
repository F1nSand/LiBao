"""工作区领域服务（M7-B，docs 03 §5.14）。root_path 后端托管；本地文件夹随 create 创建。"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import (
    ERR_WORKSPACE_NAME_CONFLICT,
    ERR_WORKSPACE_NOT_FOUND,
    ERR_WORKSPACE_PATH_FORBIDDEN,
    AppError,
)
from app.services.serializers import serialize_workspace
from app.storage.models import (
    Attachment,
    Candidate,
    Conversation,
    LongTermMemory,
    LongTermMemoryVersion,
    Message,
    RunLog,
    WebhookConfig,
)
from app.storage.models.user import User
from app.storage.models.workspace import Workspace
from app.storage.repositories.workspace import WorkspaceRepository
from app.tools.filesystem import resolve_workspace_path

logger = logging.getLogger(__name__)


def _slugify_name(name: str) -> str:
    """工作区 name → 文件系统安全 slug（保留 ASCII 字母数字，其余转 -；空/纯中文兜底 workspace）。"""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return s or "workspace"


def workspace_root(workspace_id: uuid.UUID, name: str = "") -> Path:
    """root_path 托管：{workspaces_root}/{slug(name)}-{id前8}（可读 + 唯一 + 改名稳定；name 空退化为纯 uuid）。
    绝对路径（resolve），避免下游 relative_to/路径校验在相对与绝对之间混用。"""
    dirname = f"{_slugify_name(name)}-{str(workspace_id)[:8]}" if name else str(workspace_id)
    return (Path(get_settings().workspaces_root) / dirname).resolve()


# `.agent/` 骨架模板（M7-B T7a/T8 重定位：项目级能力文件化，Claude Code `.claude/` 同款）。
_AGENT_AGENT_MD = (
    "# 项目约定\n\n"
    "<!-- 在此填写本工作区的项目约定 / agent 行为说明；会被注入 agent 的 system prompt（[项目约定] 段）。 -->\n"
)
_AGENT_README = (
    "# .agent 目录\n\n"
    "本目录是工作区的项目级能力配置，agent 在该工作区工作时自动发现并叠加：\n\n"
    "- `agent.md`：项目约定（注入 [项目约定] 段）\n"
    "- `skills/<name>/SKILL.md`：项目级 skills（同名覆盖全局 org skill）\n"
    "- `memory/*.md`：项目记忆（注入 [项目记忆] 段）\n"
    "- `knowledge/*.md`：项目知识（注入 [项目知识] 段）\n"
)


def init_agent_skeleton(root: Path) -> None:
    """在 workspace root 下初始化 `.agent/` 骨架（幂等：已存在不覆盖）。"""
    agent_dir = root / ".agent"
    for sub in ("skills", "memory", "knowledge"):
        (agent_dir / sub).mkdir(parents=True, exist_ok=True)
    for name, content in (("agent.md", _AGENT_AGENT_MD), ("README.md", _AGENT_README)):
        p = agent_dir / name
        if not p.exists():
            p.write_text(content, encoding="utf-8")


def _open_folder(path: str) -> None:
    """OS 打开本地文件夹（Windows os.startfile / macOS open / Linux xdg-open）。"""
    import os
    import subprocess
    import sys

    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606  打开本地目录，非 shell 命令
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _purge_workspace_files(root: Path, attach_paths: list[str]) -> None:
    """硬删后的磁盘清理（best-effort，DB 已 commit 后调用）。rmtree 容 Windows 文件锁；附件逐个 unlink。
    防御（review I1）：root 必须解析到 workspaces_root 内才 rmtree——空/相对/越界 root_path（
    默认 workspaces_root="data/workspaces" 为相对值）若不校验可能误删进程 CWD。"""
    ws_root = Path(get_settings().workspaces_root).resolve()
    root_resolved = root.resolve()
    if root_resolved.is_relative_to(ws_root):
        shutil.rmtree(root_resolved, ignore_errors=True)
    else:
        logger.warning("工作区目录路径异常，跳过 rmtree（仅清附件）: %s", root)
    for p in attach_paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass


async def _scalars(db: AsyncSession, stmt) -> list[Any]:
    """物化查询结果为 Python list（删除前先取 id，避免删除过程中子查询被清空）。"""
    return list((await db.execute(stmt)).scalars())


async def _cascade_delete_workspace(db: AsyncSession, workspace_id: uuid.UUID) -> list[str]:
    """级联删除工作区全部关联行（叶子→根逆依赖序；conversations.workspace_id /
    longterm_memory.workspace_id 无 FK，DB 无级联须手动）。返回待删附件 storage_path（删行前物化）。"""
    # 1. 删除前物化各层 id / 附件路径（避免删除过程中子查询被清空）
    conv_ids = await _scalars(db, select(Conversation.id).where(Conversation.workspace_id == workspace_id))
    mem_ids = await _scalars(db, select(LongTermMemory.id).where(LongTermMemory.workspace_id == workspace_id))
    attach_paths = await _scalars(
        db, select(Attachment.storage_path).where(Attachment.conversation_id.in_(conv_ids))
    )

    # 2. 叶子→根逆依赖序（in_([]) 编译恒假，空列表安全）
    deletes: list[Any] = [
        delete(LongTermMemoryVersion).where(LongTermMemoryVersion.memory_id.in_(mem_ids)),
        delete(LongTermMemory).where(LongTermMemory.id.in_(mem_ids)),
        delete(Message).where(Message.conversation_id.in_(conv_ids)),
        delete(RunLog).where(RunLog.session_id.in_(conv_ids)),
        delete(Attachment).where(Attachment.conversation_id.in_(conv_ids)),
        delete(WebhookConfig).where(WebhookConfig.conversation_id.in_(conv_ids)),
        delete(Candidate).where(Candidate.source_conversation_id.in_(conv_ids)),
        delete(Conversation).where(Conversation.id.in_(conv_ids)),
        delete(Workspace).where(Workspace.id == workspace_id),
    ]
    for stmt in deletes:
        await db.execute(stmt)
    return attach_paths


class WorkspaceService:
    async def list_for_org(self, db: AsyncSession, org_id: uuid.UUID, page: int, page_size: int) -> dict[str, Any]:
        repo = WorkspaceRepository(db)
        items = await repo.list_for_org(org_id, limit=page_size, offset=(page - 1) * page_size)
        total = await repo.count_for_org(org_id)
        from app.api.schemas.common import paged

        return paged([serialize_workspace(w) for w in items], total, page, page_size)

    async def get_in_org(self, db: AsyncSession, org_id: uuid.UUID, workspace_id: str) -> Workspace:
        """按 id 或 name 解析；org 隔离。"""
        repo = WorkspaceRepository(db)
        row: Workspace | None = None
        try:
            row = await repo.get_by_id(uuid.UUID(workspace_id))
        except ValueError:
            row = None
        if row is None or row.org_id != org_id or row.deleted_at is not None:
            row = await repo.get_by_org_name(org_id, workspace_id)
        if row is None:
            raise AppError(ERR_WORKSPACE_NOT_FOUND, "工作区不存在或无权访问")
        return row

    async def create(self, db: AsyncSession, user: User, req: Any) -> Workspace:
        repo = WorkspaceRepository(db)
        if await repo.name_exists(user.org_id, req.name):
            raise AppError(ERR_WORKSPACE_NAME_CONFLICT, "同组织下已存在同名工作区")
        row = await repo.create(
            org_id=user.org_id,
            name=req.name,
            description=req.description or "",
            root_path="",  # 先占位，flush 拿到 id 后派生 root_path
            system_prompt_fragment=req.system_prompt_fragment or "",
            created_by=user.id,
        )
        await db.flush()
        root = workspace_root(row.id, req.name)
        root.mkdir(parents=True, exist_ok=True)  # 建真实本地文件夹
        init_agent_skeleton(root)  # 项目级能力 `.agent/` 骨架（M7-B T7a/T8）
        row.root_path = str(root)
        await db.commit()
        await db.refresh(row)
        return row

    async def update(self, db: AsyncSession, user: User, workspace_id: str, req: Any) -> Workspace:
        repo = WorkspaceRepository(db)
        row = await self.get_in_org(db, user.org_id, workspace_id)
        if req.name is not None and req.name != row.name:
            if await repo.name_exists(user.org_id, req.name):
                raise AppError(ERR_WORKSPACE_NAME_CONFLICT, "同组织下已存在同名工作区")
            row.name = req.name
        if req.description is not None:
            row.description = req.description
        if req.system_prompt_fragment is not None:
            row.system_prompt_fragment = req.system_prompt_fragment
        await db.commit()
        await db.refresh(row)
        return row

    async def hard_delete(self, db: AsyncSession, user: User, workspace_id: str) -> None:
        """硬删工作区：删 DB 行（级联）+ root 目录 + 附件磁盘文件（交接板 2026-08-21，用户拍板真删除）。
        org 隔离经 get_in_org 40416（不存在 / 他 org / 已软删）。"""
        ws = await self.get_in_org(db, user.org_id, workspace_id)
        # M1 行锁：串行化并发 hard_delete（防同一工作区双删竞态；已删则 40416）
        locked = await db.execute(select(Workspace).where(Workspace.id == ws.id).with_for_update())
        locked_ws = locked.scalar_one_or_none()
        if locked_ws is None:
            raise AppError(ERR_WORKSPACE_NOT_FOUND, "工作区不存在或无权访问")
        root = Path(locked_ws.root_path)  # commit 前捕获，供 commit 后磁盘清理
        attach_paths = await _cascade_delete_workspace(db, locked_ws.id)
        await db.commit()
        # DB 是事实源：先 commit，rmtree 失败只是磁盘残留孤儿目录（可手动清理），与附件 soft_delete 模式一致
        await asyncio.to_thread(_purge_workspace_files, root, attach_paths)

    # ---- 文件（资源管理器，docs 03 §5.14）----

    async def list_files(self, db: AsyncSession, user: User, workspace_id: str, path: str) -> list[dict[str, Any]]:
        ws = await self.get_in_org(db, user.org_id, workspace_id)
        root = Path(ws.root_path)
        target = resolve_workspace_path(root, path or "")
        if not target.is_dir():
            raise AppError(ERR_WORKSPACE_PATH_FORBIDDEN, "路径不是目录")
        entries: list[dict[str, Any]] = []
        for p in sorted(target.iterdir()):
            entries.append(
                {
                    "name": p.name,
                    # 统一 `/` 分隔：Windows 原生 `\` 会破坏前端 parentOf/路径拼接
                    "path": p.relative_to(root).as_posix(),
                    "is_dir": p.is_dir(),
                    "size": p.stat().st_size if p.is_file() else 0,
                }
            )
        return entries

    async def read_file_content(self, db: AsyncSession, user: User, workspace_id: str, path: str) -> dict[str, Any]:
        ws = await self.get_in_org(db, user.org_id, workspace_id)
        target = resolve_workspace_path(ws.root_path, path)
        if not target.is_file():
            raise AppError(ERR_WORKSPACE_PATH_FORBIDDEN, "文件不存在")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = target.read_bytes().decode("utf-8", errors="replace")
        return {"path": path, "content": content[:50000]}

    async def write_file(
        self,
        db: AsyncSession,
        user: User,
        workspace_id: str,
        path: str,
        content: str = "",
        is_dir: bool = False,
    ) -> dict[str, Any]:
        """写/创建文件（幂等 upsert）；is_dir=True 新建文件夹（幂等）。统一返回 WorkspaceFile 形状。"""
        ws = await self.get_in_org(db, user.org_id, workspace_id)
        root = Path(ws.root_path)
        if not path or path in (".", "./"):
            raise AppError(ERR_WORKSPACE_PATH_FORBIDDEN, "路径不能为空")
        target = resolve_workspace_path(root, path)
        if is_dir:
            if target.exists() and not target.is_dir():
                raise AppError(ERR_WORKSPACE_PATH_FORBIDDEN, "路径已存在且不是目录")
            target.mkdir(parents=True, exist_ok=True)
            return {"name": target.name, "path": path, "is_dir": True, "size": 0}
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_dir():
            raise AppError(ERR_WORKSPACE_PATH_FORBIDDEN, "路径已存在且是目录")
        target.write_text(content[:100000], encoding="utf-8")
        return {"name": target.name, "path": path, "is_dir": False, "size": target.stat().st_size}

    async def rename_file(self, db: AsyncSession, user: User, workspace_id: str, old_path: str, new_path: str) -> None:
        """重命名文件/文件夹（目录重命名 = 整棵子树搬移，子项自动跟随；docs 03 §5.14）。"""
        ws = await self.get_in_org(db, user.org_id, workspace_id)
        root = Path(ws.root_path)
        old_target = resolve_workspace_path(root, old_path)
        new_target = resolve_workspace_path(root, new_path)
        if old_target == root.resolve() or new_target == root.resolve():
            raise AppError(ERR_WORKSPACE_PATH_FORBIDDEN, "不能重命名工作区根目录")
        if not old_target.exists():
            raise AppError(ERR_WORKSPACE_PATH_FORBIDDEN, "源路径不存在")
        if old_target == new_target:
            return  # old==new：POSIX 本为 no-op、Windows 会抛 FileExistsError，显式短路保证跨平台一致
        # M2 符号链接优先：old 是链接时按链接本身重命名（old_target 已解引用到目标，target 语义检查会错位）
        if (root / old_path).is_symlink():
            # 大小写仅改名特例（Windows：link.txt → LINK.TXT）
            if os.path.normcase(str(root / old_path)) == os.path.normcase(str(new_target)):
                (root / old_path).rename(new_target)
                return
            if new_target.exists():
                raise AppError(ERR_WORKSPACE_PATH_FORBIDDEN, "目标路径已存在")
            new_target.parent.mkdir(parents=True, exist_ok=True)
            (root / old_path).rename(new_target)
            return
        # M3 Windows 大小写仅改名特例（普通文件/目录：a.md → A.md），normcase 相等但字符串不同
        if os.name == "nt" and os.path.normcase(str(old_target)) == os.path.normcase(str(new_target)):
            old_target.rename(new_target)
            return
        if new_target.exists():
            raise AppError(ERR_WORKSPACE_PATH_FORBIDDEN, "目标路径已存在")
        if new_target.is_relative_to(old_target):
            raise AppError(ERR_WORKSPACE_PATH_FORBIDDEN, "不能将目标重命名为自身或自身子路径")
        new_target.parent.mkdir(parents=True, exist_ok=True)  # 允许移入未建子目录
        old_target.rename(new_target)

    async def delete_file(self, db: AsyncSession, user: User, workspace_id: str, path: str) -> None:
        ws = await self.get_in_org(db, user.org_id, workspace_id)
        root = Path(ws.root_path)
        target = resolve_workspace_path(root, path)
        if target == root.resolve():
            raise AppError(ERR_WORKSPACE_PATH_FORBIDDEN, "不能删除工作区根目录")
        # M2 符号链接：删链接本身，不解引用真实目标（防删链接误删其指向的文件/目录）
        if (root / path).is_symlink():
            await asyncio.to_thread((root / path).unlink, missing_ok=True)
            return
        if target.is_dir():
            # 目录递归删（best-effort 容 Windows 文件锁；rmtree 默认按 lstat 删链，不跟随目录符号链接）
            await asyncio.to_thread(shutil.rmtree, target, ignore_errors=True)
            return
        if target.is_file():
            target.unlink()

    async def reveal(self, db: AsyncSession, user: User, workspace_id: str) -> None:
        """OS 打开 root_path 所在文件夹（M7-B 增强，docs 03 §5.14）。存在校验 + org 隔离，仅 developer+。"""
        ws = await self.get_in_org(db, user.org_id, workspace_id)
        root = Path(ws.root_path)
        if not root.is_dir():
            raise AppError(ERR_WORKSPACE_NOT_FOUND, "工作区目录不存在")
        await asyncio.to_thread(_open_folder, str(root))
