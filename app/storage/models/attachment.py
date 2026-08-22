"""附件实体（docs 04 §3.7）。本地磁盘存储 MVP（MinIO 为 M4 接缝）；软删行 + 删磁盘文件。

状态机：uploaded → analyzing → ready | failed（前端 2.5s 轮询 /attachments/{id}/analysis）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class Attachment(Row):
    user_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int = 0
    storage_path: str = ""  # {upload_dir}/{attachment_id}
    status: str = "uploaded"  # uploaded/analyzing/ready/failed
    analysis: dict | None = None
    error: str | None = None
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
