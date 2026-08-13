"""工具执行器（docs 01 §7.3 tools/executor.py）。

执行安全四层之①输入校验（params_schema JSON Schema）+ 通用超时（OC3：asyncio.wait_for）。
M1 无沙箱（none）/无重试/无幂等键；require_confirm 路径在 M2 才走 interrupt。
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from jsonschema import ValidationError, validate

from app.tools.registry import ToolSpec


@dataclass
class ToolResult:
    ok: bool
    output: Any
    summary: str
    duration_ms: int
    error: str | None = None
    placeholder: bool = False
    job_ref: str | None = None


async def execute(spec: ToolSpec, input: dict[str, Any]) -> ToolResult:
    """校验参数 → 超时执行 handler → 结构化 ToolResult。"""
    start = time.perf_counter()

    # ① 输入校验（快速失败）
    try:
        validate(instance=input, schema=spec.params_schema)
    except ValidationError as exc:
        return ToolResult(ok=False, output=None, summary="", duration_ms=0, error=f"参数校验失败: {exc.message}")

    if spec.handler is None:
        return ToolResult(ok=False, output=None, summary="", duration_ms=0, error=f"工具 {spec.id} 未注册 handler")

    # ② 通用超时 kill（OC3）
    timeout_sec = spec.timeout_ms / 1000
    try:
        output = await _call_with_timeout(spec.handler, input, timeout_sec)
        duration = int((time.perf_counter() - start) * 1000)
        return ToolResult(ok=True, output=output, summary=_summarize(output), duration_ms=duration)
    except TimeoutError:
        duration = int((time.perf_counter() - start) * 1000)
        return ToolResult(
            ok=False, output=None, summary="", duration_ms=duration, error=f"工具执行超时（>{spec.timeout_ms}ms）"
        )
    except Exception as exc:  # noqa: BLE001  工具异常转结构化结果，不中断编排
        duration = int((time.perf_counter() - start) * 1000)
        return ToolResult(
            ok=False, output=None, summary="", duration_ms=duration, error=f"工具执行失败: {type(exc).__name__}: {exc}"
        )


async def _call_with_timeout(handler: Any, input: dict[str, Any], timeout_sec: float) -> Any:
    """同步 handler 走 to_thread，异步 handler 直接 await；统一挂超时。"""
    coro = handler(**input) if asyncio.iscoroutinefunction(handler) else asyncio.to_thread(handler, **input)
    return await asyncio.wait_for(coro, timeout=timeout_sec)


def _summarize(output: Any) -> str:
    """工具结果文本摘要（tool_result.summary）。简单结构即 json 化，超阈值截断。"""
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    try:
        text = json.dumps(output, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(output)
    return text[:500]
