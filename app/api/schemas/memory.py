"""记忆 schema（docs 03 §5.7）。创建/维护共用；body 恒为 dict（note 存 {"text": str}）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CreateLongTermMemoryRequest(BaseModel):
    card_type: str  # json_card | note
    title: str | None = None
    body: dict[str, Any]
    tags: list[str] | None = None


class MemoryMaintenanceRequest(BaseModel):
    pass  # 无参数；触发即整理
