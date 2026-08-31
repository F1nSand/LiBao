"""单机化折叠常量：固定 admin 用户 + 默认 org（本地单机单用户，无多租户概念）。

repository 层 org_id 过滤参数签名保留、实现忽略（org 恒为默认值）；deps.get_current_user
恒返回 ADMIN_USER。将来放开多用户仅需改此文件。
"""

from __future__ import annotations

import uuid

from app.storage.models.user import User

DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
ADMIN_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

# 固定 admin（password_hash 占位——单机无登录，不校验密码）
ADMIN_USER = User(
    id=ADMIN_USER_ID,
    username="admin",
    password_hash="local-single-user",
    name="管理员",
    role="admin",
    org_id=DEFAULT_ORG_ID,
    enabled=True,
)
