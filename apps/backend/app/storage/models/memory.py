"""记忆实体（《02》数据模型 §3.8）。长期记忆（版本化只增）+ 业务状态（不入此表）。
maintenance 原料改读 messages（memory_trace 已于 2026-08-22 删除，见迁移 0016）。

只增原则（ADR-06）：改写 = 新增 version 行 + 更新卡片 current_version；删除 = 软删；历史永远保留。
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class LongTermMemory(Row):
    """长期记忆卡片（软删）。content 恒为 dict：json_card 存结构化数据，note 存 {"text": str}。"""

    user_id: uuid.UUID
    card_type: str  # json_card | note
    content: dict = field(default_factory=dict)
    title: str | None = None
    tags: list | None = None
    importance: float = 0.0  # 0-1
    source: str = "manual"  # manual | maintenance
    current_version: int = 1
    workspace_id: uuid.UUID | None = None  # 工作区记忆（M7-B）
    last_used_at: datetime | None = None


@dataclass(kw_only=True)
class LongTermMemoryVersion(Row):
    """长期记忆版本（append-only，UNIQUE(memory_id, version)）。"""

    memory_id: uuid.UUID
    version: int
    content: dict = field(default_factory=dict)
    importance: float = 0.0
