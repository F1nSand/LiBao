"""会话实体（docs 04 §3.2）。conversation.id = LangGraph thread_id（ADR-03 sessionless）。"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class Conversation(Row):
    user_id: uuid.UUID
    agent_id: uuid.UUID
    title: str = "新会话"
    status: str = "active"
    max_messages: int = 1000
    retention_days: int = 180
    last_message_at: datetime | None = None
    workspace_id: uuid.UUID | None = None  # 工作区对话（M7-B）
