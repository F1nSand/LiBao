"""内置工具 tl_web_search：联网搜索（Bing HTML，免 key；DuckDuckGo/Brave 在本网络不可达已弃）。

出站黑名单（Settings.fetch_url_denylist，默认空 = 全放行）；transport 注入点供测试 mock；
解析容错（HTML 结构变动时降级空结果）。异常兜底 error。默认不启用（管理员显式开启）。
"""

from __future__ import annotations

import html as _html
import re
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings

_SEARCH_HOST = "www.bing.com"
_TIMEOUT_S = 15
_MAX_RESULTS = 10

_transport: httpx.AsyncBaseTransport | None = None  # 测试注入点（镜像 fetch_url）

_ALGO_START_RE = re.compile(r'<li[^>]*class="b_algo"')
_TITLE_RE = re.compile(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_SNIPPET_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.S)


def _strip_tags(text: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def parse_results(raw: str, max_results: int) -> list[dict[str, str]]:
    """解析 Bing HTML 结果（b_algo 块：h2>a 标题/链接 + p 摘要）；容错降级空结果。"""
    results: list[dict[str, str]] = []
    starts = [m.start() for m in _ALGO_START_RE.finditer(raw)]
    for i, pos in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(raw)
        block = raw[pos:end]
        m = _TITLE_RE.search(block)
        if not m:
            continue
        url, title = m.group(1), _strip_tags(m.group(2))
        pm = _SNIPPET_RE.search(block)
        snippet = _strip_tags(pm.group(1)) if pm else ""
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


async def web_search_handler(query: str, max_results: int = 5) -> dict[str, Any]:
    """联网搜索：query → 结果列表（title/url/snippet）。默认全放行（除非黑名单拦截）。"""
    settings = get_settings()
    if _SEARCH_HOST in settings.fetch_url_denylist:
        return {"error": f"搜索服务被出站黑名单拦截（{_SEARCH_HOST}）"}
    limit = max(1, min(max_results, _MAX_RESULTS))
    try:
        url = f"https://{_SEARCH_HOST}/search?{urlencode({'q': query})}"
        async with httpx.AsyncClient(
            transport=_transport, timeout=_TIMEOUT_S, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; agent-backend/0.1)"},
        ) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return {"error": f"搜索服务 HTTP {resp.status_code}"}
        results = parse_results(resp.text, limit)
        return {"query": query, "results": results, "count": len(results)}
    except Exception as exc:  # noqa: BLE001  搜索故障不击穿工具
        return {"error": f"搜索失败: {str(exc)[:300]}"}
