"""组织级命令执行后端偏好。"""

import uuid
from dataclasses import dataclass

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class SandboxPreference(Row):
    org_id: uuid.UUID
    mode: str = "powershell"
