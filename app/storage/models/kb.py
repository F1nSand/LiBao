"""知识库实体（docs 04 §3.6）。集合/文档/分块三级；向量存 pgvector。

EMBED_DIM 是维度单一来源：迁移 0004 字面量 + ORM Vector(EMBED_DIM) + EmbeddingService 运行期校验共用。
content_tsv 为 GENERATED ALWAYS 列（服务端生成），ORM 声明 server_default=FetchedValue() 防 SQLAlchemy 写 INSERT。
CJK 逐字插空格使每个汉字成为 unigram token（无中文分词扩展下的 BM25 方案，raw string 防 Python 预编译）。
"""
from __future__ import annotations

import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import FetchedValue, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.base import Base, BaseModel

EMBED_DIM = 1024  # 与迁移 0004 vector(1024) 一致；换模型 = 新迁移 + ALTER TYPE


class KbCollection(BaseModel, Base):
    __tablename__ = "kb_collections"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, default=512, nullable=False)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=64, nullable=False)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 索引时快照


class KbDocument(BaseModel, Base):
    __tablename__ = "kb_documents"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_collections.id"), index=True, nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orgs.id"), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), default="text/plain", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)  # 上传即提取入库，reindex 零磁盘依赖
    status: Mapped[str] = mapped_column(
        String(16), default="uploaded", nullable=False
    )  # uploaded/chunking/indexing/indexed/failed/archived
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)


class KbChunk(Base):
    """分块（无软删列：派生数据，reindex 整体硬删重建）。"""

    __tablename__ = "kb_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uniq_kb_chunks_doc_idx"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_documents.id"), nullable=False
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_collections.id"), index=True, nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    content_tsv: Mapped[str] = mapped_column(
        # GENERATED ALWAYS AS ... STORED（迁移 0004 定义）；FetchedValue 防 ORM 写 INSERT；
        # 类型标 Text（tsvector 文本格式，asyncpg 原样返回），注解用 str 满足 registry 解析
        Text,
        server_default=FetchedValue(),
        nullable=False,
    )
