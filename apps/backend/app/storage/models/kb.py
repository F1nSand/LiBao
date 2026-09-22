"""知识库实体（《02》数据模型 §3.6）。集合/文档/分块三级；向量存 LanceDB（本地单机化）。

EMBED_DIM 是维度单一来源：LanceDB schema + EmbeddingService 运行期校验共用。
分块为派生数据：文本+序号进集合 index.json，向量进 kb/vectors.lance；无软删列（reindex 硬删重建）。
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.storage.file.rows import Row

EMBED_DIM = 1024  # 与 LanceDB schema vector(1024) 一致；换模型 = 重建向量库


@dataclass(kw_only=True)
class KbCollection(Row):
    org_id: uuid.UUID
    name: str
    description: str = ""
    chunk_size: int = 512
    chunk_overlap: int = 64
    embedding_model: str | None = None  # 索引时快照
    chunking_strategy: str = "auto"
    fts_tokenizer: str = "icu"


@dataclass(kw_only=True)
class KbDocument(Row):
    collection_id: uuid.UUID
    org_id: uuid.UUID
    filename: str
    content_type: str = "text/plain"
    size_bytes: int = 0
    content: str = ""  # 上传即提取入库；原文另落 documents/<doc_id>.md
    status: str = "uploaded"  # uploaded/chunking/indexing/indexed/failed/archived
    chunk_count: int = 0
    error: str | None = None
    active_generation: str | None = None
    building_generation: str | None = None
    index_state: str = "idle"
    chunking_version: str | None = None
    retrieval_schema_version: int = 1
    embedding_dimension: int | None = None
    last_indexed_at: datetime | None = None
    last_index_error: str | None = None


@dataclass(kw_only=True)
class KbChunk(Row):
    """分块（无软删列：派生数据，reindex 整体硬删重建）。向量不落行内（进 LanceDB）。"""

    document_id: uuid.UUID
    collection_id: uuid.UUID
    org_id: uuid.UUID
    chunk_index: int
    content: str
    embedding: list | None = None  # 向量（仅 pipeline 传参用，不落 index.json）
    generation: str = "legacy-v1"
    retrieval_text: str = ""
    section_path: tuple[str, ...] = ()
    start_offset: int = 0
    end_offset: int = 0
    token_count: int = 0
    chunking_strategy: str = "auto"
