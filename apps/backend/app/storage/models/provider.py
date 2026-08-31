"""LLM Provider 配置（《02》前端设计 /settings Provider tab，前端契约已对齐）。

api_key 只写不读：API 响应仅 has_key 布尔；明文仅存文件（供启动同步到 LLM 客户端），永不回传。
"""

import uuid
from dataclasses import dataclass, field

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class ProviderConfig(Row):
    org_id: uuid.UUID
    name: str  # 配置别名（自由文本，非厂商名）
    website: str | None = None  # 官网链接（可选，纯展示，后端不校验不调用）
    base_url: str | None = None  # OpenAI 兼容请求地址（base 或完整 URL，见 is_full_url）
    is_full_url: bool = False  # 请求地址是否完整 URL（含 /chat/completions）；false = base，系统自动拼接
    model: str | None = None  # 模型名（裸名，无厂商前缀，如 gpt-4o / deepseek-chat）
    api_key: str | None = None  # 明文存储，仅服务端用，不 API 回传
    enabled: bool = True  # 是否当前激活（唯一激活：activate 保证至多一条 true）
    # 模型能力声明（2026-08-27 多模态适配）：[] 未声明→按模型名 pattern 兜底；["vision"]=强制视觉；
    # 其他非空（不含 vision）=强制非视觉。序列化随 GET /settings/providers(/active) 返回。
    capabilities: list[str] = field(default_factory=list)
