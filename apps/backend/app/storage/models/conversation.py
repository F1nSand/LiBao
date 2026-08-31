"""会话实体（《02》数据模型 §3.2）。conversation.id = LangGraph thread_id（ADR-03 sessionless）。"""

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
    # Claude Code-style active branch/cursor.  Old conversation rows deserialize
    # with these defaults, so enabling checkpoints is backward compatible.
    active_message_head_id: uuid.UUID | None = None
    message_cursor_initialized: bool = False
    active_graph_checkpoint_id: str | None = None
    graph_cursor_initialized: bool = False
    active_code_node_id: uuid.UUID | None = None
    history_revision: int = 0
