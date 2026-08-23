"""LLM Provider 配置（docs 02 /settings Provider tab，前端契约已对齐）。

api_key 只写不读：API 响应仅 has_key 布尔；明文仅存文件（供启动同步到 LLM 客户端），永不回传。
"""

import uuid
from dataclasses import dataclass

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class ProviderConfig(Row):
    org_id: uuid.UUID
    name: str
    base_url: str | None = None  # LiteLLM api_base
    model: str | None = None  # LiteLLM model（provider/model 格式）
    api_key: str | None = None  # 明文存储，仅服务端用，不 API 回传
    enabled: bool = True
