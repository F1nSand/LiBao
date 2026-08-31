"""Rerank 服务（《02》后端设计 §9.1 重排序）。httpx 调 SiliconFlow `/rerank`（Qwen3-Reranker，OpenAI 兼容）。

复用 embedding 的 base_url/api_key（同一家供应商）；Cross-Encoder 重排 RRF 粗排候选，
精排后取 top_k。选 httpx 而非 litellm：单端点自控重试/错误分类，测试可用 MockTransport 注入。
失败抛 AppError → 调用方（hybrid_search）静默降级 RRF 顺序，不击穿检索。
"""

from __future__ import annotations

import asyncio
import json
import random

import httpx

from app.core.config import get_settings
from app.core.errors import ERR_INTERNAL, AppError

_BACKOFF_BASE_MS = 500
_MAX_RETRIES = 3


class RerankService:
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        s = get_settings()
        self.model = model or s.rerank_model
        self.base_url = (base_url or s.embedding_base_url).rstrip("/")  # 复用 embedding 的 url
        self.api_key = api_key if api_key is not None else s.embedding_api_key  # 复用 embedding 的 key
        self.timeout_s = s.embedding_timeout_s
        self._transport = transport  # 测试注入点

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        """重排 documents → [(原 index, relevance_score)] 按 score 降序（长度 == top_n）。

        documents 数 ≤ top_n 时无需重排（调用方直接回退 RRF 顺序，不走到这里）。
        """
        if not documents:
            return []
        if not self.api_key:
            raise AppError(ERR_INTERNAL, "rerank API key 未配置（复用 EMBEDDING_API_KEY）")
        body = {"model": self.model, "query": query, "documents": documents, "top_n": top_n}
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                    transport=self._transport, timeout=self.timeout_s, base_url=self.base_url
                ) as client:
                    resp = await client.post(
                        "/rerank",
                        headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                        content=json.dumps(body, ensure_ascii=False),
                    )
                if resp.status_code == 401:
                    raise AppError(ERR_INTERNAL, "rerank API key 配置错误（401）")
                if resp.status_code != 200:
                    last_exc = RuntimeError(f"rerank HTTP {resp.status_code}")
                    if (resp.status_code == 429 or resp.status_code >= 500) and attempt < _MAX_RETRIES:
                        await asyncio.sleep(self._backoff(attempt))
                        continue
                    break
                return self._parse(resp.json(), top_n)
            except AppError:
                raise
            except Exception as exc:  # noqa: BLE001  网络错误 → 重试
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                break
        raise AppError(ERR_INTERNAL, f"rerank 调用失败: {last_exc}")

    @staticmethod
    def _parse(data: dict, top_n: int) -> list[tuple[int, float]]:
        """解析 results → [(index, relevance_score)] 按 score 降序，截断 top_n。

        兼容 relevance_score / score 字段（SiliconFlow 不同文档变体）。
        """
        results = data.get("results") or []
        scored: list[tuple[int, float]] = []
        for r in results:
            if not isinstance(r, dict):
                continue
            idx = r.get("index")
            score = r.get("relevance_score", r.get("score"))
            if idx is None or not isinstance(score, (int, float)):
                continue
            scored.append((int(idx), float(score)))
        scored.sort(key=lambda kv: -kv[1])
        return scored[:top_n]

    @staticmethod
    def _backoff(attempt: int) -> float:
        return _BACKOFF_BASE_MS / 1000 * (2**attempt) + random.uniform(0, _BACKOFF_BASE_MS / 1000)
