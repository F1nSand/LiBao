"""内置工具 tl_fetch_url：只读抓取网页（《04》路线图 RM-8 / 《02》数据模型 F4）。

出站黑名单（Settings.fetch_url_denylist，默认空 = 全放行；精确域名或 *.example.com 通配）；
内容清洗（D3：剥 script/style + 折叠空白）；默认不启用（管理员显式开启）。异常兜底 error。
"""

from __future__ import annotations

import asyncio
import html.parser
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpcore
import httpx

from app.core.config import get_settings

_MAX_FETCH_CHARS = 20000  # 抓取内容硬上限（防超大页）
_MAX_RESPONSE_BYTES = _MAX_FETCH_CHARS * 4  # UTF-8 最坏情况下覆盖 max_chars
_FETCH_TIMEOUT_S = 10
_MAX_REDIRECTS = 5
_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
}

_transport: httpx.AsyncBaseTransport | None = None  # 测试注入点（镜像 embeddings.py）


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """让 httpcore 连接到已校验的 IP，同时保留原始 Host/SNI。"""

    def __init__(self, addresses: list[str]) -> None:
        self._addresses = tuple(addresses)

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        last_error: Exception | None = None
        for address in self._addresses:
            try:
                return await httpcore.AnyIOBackend().connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise httpcore.ConnectError("没有可用的已校验目标地址")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        return await httpcore.AnyIOBackend().connect_unix_socket(
            path, timeout=timeout, socket_options=socket_options
        )

    async def sleep(self, seconds: float) -> None:
        await httpcore.AnyIOBackend().sleep(seconds)


class _PinnedHTTPTransport(httpx.AsyncHTTPTransport):
    """基于解析结果建连接，避免校验后再次解析原始域名。"""

    def __init__(self, addresses: list[str]) -> None:
        super().__init__(trust_env=False)
        self._pool._network_backend = _PinnedNetworkBackend(addresses)  # type: ignore[attr-defined]


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
    normalized_host = host.strip().rstrip(".").lower()
    for raw in denylist:
        entry = raw.strip().lower()
        wildcard = entry.startswith("*.")
        suffix = entry[2:] if wildcard else entry
        suffix = suffix.rstrip(".")
        if not suffix:
            continue
        if (not wildcard and suffix == normalized_host) or (
            wildcard and normalized_host.endswith(f".{suffix}")
        ):
            return True
    return False


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


async def _validate_target(url: str, denylist: list[str]) -> tuple[str | None, list[str]]:
    """Validate a URL and return the exact public IPs used for the next connection."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except ValueError:
        return "仅支持 http/https URL", []

    if parsed.scheme not in {"http", "https"} or not host:
        return "仅支持 http/https URL", []

    normalized_host = host.rstrip(".").lower()
    if _denied(normalized_host, denylist):
        return f"域名 {host} 在出站黑名单内", []
    if normalized_host in _BLOCKED_HOSTNAMES:
        return "目标地址属于本地或私有网络", []

    try:
        literal = ipaddress.ip_address(normalized_host)
        addresses = [str(literal)]
    except ValueError:
        try:
            addresses = await asyncio.to_thread(_resolve_host, normalized_host)
        except ValueError as exc:
            return str(exc), []

    if not addresses or any(not _is_public_address(address) for address in addresses):
        return "目标地址属于本地或私有网络", []
    return None, addresses


async def _read_response(response: httpx.Response, max_bytes: int) -> tuple[str, bool]:
    """Read at most max_bytes and return decoded text plus a hard-cap marker."""
    body = bytearray()
    truncated = False
    async for chunk in response.aiter_bytes():
        remaining = max_bytes - len(body)
        if remaining <= 0:
            truncated = True
            break
        if len(chunk) > remaining:
            body.extend(chunk[:remaining])
            truncated = True
            break
        body.extend(chunk)
    encoding = response.encoding or "utf-8"
    return bytes(body).decode(encoding, errors="replace"), truncated


async def handler(url: str, max_chars: int = 8000) -> dict[str, Any]:
    """只读抓取：逐请求 SSRF 校验 → GET → 清洗。异常兜底 error。"""
    settings = get_settings()
    try:
        limit = min(max_chars, _MAX_FETCH_CHARS)
        max_bytes = max(4096, limit * 4)
        current_url = url
        for _ in range(_MAX_REDIRECTS + 1):
            validation_error, addresses = await _validate_target(
                current_url, settings.fetch_url_denylist
            )
            if validation_error:
                return {"error": validation_error}

            transport = _transport or _PinnedHTTPTransport(addresses)
            async with httpx.AsyncClient(
                transport=transport,
                timeout=_FETCH_TIMEOUT_S,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "GET", current_url, headers={"User-Agent": "agent-backend/0.1"}
                ) as resp:
                    if resp.status_code in {301, 302, 303, 307, 308}:
                        location = resp.headers.get("location")
                        if not location:
                            return {"error": "重定向响应缺少 Location"}
                        current_url = urljoin(current_url, location)
                        continue
                    if resp.status_code != 200:
                        return {"error": f"HTTP {resp.status_code}"}
                    raw_text, response_truncated = await _read_response(resp, max_bytes)
                    return {
                        "url": current_url,
                        "title": _extract_title(raw_text),
                        "text": _clean_html(raw_text, limit),
                        "truncated": response_truncated or len(raw_text) > limit,
                        "content_type": resp.headers.get("content-type", ""),
                    }
        return {"error": "重定向次数超过限制"}
    except Exception as exc:  # noqa: BLE001  抓取故障不击穿工具
        return {"error": f"抓取失败: {str(exc)[:300]}"}
