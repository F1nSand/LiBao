"""知识库数据访问（docs 04 §3.6）。集合/文档软删；分块硬删重建（派生数据）。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.kb import KbChunk, KbCollection, KbDocument


class KbRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- 集合 ----

    async def get_collection(self, org_id: uuid.UUID, collection_id: uuid.UUID) -> KbCollection | None:
        stmt = select(KbCollection).where(
            KbCollection.org_id == org_id,
            KbCollection.id == collection_id,
            KbCollection.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def name_exists(self, org_id: uuid.UUID, name: str) -> bool:
        stmt = select(KbCollection.id).where(
            KbCollection.org_id == org_id,
            KbCollection.name == name,
            KbCollection.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).first() is not None

    async def list_collections(self, org_id: uuid.UUID) -> list[KbCollection]:
        stmt = (
            select(KbCollection)
            .where(KbCollection.org_id == org_id, KbCollection.deleted_at.is_(None))
            .order_by(KbCollection.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars())

    async def create_collection(
        self, org_id: uuid.UUID, name: str, chunk_size: int, chunk_overlap: int, description: str = ""
    ) -> KbCollection:
        row = KbCollection(
            org_id=org_id, name=name, description=description, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        self.session.add(row)
        return row

    async def soft_delete_collection(self, coll: KbCollection) -> None:
        coll.deleted_at = datetime.now(UTC)
        self.session.add(coll)

    # ---- 文档 ----

    async def get_document(self, org_id: uuid.UUID, document_id: uuid.UUID) -> KbDocument | None:
        stmt = select(KbDocument).where(
            KbDocument.org_id == org_id,
            KbDocument.id == document_id,
            KbDocument.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_documents(self, collection_id: uuid.UUID) -> list[KbDocument]:
        stmt = (
            select(KbDocument)
            .where(KbDocument.collection_id == collection_id, KbDocument.deleted_at.is_(None))
            .order_by(KbDocument.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars())

    async def create_document(
        self,
        *,
        collection_id: uuid.UUID,
        org_id: uuid.UUID,
        filename: str,
        content_type: str,
        size_bytes: int,
        content: str,
    ) -> KbDocument:
        row = KbDocument(
            collection_id=collection_id,
            org_id=org_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            content=content,
            status="uploaded",
            chunk_count=0,
        )
        self.session.add(row)
        return row

    async def soft_delete_document(self, doc: KbDocument) -> None:
        doc.deleted_at = datetime.now(UTC)
        self.session.add(doc)

    async def delete_chunks(self, document_id: uuid.UUID) -> None:
        await self.session.execute(delete(KbChunk).where(KbChunk.document_id == document_id))

    async def delete_collection_chunks(self, collection_id: uuid.UUID) -> None:
        await self.session.execute(delete(KbChunk).where(KbChunk.collection_id == collection_id))

    # ---- 分块 ----

    async def list_chunks(self, document_id: uuid.UUID) -> list[KbChunk]:
        stmt = (
            select(KbChunk)
            .where(KbChunk.document_id == document_id)
            .order_by(KbChunk.chunk_index.asc())
        )
        return list((await self.session.execute(stmt)).scalars())

    async def insert_chunks(self, rows: list[KbChunk]) -> None:
        self.session.add_all(rows)

    async def count_chunks(self, document_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(KbChunk).where(KbChunk.document_id == document_id)
        return int((await self.session.execute(stmt)).scalar_one())
