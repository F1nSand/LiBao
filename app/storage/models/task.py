"""任务实体（docs 04 §3.3）。task.id = LangGraph thread_id（异步模式，M1 对话为主暂不落任务）。"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class Task(Row):
    user_id: uuid.UUID
    agent_id: uuid.UUID
    status: str = "pending"  # pending / running / waiting_confirm / cancelled / done / failed
    input: dict = field(default_factory=dict)
    output: dict | None = None
    error: dict | None = None  # {code, message}
    parent_task_id: uuid.UUID | None = None
    pending_confirm: dict | None = None
    progress: float = 0.0
    placeholder_events: list | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
