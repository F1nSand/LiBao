"""内置工具 tl_fetch_url：只读抓取网页（《04》路线图 RM-8 / 《02》数据模型 F4）。

出站黑名单（Settings.fetch_url_denylist，默认空 = 全放行；精确域名或 *.example.com 通配）；
内容清洗（D3：剥 script/style + 折叠空白）；默认不启用（管理员显式开启）。异常兜底 error。
"""

from __future__ import annotations

import html.parser
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import get_settings

_MAX_FETCH_CHARS = 20000  # 抓取内容硬上限（防超大页）
_FETCH_TIMEOUT_S = 10
_MAX_REDIRECTS = 5
_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
}

_transport: httpx.AsyncBaseTransport | None = None  # 测试注入点（镜像 embeddings.py）


class _TextExtractor(html.parser.HTMLParser):
    """剥 script/style/noscript 块并收集文本（D3 内容清洗最小实现）。"""

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            self.parts.append(data)


def _clean_html(raw: str, max_chars: int) -> str:
    parser = _TextExtractor()
    parser.feed(raw)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return text[:max_chars]


def _extract_title(raw: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    return m.group(1).strip()[:200] if m else None


def _denied(host: str, denylist: list[str]) -> bool:
    """黑名单匹配：精确域名或 *.example.com 通配。空黑名单 = 默认全放行。"""
    if not denylist:
        return False
    host = host.lower()
    return any(h == host or (h.startswith("*.") and host.endswith(h[1:])) for h in denylist)


def _resolve_host(host: str) -> list[str]:
    """Resolve a host so every resulting address can be checked before connecting."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("目标域名无法解析") from exc

    addresses = {info[4][0] for info in infos if info[4]}
    return sorted(addresses)


def _is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_global


def _validate_target(url: str, denylist: list[str]) -> str | None:
    """Validate a URL before every request, including each redirect target."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except ValueError:
        return "仅支持 http/https URL"

    if parsed.scheme not in {"http", "https"} or not host:
        return "仅支持 http/https URL"

    normalized_host = host.rstrip(".").lower()
    if _denied(normalized_host, denylist):
        return f"域名 {host} 在出站黑名单内"
    if normalized_host in _BLOCKED_HOSTNAMES:
        return "目标地址属于本地或私有网络"

    try:
        literal = ipaddress.ip_address(normalized_host)
        addresses = [str(literal)]
    except ValueError:
        try:
            addresses = _resolve_host(normalized_host)
        except ValueError as exc:
            return str(exc)

    if not addresses or any(not _is_public_address(address) for address in addresses):
        return "目标地址属于本地或私有网络"
    return None


async def handler(url: str, max_chars: int = 8000) -> dict[str, Any]:
    """只读抓取：逐请求 SSRF 校验 → GET → 清洗。异常兜底 error。"""
    settings = get_settings()
    try:
        validation_error = _validate_target(url, settings.fetch_url_denylist)
        if validation_error:
            return {"error": validation_error}

        limit = min(max_chars, _MAX_FETCH_CHARS)
        async with httpx.AsyncClient(
            transport=_transport, timeout=_FETCH_TIMEOUT_S, follow_redirects=False
        ) as client:
            current_url = url
            for _ in range(_MAX_REDIRECTS + 1):
                resp = await client.get(
                    current_url, headers={"User-Agent": "agent-backend/0.1"}
                )
                if resp.status_code not in {301, 302, 303, 307, 308}:
                    break
                location = resp.headers.get("location")
                if not location:
                    return {"error": "重定向响应缺少 Location"}
                current_url = urljoin(current_url, location)
                validation_error = _validate_target(
                    current_url, settings.fetch_url_denylist
                )
                if validation_error:
                    return {"error": validation_error}
            else:
                return {"error": "重定向次数超过限制"}

        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}"}
        return {
            "url": current_url,
            "title": _extract_title(resp.text),
            "text": _clean_html(resp.text, limit),
            "truncated": len(resp.text) > limit,
            "content_type": resp.headers.get("content-type", ""),
        }
    except Exception as exc:  # noqa: BLE001  抓取故障不击穿工具
        return {"error": f"抓取失败: {str(exc)[:300]}"}
