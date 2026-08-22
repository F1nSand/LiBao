"""工具执行器（docs 01 §7.3 tools/executor.py）。

执行安全四层之①输入校验（params_schema JSON Schema）+ 通用超时（OC3：asyncio.wait_for）
+ 失败静默重试（指数退避+抖动，docs 01 §5.4）+ 幂等去重（仅 idempotent 工具，进程内缓存）。
沙盒守卫：sandbox != none 返回"暂未实现"（Docker 沙盒为 M3 接缝）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from dataclasses import dataclass, replace
from typing import Any

from jsonschema import ValidationError, validate

from app.core.config import get_settings
from app.tools.registry import ToolSpec
from app.tools.sandbox import SandboxLevel

# ---- 重试/幂等常量 ----
_BACKOFF_BASE_MS = 300  # 指数退避基数（抖动上限同此值）
_IDEMPOTENCY_TTL_S = 3600
_MAX_IDEMPOTENCY_ENTRIES = 1024

# 幂等去重缓存（进程内回退；M4 Redis 持久化，见 README）——{key: (expire_monotonic, ToolResult)}
_idem_cache: dict[str, tuple[float, ToolResult]] = {}

# M4 完整版：工具级并发信号量（ToolSpec.max_concurrency 执行落点）——{spec.id: Semaphore(max_concurrency)}
_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


def _semaphore(spec: ToolSpec) -> asyncio.Semaphore:
    """取/建工具级信号量（懒创建；进程内限流，单实例足够，多实例需 Redis 计数为接缝）。"""
    sem = _SEMAPHORES.get(spec.id)
    if sem is None:
        sem = asyncio.Semaphore(max(1, spec.max_concurrency))
        _SEMAPHORES[spec.id] = sem
    return sem


@dataclass
class ToolResult:
    ok: bool
    output: Any
    summary: str
    duration_ms: int
    error: str | None = None
    placeholder: bool = False
    job_ref: str | None = None
    retries: int = 0


def _fingerprint(spec: ToolSpec, input: dict[str, Any]) -> str:
    """幂等指纹：显式 idempotency_key 优先，否则工具 id + 规范化 input 的 sha256。"""
    explicit = input.get("idempotency_key")
    if isinstance(explicit, str):
        return f"{spec.id}:{explicit}"
    canonical = json.dumps(
        {"tool": spec.id, "input": input}, sort_keys=True, ensure_ascii=False, default=str
    )
    return f"{spec.id}:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _serialize_result(result: ToolResult) -> str | None:
    """ToolResult → JSON；output 非 JSON 可序列化 → None（跳过 Redis，回退进程内）。"""
    try:
        return json.dumps(
            {
                "ok": result.ok,
                "output": result.output,
                "summary": result.summary,
                "duration_ms": result.duration_ms,
                "error": result.error,
                "placeholder": result.placeholder,
                "job_ref": result.job_ref,
                "retries": result.retries,
            },
            ensure_ascii=False,
        )
    except (TypeError, ValueError):
        return None


def _deserialize_result(raw: str) -> ToolResult | None:
    try:
        data = json.loads(raw)
        return ToolResult(**data)
    except (TypeError, ValueError, KeyError):
        return None


async def _cache_get(key: str) -> ToolResult | None:
    entry = _idem_cache.get(key)
    if entry is None:
        return None
    expire_ts, result = entry
    if expire_ts < time.monotonic():
        _idem_cache.pop(key, None)
        return None
    return result


async def _cache_put(key: str, result: ToolResult) -> None:
    # 进程内幂等缓存（本地单机化唯一路径；上限淘汰整体清空）
    if len(_idem_cache) >= _MAX_IDEMPOTENCY_ENTRIES:
        _idem_cache.clear()  # 上限淘汰：整体清空（最简单正确）
    _idem_cache[key] = (time.monotonic() + _IDEMPOTENCY_TTL_S, result)


async def execute(spec: ToolSpec, input: dict[str, Any]) -> ToolResult:
    """校验参数 → 沙盒守卫 → 幂等去重 → 重试循环（仅 handler 异常可重试）→ ToolResult。"""
    start = time.perf_counter()

    # ① 输入校验（快速失败，不重试）
    try:
        validate(instance=input, schema=spec.params_schema)
    except ValidationError as exc:
        return ToolResult(ok=False, output=None, summary="", duration_ms=0, error=f"参数校验失败: {exc.message}")

    if spec.handler is None:
        return ToolResult(ok=False, output=None, summary="", duration_ms=0, error=f"工具 {spec.id} 未注册 handler")

    # ② 沙盒守卫（M2.5 接缝：docker/microvm 未实现）
    if spec.sandbox != SandboxLevel.NONE:
        return ToolResult(ok=False, output=None, summary="", duration_ms=0, error="沙盒执行暂未实现（M3）")

    # ③ 幂等去重（执行前查，成功才写）
    idem_key = _fingerprint(spec, input) if spec.idempotent else None
    if idem_key is not None and (cached := await _cache_get(idem_key)) is not None:
        return cached  # ToolResult 只读，直接返回缓存实例

    # ④ 并发限流（ToolSpec.max_concurrency；幂等缓存命中不计入并发）
    async with _semaphore(spec):
        return await _execute_with_retries(spec, input, idem_key, start)


async def _execute_with_retries(
    spec: ToolSpec, input: dict[str, Any], idem_key: str | None, start: float
) -> ToolResult:
    """重试循环（仅 handler 普通异常可重试；超时直接返回）。"""
    timeout_sec = spec.timeout_ms / 1000
    last_error: Exception | None = None
    for attempt in range(spec.max_retries + 1):
        try:
            output = await _call_with_timeout(spec.handler, input, timeout_sec)
            duration = int((time.perf_counter() - start) * 1000)
            result = ToolResult(
                ok=True, output=output, summary=_summarize(output), duration_ms=duration, retries=attempt
            )
            # M4 完整版：handler 返回 {"placeholder":true, "job_ref":...} 的占位契约 → 透出到 ToolResult
            # （initiate_* 异步工具：立即返回占位，后台回填真值，docs 01 §5.5）
            if isinstance(output, dict) and output.get("job_ref"):
                result = replace(
                    result,
                    placeholder=bool(output.get("placeholder")),
                    job_ref=str(output["job_ref"]),
                    summary=str(output.get("summary") or result.summary),
                )
            if idem_key is not None:
                await _cache_put(idem_key, result)
            return result
        except TimeoutError:
            duration = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                ok=False, output=None, summary="", duration_ms=duration, error=f"工具执行超时（>{spec.timeout_ms}ms）"
            )
        except Exception as exc:  # noqa: BLE001  工具异常转结构化结果，不中断编排
            last_error = exc
            if attempt < spec.max_retries:
                await asyncio.sleep(_BACKOFF_BASE_MS / 1000 * (2**attempt) + random.uniform(0, _BACKOFF_BASE_MS / 1000))

    duration = int((time.perf_counter() - start) * 1000)
    return ToolResult(
        ok=False,
        output=None,
        summary="",
        duration_ms=duration,
        error=f"工具执行失败: {type(last_error).__name__}: {last_error}",
        retries=spec.max_retries,
    )


async def _call_with_timeout(handler: Any, input: dict[str, Any], timeout_sec: float) -> Any:
    """同步 handler 走 to_thread，异步 handler 直接 await；统一挂超时。"""
    coro = handler(**input) if asyncio.iscoroutinefunction(handler) else asyncio.to_thread(handler, **input)
    return await asyncio.wait_for(coro, timeout=timeout_sec)


def _summarize(output: Any) -> str:
    """工具结果文本摘要（tool_result.summary）。str 原样透传；dict/list json 化后截断到上限。"""
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    try:
        text = json.dumps(output, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(output)
    return text[: get_settings().tool_result_max_chars]
