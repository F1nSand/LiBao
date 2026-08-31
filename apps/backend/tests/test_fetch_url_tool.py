"""A1 fetch_url 工具测试（纯单元，无 DB）：注册态 / 内容清洗 / 出站黑名单（默认全放行）/ 错误兜底 / executor 全路径。"""
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
    monkeypatch.setattr(s, "fetch_url_denylist", [])  # 默认空 = 全放行
    monkeypatch.setattr(fetch_url, "_resolve_host", lambda host: ["93.184.216.34"])
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


def test_denylist_semantics(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "fetch_url_denylist", [])
    assert fetch_url._denied("evil.com", s.fetch_url_denylist) is False  # 空黑名单 = 默认全放行
    monkeypatch.setattr(s, "fetch_url_denylist", ["evil.com"])
    assert fetch_url._denied("evil.com", s.fetch_url_denylist) is True
    assert fetch_url._denied("sub.evil.com", s.fetch_url_denylist) is False  # 无通配，精确匹配
    assert fetch_url._denied("a.bad.com", ["*.bad.com"]) is True  # *. 通配
    assert fetch_url._denied("evil.com", ["EVIL.COM"]) is True  # 配置大小写不应改变语义
    assert fetch_url._denied("evil.com", ["evil.com."]) is True  # DNS 完全限定名尾点


async def test_fetch_cleans_html():
    html = (
        "<html><head><title>示例页</title></head><body>"
        "<script>var x=1</script><p>你好</p><style>a{color:red}</style><p>  世界  </p>"
        "</body></html>"
    )

    def handler(request):
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    _mock(handler)
    result = await fetch_url.handler("https://example.com/a", max_chars=200)
    assert result["url"] == "https://example.com/a"
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
    result = await fetch_url.handler("https://example.com/long", max_chars=100)
    assert len(result["text"]) <= 100
    assert result["truncated"] is True


async def test_fetch_denylist_blocks(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "fetch_url_denylist", ["evil.com"])
    result = await fetch_url.handler("http://evil.com/x")
    assert "error" in result
    assert "黑名单" in result["error"]


async def test_fetch_invalid_url():
    assert "error" in await fetch_url.handler("ftp://x")
    assert "error" in await fetch_url.handler("not-a-url")


async def test_fetch_rejects_loopback_and_private_targets():
    for url in (
        "http://127.0.0.1/internal",
        "http://10.0.0.8/internal",
        "http://[::1]/internal",
        "http://localhost/internal",
    ):
        result = await fetch_url.handler(url)
        assert "error" in result
        assert "本地或私有网络" in result["error"]


async def test_fetch_rejects_private_dns_resolution(monkeypatch):
    monkeypatch.setattr(fetch_url, "_resolve_host", lambda host: ["93.184.216.34", "192.168.1.10"])
    result = await fetch_url.handler("https://example.com/internal")
    assert "error" in result
    assert "本地或私有网络" in result["error"]


async def test_fetch_caps_response_body():
    def handler(request):
        return httpx.Response(200, text="x" * 100_000)

    _mock(handler)
    result = await fetch_url.handler("https://example.com/large", max_chars=100)
    assert len(result["text"]) <= 100
    assert result["truncated"] is True


async def test_fetch_validates_each_redirect_before_following():
    requests = []

    def handler(request):
        requests.append(request.url)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    _mock(handler)
    result = await fetch_url.handler("https://example.com/redirect")
    assert "error" in result
    assert "本地或私有网络" in result["error"]
    assert len(requests) == 1


async def test_fetch_non_200():
    def handler(request):
        return httpx.Response(503, text="err")

    _mock(handler)
    result = await fetch_url.handler("https://example.com/x")
    assert "error" in result
    assert "503" in result["error"]


async def test_executor_full_path():
    def handler(request):
        return httpx.Response(200, text="<html><body><p>正文内容</p></body></html>")

    _mock(handler)
    spec = get("tl_fetch_url")
    result = await executor.execute(spec, {"url": "https://example.com/x"})
    assert result.ok is True
    assert result.output["text"] == "正文内容"
