"""内置工具 tl_fetch_url：只读抓取网页（docs 07 RM-8 / docs 04 F4）。

出站白名单 fail-closed（Settings.fetch_url_allowlist）；内容清洗（D3：剥 script/style + 折叠空白）；
默认不启用（管理员显式开启）。异常兜底 error（不抛，executor 正常打包）。
"""
from __future__ import annotations

import html.parser
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings

_MAX_FETCH_CHARS = 20000  # 抓取内容硬上限（防超大页）
_FETCH_TIMEOUT_S = 10

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


def _allowed(host: str, allowlist: list[str]) -> bool:
    """白名单匹配：精确域名或 *.example.com 通配。空白名单 = fail-closed 全拒。"""
    if not allowlist:
        return False
    host = host.lower()
    return any(h == host or (h.startswith("*.") and host.endswith(h[1:])) for h in allowlist)


async def handler(url: str, max_chars: int = 8000) -> dict[str, Any]:
    """只读抓取：白名单校验 → GET → 清洗。异常兜底 error。"""
    settings = get_settings()
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return {"error": "仅支持 http/https URL"}
        if not _allowed(parsed.hostname, settings.fetch_url_allowlist):
            return {"error": f"域名 {parsed.hostname} 不在出站白名单内"}
        limit = min(max_chars, _MAX_FETCH_CHARS)
        async with httpx.AsyncClient(
            transport=_transport, timeout=_FETCH_TIMEOUT_S, follow_redirects=True
        ) as client:
            resp = await client.get(url, headers={"User-Agent": "agent-backend/0.1"})
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}"}
        return {
            "url": url,
            "title": _extract_title(resp.text),
            "text": _clean_html(resp.text, limit),
            "truncated": len(resp.text) > limit,
            "content_type": resp.headers.get("content-type", ""),
        }
    except Exception as exc:  # noqa: BLE001  抓取故障不击穿工具
        return {"error": f"抓取失败: {str(exc)[:300]}"}
