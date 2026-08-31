"""T4 执行器测试：重试（指数退避）、幂等去重、沙盒守卫、校验/超时不重试。纯单元，无 DB。

_no_redis autouse：幂等单测强制走进程内缓存（Redis 持久化会跨 run 污染固定指纹的断言；
Redis 集成由 test_idempotency_redis.py 单独覆盖）。
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.tools import executor
from app.tools.registry import ToolGateAction, ToolGateDecision, ToolSpec
from app.tools.sandbox import SandboxCommand, SandboxErrorCode, SandboxFailure, SandboxLevel, SandboxResult


def _spec(**kw) -> ToolSpec:
    base = {
        "id": "t_x",
        "name": "x",
        "description": "d",
        "params_schema": {"type": "object", "properties": {}, "required": []},
    }
    base.update(kw)
    return ToolSpec(**base)


def test_summarize_dict_not_truncated_at_500():
    """修复回归：dict 输出不再被截断到 500 字符，而是按 tool_result_max_chars 上限。"""
    big = {"items": [{"name": f"item-{i}", "desc": "x" * 100} for i in range(20)]}
    summary = executor._summarize(big)
    assert len(summary) > 500  # 不再截断到 500
    assert len(summary) <= get_settings().tool_result_max_chars
    assert "item-19" in summary  # 末尾条目对 LLM 可见


def test_summarize_str_is_bounded_with_metadata():
    long_str = "hello" * 2000  # 10000 字符
    assert len(executor._summarize(long_str)) == get_settings().tool_result_max_chars
    summary, truncated, original_chars = executor._summarize_with_meta(long_str)
    assert summary == executor._summarize(long_str)
    assert truncated is True
    assert original_chars == len(long_str)


async def test_retry_success_after_two_failures():
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return {"ok": True}

    result = await executor.execute(_spec(max_retries=2, handler=handler), {})
    assert result.ok is True
    assert result.retries == 2
    assert calls["n"] == 3


async def test_tool_result_reports_bounded_summary_metadata():
    long_str = "x" * (get_settings().tool_result_max_chars + 17)
    result = await executor.execute(_spec(handler=lambda: long_str), {})
    assert result.ok is True
    assert len(result.summary) == get_settings().tool_result_max_chars
    assert result.summary_truncated is True
    assert result.summary_original_chars == len(long_str)


async def test_preflight_blocks_without_invoking_handler():
    called = {"value": False}

    def handler(**kw):
        called["value"] = True
        return {"ok": True}

    def preflight(_input, _context):
        return ToolGateDecision(ToolGateAction.BLOCK, "禁止", "high")

    result = await executor.execute(_spec(handler=handler, preflight=preflight), {})
    assert not result.ok
    assert "sandbox_policy_blocked" in (result.error or "")
    assert called["value"] is False


async def test_preflight_confirmation_requires_explicit_approval():
    def preflight(_input, _context):
        return ToolGateDecision(ToolGateAction.CONFIRM, "需要确认", "high")

    spec = _spec(handler=lambda: {"ok": True}, preflight=preflight)
    denied = await executor.execute(spec, {})
    assert not denied.ok and "sandbox_confirmation_required" in (denied.error or "")
    approved = await executor.execute(spec, {}, approved=True)
    assert approved.ok


async def test_retry_all_fail():
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        raise RuntimeError("always fails")

    result = await executor.execute(_spec(max_retries=2, handler=handler), {})
    assert result.ok is False
    assert result.retries == 2
    assert calls["n"] == 3
    assert "RuntimeError" in result.error


async def test_validation_failure_not_retried():
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        return {"ok": True}

    spec = ToolSpec(
        id="t_req", name="req", description="d",
        params_schema={"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
        max_retries=3, handler=handler,
    )
    result = await executor.execute(spec, {})
    assert result.ok is False
    assert "参数校验失败" in result.error
    assert calls["n"] == 0  # 校验失败不触发 handler，更不重试


async def test_timeout_not_retried():
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        time.sleep(1)

    result = await executor.execute(_spec(max_retries=3, timeout_ms=50, handler=handler), {})
    assert result.ok is False
    assert "超时" in result.error
    assert result.retries == 0
    assert calls["n"] == 1  # 超时直接返回，不重试


async def test_idempotent_dedupes_same_input():
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        return {"result": calls["n"]}

    spec = _spec(idempotent=True, handler=handler)
    r1 = await executor.execute(spec, {})
    r2 = await executor.execute(spec, {})
    assert calls["n"] == 1  # 同指纹去重
    assert r1.output == r2.output
    assert r2.duration_ms == r1.duration_ms  # 命中缓存（时长一致）


async def test_idempotent_explicit_key_differs():
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        return {"result": calls["n"]}

    spec = _spec(idempotent=True, handler=handler)
    await executor.execute(spec, {"idempotency_key": "k1"})
    await executor.execute(spec, {"idempotency_key": "k2"})
    assert calls["n"] == 2  # 显式 key 不同 → 不命中


async def test_non_idempotent_not_cached():
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        return {"result": calls["n"]}

    spec = _spec(idempotent=False, handler=handler)
    await executor.execute(spec, {})
    await executor.execute(spec, {})
    assert calls["n"] == 2  # 非幂等不缓存


async def test_docker_requires_command_builder():
    result = await executor.execute(_spec(sandbox=SandboxLevel.DOCKER, handler=lambda: {"ok": True}), {})
    assert result.ok is False
    assert "sandbox_unsupported_tool" in result.error


async def test_docker_runner_receives_workspace_and_spec_timeout(monkeypatch, tmp_path):
    calls = []

    async def builder(command):
        return SandboxCommand(argv=("bash", "-lc", command))

    async def runner(command, *, workspace_root, timeout_ms, settings):
        calls.append((command, workspace_root, timeout_ms, settings))
        return SandboxResult(exit_code=0, stdout="ok", stderr="")

    monkeypatch.setattr(executor, "run_docker_command", runner)
    monkeypatch.setattr(executor, "get_tool_workspace_root", lambda: str(tmp_path), raising=False)
    settings = SimpleNamespace(tool_result_max_chars=8000)
    monkeypatch.setattr(executor, "get_settings", lambda: settings)
    spec = _spec(
        id="t_docker_runner",
        name="docker_runner",
        sandbox=SandboxLevel.DOCKER,
        sandbox_command_builder=builder,
        timeout_ms=1234,
        params_schema={"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
    )

    result = await executor.execute(spec, {"command": "echo ok"})
    assert result.ok is True
    assert calls and calls[0][0].argv == ("bash", "-lc", "echo ok")
    assert calls[0][1] == str(tmp_path)
    assert calls[0][2] == 1234


async def test_microvm_remains_unsupported():
    result = await executor.execute(_spec(sandbox=SandboxLevel.MICROVM), {})
    assert result.ok is False
    assert "sandbox_unsupported_tool" in result.error


@pytest.mark.parametrize(
    ("code", "retryable", "expected_calls"),
    [
        (SandboxErrorCode.TIMEOUT, False, 1),
        (SandboxErrorCode.UNSUPPORTED_TOOL, False, 1),
        (SandboxErrorCode.INVALID_WORKDIR, False, 1),
        (SandboxErrorCode.IMAGE_MISSING, False, 1),
        (SandboxErrorCode.EXIT_NONZERO, False, 1),
        (SandboxErrorCode.START_FAILED, True, 2),
        (SandboxErrorCode.UNAVAILABLE, True, 2),
    ],
)
async def test_docker_failure_retry_policy(monkeypatch, tmp_path, code, retryable, expected_calls):
    calls = {"runner": 0}

    async def builder():
        return SandboxCommand(argv=("bash", "-lc", "true"))

    async def runner(*args, **kwargs):
        calls["runner"] += 1
        raise SandboxFailure(code, "failure", retryable=retryable)

    async def no_sleep(*args):
        return None

    monkeypatch.setattr(executor, "run_docker_command", runner)
    monkeypatch.setattr(executor, "get_tool_workspace_root", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr(executor.asyncio, "sleep", no_sleep)
    spec = _spec(
        id=f"t_{code.value}",
        name=f"docker_{code.value}",
        sandbox=SandboxLevel.DOCKER,
        sandbox_command_builder=builder,
        max_retries=1,
    )

    result = await executor.execute(spec, {})
    assert result.ok is False
    assert code.value in result.error
    assert calls["runner"] == expected_calls


async def test_docker_failure_is_not_cached_until_success(monkeypatch, tmp_path):
    executor._idem_cache.clear()
    calls = {"runner": 0}

    async def builder():
        return SandboxCommand(argv=("bash", "-lc", "true"))

    async def runner(*args, **kwargs):
        calls["runner"] += 1
        if calls["runner"] == 1:
            raise SandboxFailure(SandboxErrorCode.EXIT_NONZERO, "failed")
        return SandboxResult(exit_code=0, stdout="ok", stderr="")

    monkeypatch.setattr(executor, "run_docker_command", runner)
    monkeypatch.setattr(executor, "get_tool_workspace_root", lambda: str(tmp_path), raising=False)
    spec = _spec(
        id="t_docker_cache",
        name="docker_cache",
        sandbox=SandboxLevel.DOCKER,
        sandbox_command_builder=builder,
        idempotent=True,
    )

    first = await executor.execute(spec, {})
    second = await executor.execute(spec, {})
    assert first.ok is False
    assert second.ok is True
    assert calls["runner"] == 2
