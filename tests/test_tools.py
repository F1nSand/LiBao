"""工具层冒烟测试（T8 判据）：registry / aci / executor 校验·执行·超时。"""
from __future__ import annotations

import time

import pytest

from app.tools import executor
from app.tools.builtin import register_builtin_tools
from app.tools.registry import ToolSpec, acis, all_tools, get, unregister


@pytest.fixture(autouse=True)
def _register():
    register_builtin_tools()
    # 幂等清理历史 MCP spec（其他测试进程内残留，acis 前缀排序断言依赖纯净 registry）
    for spec in [s for s in all_tools() if s.id.startswith("mc_")]:
        unregister(spec.id)


def test_registry_get_returns_spec():
    spec = get("tl_time_now")
    assert spec is not None
    assert spec.id == "tl_time_now"
    assert spec.name == "time_now"
    assert spec.enabled is True
    assert spec.idempotent is False  # 时间查询不可去重（F2：缓存会返回陈旧时间）


def test_aci_shape_and_sorted():
    aci = get("tl_time_now").aci()
    assert aci == {
        "type": "function",
        "function": {
            "name": "time_now",
            "description": get("tl_time_now").description,
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
    # 前缀稳定：acis() 按 id 排序
    assert [a["function"]["name"] for a in acis()] == sorted(a["function"]["name"] for a in acis())


async def test_execute_success_time_now():
    result = await executor.execute(get("tl_time_now"), {})
    assert result.ok is True
    assert result.output["tz"] == "Asia/Shanghai"
    assert "iso" in result.output
    assert result.summary


async def test_execute_validation_failure():
    spec = ToolSpec(
        id="t_bad",
        name="bad",
        description="d",
        params_schema={
            "type": "object",
            "properties": {"x": {"type": "integer"}},
            "required": ["x"],
        },
        handler=lambda x: x,
    )
    result = await executor.execute(spec, {})
    assert result.ok is False
    assert "参数校验失败" in result.error


async def test_execute_timeout():
    spec = ToolSpec(id="t_slow", name="slow", description="d", timeout_ms=50, handler=lambda: time.sleep(1))
    result = await executor.execute(spec, {})
    assert result.ok is False
    assert "超时" in result.error


async def test_execute_missing_handler():
    spec = ToolSpec(
        id="t_nohandler",
        name="nohandler",
        description="d",
        params_schema={"type": "object", "properties": {}, "required": []},
    )
    result = await executor.execute(spec, {})
    assert result.ok is False
    assert "未注册 handler" in result.error
