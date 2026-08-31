"""通知实体（《02》接口契约 §5.11 / FrontEnd Notification）。

产生源：任务事件（done/failed）+ demo_notify 工具确认后。SSE 按 user_id 推送。
append-only：前端仅读/已读（read 标记）。
"""

import uuid
from dataclasses import dataclass

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class Notification(Row):
    user_id: uuid.UUID
    title: str
    body: str | None = None
    level: str = "info"  # info/success/warning/error
    read: bool = False
