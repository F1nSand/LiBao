"""Skill schema（M7-A，docs 03 §5.14）。创建默认 enabled=false（服务层强制）。"""

from __future__ import annotations

from pydantic import BaseModel


class CreateSkillRequest(BaseModel):
    name: str
    description: str = ""
    body: str = ""


class SkillImportRequest(BaseModel):
    url: str


class SkillToggleRequest(BaseModel):
    enabled: bool
