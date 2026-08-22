"""用户实体（docs 04 §3.1）。本地单机化：单用户折叠为固定 admin（constants.py）。

角色：admin / developer / viewer（保留字段语义，折叠后恒 admin）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class User(Row):
    username: str
    name: str
    password_hash: str = ""
    role: str = "viewer"  # admin / developer / viewer
    org_id: uuid.UUID = uuid.UUID(int=0)
    enabled: bool = True
