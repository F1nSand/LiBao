"""load_skill 内置 meta 工具（M7-A）：按 name 取回启用 skill 的正文（渐进式披露，docs 01 §4.2.1）。

五层约束：工具层→存储层经 sessionmaker 桥 + SkillRepository（同 kb_search）。
org 上下文缺失 / 未命中 → 降级错误结果（不抛，executor 正常打包）。
"""
from __future__ import annotations

import uuid
from typing import Any

from app.storage.db import get_sessionmaker
from app.storage.repositories.skill import SkillRepository
from app.tools.context import get_tool_org


async def load_skill_handler(name: str) -> dict[str, Any]:
    org_id = get_tool_org()
    if not org_id:
        return {"error": "缺少组织上下文"}
    sessionmaker = get_sessionmaker()
    if sessionmaker is None:
        return {"error": "skill 服务不可用"}
    try:
        async with sessionmaker() as db:
            skill = await SkillRepository(db).get_by_org_name(uuid.UUID(org_id), name)
    except Exception as exc:  # noqa: BLE001  加载故障不击穿工具调用
        return {"error": f"加载失败: {str(exc)[:300]}"}
    if skill is None or not skill.enabled:
        return {"error": f"skill {name} 不存在或未启用"}
    return {"name": skill.name, "description": skill.description, "body": skill.body}
