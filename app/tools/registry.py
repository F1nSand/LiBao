"""工具注册中心（docs 01 §7.1 tools/registry.py）。

ToolSpec 字段即 M2 工具系统的接缝（sandbox/require_confirm/allowlist/idempotent 已预留）。
aci() 生成 OpenAI function schema，函数名取 spec.name（LLM 侧）；注册表键为 spec.id（稳定唯一）。
acis() 按 id 排序输出，保证静态前缀字节稳定。
"""
from __future__ import annotations

import enum
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from app.tools.sandbox import SandboxLevel


class ToolType(enum.StrEnum):
    PERCEPTION = "perception"
    EXECUTION = "execution"
    COLLABORATION = "collaboration"
    USER_COMMS = "user_comms"
    EVENT = "event"


@dataclass(frozen=True)
class ToolSpec:
    id: str
    name: str
    description: str
    params_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}, "required": []})
    enabled: bool = False
    require_confirm: bool = False
    sandbox: SandboxLevel = SandboxLevel.NONE
    idempotent: bool = False
    tool_type: ToolType = ToolType.EXECUTION
    mcp_source: str | None = None
    timeout_ms: int = 30000
    max_concurrency: int = 1
    max_retries: int = 0  # 失败静默重试次数（docs 01 §5.4；0=不重试）
    allowlist: list[str] | None = None
    handler: Callable[..., Any] | None = None

    def aci(self) -> dict[str, Any]:
        """OpenAI function schema（ACI）。函数名 = spec.name。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.params_schema,
            },
        }


_REGISTRY: dict[str, ToolSpec] = {}
_NAME_INDEX: dict[str, str] = {}  # name → id 反向索引（name 唯一性不变量保证单值）


def register(spec: ToolSpec) -> None:
    if spec.id in _REGISTRY:
        raise ValueError(f"工具 id 冲突：{spec.id}")
    if spec.name in _NAME_INDEX:
        raise ValueError(f"工具名冲突（I7 遮蔽拒绝）：{spec.name} 已注册为 {_NAME_INDEX[spec.name]}")
    _REGISTRY[spec.id] = spec
    _NAME_INDEX[spec.name] = spec.id


def get(tool_id: str) -> ToolSpec | None:
    return _REGISTRY.get(tool_id)


def unregister(tool_id: str) -> None:
    """移除注册（测试清理 / MCP 源注销时使用）。"""
    spec = _REGISTRY.pop(tool_id, None)
    if spec is not None:
        _NAME_INDEX.pop(spec.name, None)


def set_enabled(tool_id: str, enabled: bool) -> None:
    """启停同步桥（M2）：frozen dataclass 用 replace 换新 spec 写回注册表。

    与 DB tool_definition.enabled 联动（ToolService.set_enabled 调用），
    使「默认关闭」原则对内置工具实时生效（acis_for_tools / agent_can_use 立即过滤）。
    """
    spec = _REGISTRY.get(tool_id)
    if spec is None or spec.enabled == enabled:
        return
    _REGISTRY[tool_id] = replace(spec, enabled=enabled)


def patch_spec(tool_id: str, **fields: Any) -> None:
    """运行时字段同步桥（M2）：PUT /tools 的运行时配置（require_confirm/idempotent/
    sandbox/timeout_ms/max_concurrency）写入 DB 后同步到 registry spec，执行即刻生效。"""
    spec = _REGISTRY.get(tool_id)
    if spec is None:
        return
    updates = {k: v for k, v in fields.items() if getattr(spec, k, None) != v}
    if updates:
        _REGISTRY[tool_id] = replace(spec, **updates)


def get_by_name(name: str) -> ToolSpec | None:
    """按 ACI 函数名查找（模型 tool_call 里带的是 spec.name）。O(1) 反向索引。"""
    tool_id = _NAME_INDEX.get(name)
    return _REGISTRY.get(tool_id) if tool_id else None


def agent_can_use(spec: ToolSpec | None, tool_ids: Iterable[str]) -> bool:
    """授权谓词：agent 只能执行其启用集内且 enabled 的工具。

    ACI 绑定（acis_for_tools）与执行守卫（tool_execute）共用此单一不变量，防两处漂移。
    """
    return spec is not None and spec.id in tool_ids and spec.enabled


def all_tools() -> list[ToolSpec]:
    return list(_REGISTRY.values())


def enabled_tools() -> list[ToolSpec]:
    return [s for s in _REGISTRY.values() if s.enabled]


def acis() -> list[dict[str, Any]]:
    """全部工具 ACI，按 id 排序（前缀稳定铁律 docs 01 §4.1）。"""
    return [s.aci() for s in sorted(_REGISTRY.values(), key=lambda s: s.id)]
