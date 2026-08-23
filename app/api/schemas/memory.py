"""记忆 schema（docs 03 §5.7）。创建/更新共用；body 恒为 dict（note 存 {"text": str}）。

P5：创建支持 workspace_id（工作区项目卡片可选）/ importance；更新端点启用版本化改写。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CreateLongTermMemoryRequest(BaseModel):
    card_type: str  # json_card | note
    title: str | None = None
    body: dict[str, Any]
    tags: list[str] | None = None
    importance: float | None = None  # 0-1（缺省 0）
    workspace_id: str | None = None  # 空 = 全局记忆


class UpdateLongTermMemoryRequest(BaseModel):
    body: dict[str, Any]
    importance: float | None = None
