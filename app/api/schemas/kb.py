"""知识库 schema（docs 03 §5.6）。集合创建/检索请求。"""
from __future__ import annotations

import uuid

from pydantic import BaseModel


class CreateCollectionRequest(BaseModel):
    name: str
    description: str = ""
    chunk_size: int = 512
    overlap: int = 64


class KbSearchRequest(BaseModel):
    collection_ids: list[uuid.UUID] = []
    query: str
    top_k: int = 5
    hybrid: dict | None = None  # {"semantic": bool, "bm25": bool} 开关；缺省双通道（S10 注释与实现一致）


class KbStatusRequest(BaseModel):
    status: str  # archived
