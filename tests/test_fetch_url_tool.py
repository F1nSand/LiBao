"""A1 fetch_url 工具测试（纯单元，无 DB）：注册态 / 内容清洗 / 白名单 / 错误兜底 / executor 全路径。"""
from __future__ import annotations

import httpx
import pytest

from app.core.config import get_settings
from app.tools import executor
from app.tools.builtin import fetch_url, register_builtin_tools
from app.tools.registry import get, unregister


@pytest.fixture(autouse=True)
def _clean_fetch(monkeypatch):
    register_builtin_tools()
    s = get_settings()
    monkeypatch.setattr(s, "fetch_url_allowlist", ["allowed.com", "*.ok.com"])
    yield
    fetch_url._transport = None
    unregister("tl_fetch_url")


def _mock(handler):
    fetch_url._transport = httpx.MockTransport(handler)


def test_registered_default_off():
    spec = get("tl_fetch_url")
    assert spec is not None
    assert spec.enabled is False  # 默认关闭，管理员显式启用
    assert spec.builtin is True
    aci = spec.aci()
    assert aci["function"]["name"] == "fetch_url"
    assert "url" in aci["function"]["parameters"]["properties"]


def test_allowlist_blocks_outside(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "fetch_url_allowlist", ["allowed.com"])
    assert fetch_url._allowed("evil.com", s.fetch_url_allowlist) is False
    assert fetch_url._allowed("allowed.com", s.fetch_url_allowlist) is True
    assert fetch_url._allowed("sub.allowed.com", s.fetch_url_allowlist) is False  # 无通配，精确匹配
    assert fetch_url._allowed("a.ok.com", ["*.ok.com"]) is True  # *. 通配
    assert fetch_url._allowed("a.b.ok.com", ["*.ok.com"]) is True


async def test_fetch_cleans_html(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "fetch_url_allowlist", ["allowed.com"])
    html = (
        "<html><head><title>示例页</title></head><body>"
        "<script>var x=1</script><p>你好</p><style>a{color:red}</style><p>  世界  </p>"
        "</body></html>"
    )

    def handler(request):
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    _mock(handler)
    result = await fetch_url.handler("https://allowed.com/a", max_chars=200)
    assert result["url"] == "https://allowed.com/a"
    assert result["title"] == "示例页"
    assert "你好" in result["text"] and "世界" in result["text"]
    assert "var x=1" not in result["text"]  # script 剥掉
    assert "color:red" not in result["text"]  # style 剥掉
    assert result["truncated"] is False
    assert result["content_type"] == "text/html"


async def test_fetch_truncates():
    html = "<html><body>" + "x" * 1000 + "</body></html>"

    def handler(request):
        return httpx.Response(200, text=html)

    _mock(handler)
    result = await fetch_url.handler("https://allowed.com/long", max_chars=100)
    assert len(result["text"]) <= 100
    assert result["truncated"] is True


async def test_fetch_allowlist_blocks():
    result = await fetch_url.handler("http://evil.com/x")
    assert "error" in result
    assert "白名单" in result["error"]


async def test_fetch_invalid_url():
    assert "error" in await fetch_url.handler("ftp://x")
    assert "error" in await fetch_url.handler("not-a-url")


async def test_fetch_non_200():
    def handler(request):
        return httpx.Response(503, text="err")

    _mock(handler)
    result = await fetch_url.handler("https://allowed.com/x")
    assert "error" in result
    assert "503" in result["error"]


async def test_executor_full_path(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "fetch_url_allowlist", ["allowed.com"])

    def handler(request):
        return httpx.Response(200, text="<html><body><p>正文内容</p></body></html>")

    _mock(handler)
    spec = get("tl_fetch_url")
    result = await executor.execute(spec, {"url": "https://allowed.com/x"})
    assert result.ok is True
    assert result.output["text"] == "正文内容"
