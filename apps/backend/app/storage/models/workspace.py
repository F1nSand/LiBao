"""工作区实体（M7-B，《02》数据模型 §3.11）。

工作区 = 本地文件夹（root_path）+ 项目级 agent 增量（project_instructions）+ 独立记忆 + 项目 skills/工具。
root_path 由后端托管（{workspaces_root}/{id}），用户不指定磁盘路径（防越权）。
"""

import uuid
from dataclasses import dataclass

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class Workspace(Row):
    org_id: uuid.UUID
    name: str
    description: str = ""
    root_path: str = ""
    project_instructions: str = ""
    status: str = "active"  # active/archived
    # 创建者（审计元数据）
    created_by: uuid.UUID | None = None
