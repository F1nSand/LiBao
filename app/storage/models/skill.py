"""Skill 实体（M7-A，docs 01 §4.2.1 / docs 04 §3.11）。

org 级 skill = SKILL.md（name + description 路由描述 + body 正文）。默认 enabled=false（约束优先）。
主 agent 自动使用 org 内 enabled skills：路由描述进 system_prompt 前缀，正文经 tl_load_skill 按需取回。
"""

import uuid
from dataclasses import dataclass

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class Skill(Row):
    org_id: uuid.UUID
    name: str
    description: str = ""
    body: str = ""
    source: str = "manual"  # manual/git
    enabled: bool = False
