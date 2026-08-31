"""任务实体（《02》数据模型 §3.3）。后台任务和普通聊天运行都以 Task 作为取消/恢复载体。"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class Task(Row):
    user_id: uuid.UUID
    agent_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    recovery_graph_checkpoint_id: str | None = None
    status: str = "pending"  # pending / running / waiting_confirm / cancelled / done / failed
    input: dict = field(default_factory=dict)
    output: dict | None = None
    error: dict | None = None  # {code, message}
    parent_task_id: uuid.UUID | None = None
    pending_confirm: dict | None = None
    last_event_seq: int = 0
    recovery_attempts: int = 0
    recovery_key: str | None = None
    progress: float = 0.0
    placeholder_events: list | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
