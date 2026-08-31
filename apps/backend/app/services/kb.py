"""知识库领域服务（《02》后端设计 §9.1 / 《02》接口契约 §5.6）。集合/文档 CRUD + 状态机操作。

上传即提取文本入库（txt/md，UTF-8 严格），KB 不落磁盘 → reindex 零磁盘依赖。
后台处理链 process_document 由调用方 create_task 触发（M4 队列接缝）。
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.config import get_settings
from app.core.errors import (
    ERR_COLLECTION_NAME_CONFLICT,
    ERR_COLLECTION_NOT_FOUND,
    ERR_DOCUMENT_NOT_FOUND,
    ERR_DOCUMENT_TYPE_UNSUPPORTED,
    ERR_FILE_TOO_LARGE,
    ERR_PARAM_MISSING,
    ERR_TASK_RUNNING,
    AppError,
)
from app.storage.models.kb import KbCollection, KbDocument
from app.storage.models.user import User
from app.storage.repositories.kb import KbRepository

_ALLOWED_TYPES = {"text/plain", "text/markdown"}


class KbService:
    # ---- 集合 ----

    async def create_collection(
        self,
        db: Any,
        user: User,
        name: str,
        chunk_size: int = 512,
        overlap: int = 64,
        description: str = "",
    ) -> KbCollection:
        repo = KbRepository(db)
        if await repo.name_exists(user.org_id, name):
            raise AppError(ERR_COLLECTION_NAME_CONFLICT, f"集合 {name} 已存在")
        coll = await repo.create_collection(user.org_id, name, chunk_size, overlap, description)
        await db.commit()
        return coll

    async def get_collection(self, db: Any, user: User, collection_id: uuid.UUID) -> KbCollection:
        coll = await KbRepository(db).get_collection(user.org_id, collection_id)
        if coll is None:
            raise AppError(ERR_COLLECTION_NOT_FOUND, "集合不存在或无权访问")
        return coll

    async def list_collections(self, db: Any, user: User) -> list[KbCollection]:
        return await KbRepository(db).list_collections(user.org_id)

    async def document_counts(
        self, db: Any, user: User, collection_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """各集合非软删文档数（S11：经服务层转发 repo，五层依赖约束）。"""
        return await KbRepository(db).document_counts(user.org_id, collection_ids)

    async def delete_collection(self, db: Any, user: User, collection_id: uuid.UUID) -> None:
        """软删集合 + 软删其文档 + 硬删 chunks。"""
        repo = KbRepository(db)
        coll = await self.get_collection(db, user, collection_id)
        for doc in await repo.list_documents(collection_id):
            await repo.soft_delete_document(doc)
        await repo.delete_collection_chunks(collection_id)
        await repo.soft_delete_collection(coll)
        await db.commit()

    # ---- 文档 ----

    async def upload_document(
        self,
        db: Any,
        user: User,
        collection_id: uuid.UUID,
        filename: str,
        content: str,
        content_type: str,
        size_bytes: int = 0,
    ) -> KbDocument:
        """上传（内容已由路由从 multipart 提取）；校验类型/大小 → uploaded → 触发后台链。"""
        coll = await self.get_collection(db, user, collection_id)
        if content_type not in _ALLOWED_TYPES:
            raise AppError(ERR_DOCUMENT_TYPE_UNSUPPORTED, f"文档类型不支持: {content_type}（仅 txt/md）")
        if size_bytes > get_settings().max_upload_mb * 1024 * 1024:
            raise AppError(ERR_FILE_TOO_LARGE, f"文件超过 {get_settings().max_upload_mb}MB 限制")
        if not content:
            raise AppError(ERR_PARAM_MISSING, "文档内容为空")  # S8：空内容属参数缺失，非超长
        doc = await KbRepository(db).create_document(
            collection_id=coll.id,
            org_id=user.org_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            content=content,
        )
        await db.commit()
        await db.refresh(doc)
        _spawn_pipeline(doc.id)
        return doc

    async def get_document(self, db: Any, user: User, document_id: uuid.UUID) -> KbDocument:
        doc = await KbRepository(db).get_document(user.org_id, document_id)
        if doc is None:
            raise AppError(ERR_DOCUMENT_NOT_FOUND, "文档不存在或无权访问")
        return doc

    async def list_docs(self, db: Any, collection_id: uuid.UUID) -> list[KbDocument]:
        return await KbRepository(db).list_documents(collection_id)

    async def reindex_document(self, db: Any, user: User, document_id: uuid.UUID) -> None:
        """重索引：仅允许 indexed/failed/archived 发起（处理中 → 40901）。"""
        doc = await self.get_document(db, user, document_id)
        if doc.status in {"chunking", "indexing"}:
            raise AppError(ERR_TASK_RUNNING, "文档正在处理中")
        doc.status = "uploaded"
        doc.error = None
        await KbRepository(db).persist_document(doc)  # index.json 落盘（不走 FileTable）
        _spawn_pipeline(document_id)

    async def archive_document(self, db: Any, user: User, document_id: uuid.UUID, status: str) -> None:
        doc = await self.get_document(db, user, document_id)
        if doc.status in {"chunking", "indexing"}:
            raise AppError(ERR_TASK_RUNNING, "文档正在处理中")
        doc.status = status  # archived
        await KbRepository(db).persist_document(doc)  # index.json 落盘（不走 FileTable）

    async def delete_document(self, db: Any, user: User, document_id: uuid.UUID) -> None:
        """软删文档 + 硬删 chunks。"""
        repo = KbRepository(db)
        doc = await self.get_document(db, user, document_id)
        await repo.delete_chunks(document_id)
        await repo.soft_delete_document(doc)
        await db.commit()

    # ---- 混合检索（T7）----

    async def search(
        self,
        db: Any,
        user: User,
        coll_ids: list[uuid.UUID],
        query: str,
        top_k: int = 5,
        hybrid: dict | None = None,
    ) -> list[dict]:
        """语义 + BM25 双通道 → RRF 融合（repository 单一来源）。org 折叠：user 缺省用默认 org。"""
        from app.storage.constants import DEFAULT_ORG_ID

        org_id = getattr(user, "org_id", None) or DEFAULT_ORG_ID
        return await KbRepository(db).hybrid_search(org_id, coll_ids, query, top_k, hybrid)


def _spawn_pipeline(document_id: uuid.UUID) -> None:
    """触发后台处理链（本地单机化：直连 store，无 sessionmaker 桥）。"""
    from app.core.async_utils import spawn_background
    from app.services.kb_pipeline import process_document

    spawn_background(process_document, document_id)
