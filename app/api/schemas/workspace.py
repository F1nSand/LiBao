"""工作区 schema（M7-B，docs 03 §5.14）。"""
from __future__ import annotations

from pydantic import BaseModel


class CreateWorkspaceRequest(BaseModel):
    name: str
    description: str = ""
    system_prompt_fragment: str = ""


class UpdateWorkspaceRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt_fragment: str | None = None


class WriteFileRequest(BaseModel):
    path: str
    content: str
