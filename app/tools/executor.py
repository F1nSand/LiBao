"""工具执行器（docs 01 §7.3 tools/executor.py）。

执行安全四层之①输入校验（params_schema JSON Schema）+ 通用超时（OC3：asyncio.wait_for）
+ 失败静默重试（指数退避+抖动，docs 01 §5.4）+ 幂等去重（仅 idempotent 工具，进程内缓存）。
沙盒守卫：MICROVM 明确返回不支持；WORKSPACE/DOCKER 通过命令构建器分别走宿主 runner 或一次性容器执行。
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import random
import time
from dataclasses import dataclass, replace
from typing import Any

from jsonschema import ValidationError, validate

from app.core.config import get_settings
from app.tools.context import get_tool_workspace_root
from app.tools.registry import ToolGateAction, ToolSpec
from app.tools.sandbox import (
    SandboxCommand,
    SandboxErrorCode,
    SandboxFailure,
    SandboxLevel,
    SandboxResult,
    WorkspaceCommand,
    run_docker_command,
    run_workspace_command,
)

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
    summary_truncated: bool = False
    summary_original_chars: int = 0


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
                "summary_truncated": result.summary_truncated,
                "summary_original_chars": result.summary_original_chars,
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


async def execute(
    spec: ToolSpec,
    input: dict[str, Any],
    *,
    approved: bool = False,
    context: dict[str, Any] | None = None,
) -> ToolResult:
    """校验参数 → 沙盒守卫 → 幂等去重 → 重试循环（仅 handler 异常可重试）→ ToolResult。"""
    start = time.perf_counter()

    # ① 输入校验（快速失败，不重试）
    try:
        validate(instance=input, schema=spec.params_schema)
    except ValidationError as exc:
        return ToolResult(ok=False, output=None, summary="", duration_ms=0, error=f"参数校验失败: {exc.message}")

    if spec.preflight is not None:
        try:
            decision = spec.preflight(input, context or {})
        except Exception as exc:  # noqa: BLE001 - policy failures fail closed
            return ToolResult(
                ok=False,
                output=None,
                summary="",
                duration_ms=0,
                error=f"{SandboxErrorCode.POLICY_BLOCKED.value}: 策略预检失败: {exc}",
            )
        if decision.action == ToolGateAction.BLOCK:
            return ToolResult(
                ok=False,
                output={"verdict": "block", "reason": decision.reason, "risk": decision.risk},
                summary=decision.reason,
                duration_ms=0,
                error=f"{SandboxErrorCode.POLICY_BLOCKED.value}: {decision.reason}",
            )
        if decision.action == ToolGateAction.CONFIRM and not approved:
            return ToolResult(
                ok=False,
                output={"verdict": "confirm", "reason": decision.reason, "risk": decision.risk},
                summary=decision.reason,
                duration_ms=0,
                error=f"{SandboxErrorCode.CONFIRM_REQUIRED.value}: {decision.reason}",
            )

    if spec.sandbox == SandboxLevel.MICROVM:
        return ToolResult(
            ok=False,
            output=None,
            summary="",
            duration_ms=0,
            error=f"{SandboxErrorCode.UNSUPPORTED_TOOL.value}: microvm 沙箱暂不支持",
        )

    if spec.sandbox in (SandboxLevel.DOCKER, SandboxLevel.WORKSPACE) and spec.sandbox_command_builder is None:
        return ToolResult(
            ok=False,
            output=None,
            summary="",
            duration_ms=0,
            error=f"{SandboxErrorCode.UNSUPPORTED_TOOL.value}: docker 工具缺少命令构建器",
        )
    if spec.sandbox == SandboxLevel.NONE and spec.handler is None:
        return ToolResult(ok=False, output=None, summary="", duration_ms=0, error=f"工具 {spec.id} 未注册 handler")

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
            output = await _call_with_timeout(spec, input, timeout_sec)
            duration = int((time.perf_counter() - start) * 1000)
            summary, summary_truncated, original_chars = _summarize_with_meta(output)
            result = ToolResult(
                ok=True,
                output=output,
                summary=summary,
                duration_ms=duration,
                retries=attempt,
                summary_truncated=summary_truncated,
                summary_original_chars=original_chars,
            )
            # M4 完整版：handler 返回 {"placeholder":true, "job_ref":...} 的占位契约 → 透出到 ToolResult
            # （initiate_* 异步工具：立即返回占位，后台回填真值，docs 01 §5.5）
            if isinstance(output, dict) and output.get("job_ref"):
                placeholder_summary = _bounded_text(str(output.get("summary") or result.summary))
                result = replace(
                    result,
                    placeholder=bool(output.get("placeholder")),
                    job_ref=str(output["job_ref"]),
                    summary=placeholder_summary[0],
                    summary_truncated=placeholder_summary[1],
                    summary_original_chars=placeholder_summary[2],
                )
            if idem_key is not None:
                await _cache_put(idem_key, result)
            return result
        except SandboxFailure as exc:
            duration = int((time.perf_counter() - start) * 1000)
            summary, summary_truncated, original_chars = (
                _summarize_with_meta(exc.output) if exc.output is not None else ("", False, 0)
            )
            result = ToolResult(
                ok=False,
                output=exc.output,
                summary=summary,
                duration_ms=duration,
                error=f"{exc.code.value}: {exc.message}",
                retries=attempt,
                summary_truncated=summary_truncated,
                summary_original_chars=original_chars,
            )
            if exc.retryable and attempt < spec.max_retries:
                last_error = exc
                await asyncio.sleep(
                    _BACKOFF_BASE_MS / 1000 * (2**attempt) + random.uniform(0, _BACKOFF_BASE_MS / 1000)
                )
                continue
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


async def _run_docker_attempt(spec: ToolSpec, input: dict[str, Any]) -> dict[str, Any]:
    builder = spec.sandbox_command_builder
    if builder is None:
        raise SandboxFailure(SandboxErrorCode.UNSUPPORTED_TOOL, "命令沙箱工具缺少命令构建器")
    built = builder(**input)
    command = await built if inspect.isawaitable(built) else built
    if not isinstance(command, (SandboxCommand, WorkspaceCommand)):
        raise SandboxFailure(SandboxErrorCode.UNSUPPORTED_TOOL, "命令构建器返回了无效类型")
    root = get_tool_workspace_root()
    if not root:
        raise SandboxFailure(SandboxErrorCode.INVALID_WORKDIR, "不在工作区上下文")
    settings = get_settings()
    if isinstance(command, WorkspaceCommand):
        result: SandboxResult = await run_workspace_command(
            command,
            workspace_root=root,
            timeout_ms=spec.timeout_ms,
            settings=settings,
        )
    else:
        result = await run_docker_command(command, workspace_root=root, timeout_ms=spec.timeout_ms, settings=settings)
    output: dict[str, Any] = {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.exit_code,
    }
    if result.truncated:
        output["truncated"] = True
    if note := command.env.get("LIBAO_SHELL_REVIEW_NOTE") or command.env.get("LIBAO_BASH_REVIEW_NOTE"):
        output["note"] = note
    return output


async def _call_with_timeout(spec: ToolSpec, input: dict[str, Any], timeout_sec: float) -> Any:
    """命令沙箱将构建与执行包在一次总超时内；NONE 继续兼容同步/异步 handler。"""
    if spec.sandbox in (SandboxLevel.DOCKER, SandboxLevel.WORKSPACE):
        return await asyncio.wait_for(_run_docker_attempt(spec, input), timeout=timeout_sec)
    handler = spec.handler
    coro = handler(**input) if asyncio.iscoroutinefunction(handler) else asyncio.to_thread(handler, **input)
    return await asyncio.wait_for(coro, timeout=timeout_sec)


def _bounded_text(text: str) -> tuple[str, bool, int]:
    limit = max(0, int(get_settings().tool_result_max_chars))
    return text[:limit], len(text) > limit, len(text)


def _summarize_with_meta(output: Any) -> tuple[str, bool, int]:
    """统一限制工具摘要；字符串与结构化结果使用同一字符预算并返回截断元数据。"""
    if output is None:
        return "", False, 0
    if isinstance(output, str):
        return _bounded_text(output)
    try:
        text = json.dumps(output, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(output)
    return _bounded_text(text)


def _summarize(output: Any) -> str:
    """向旧调用方提供摘要字符串；新的 ToolResult 同时携带截断元数据。"""
    return _summarize_with_meta(output)[0]
