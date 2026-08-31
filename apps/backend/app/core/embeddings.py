"""Embedding 服务（《02》后端设计 §9.1 / 05 §1.2）。直接 httpx 调 OpenAI 兼容 /embeddings 端点。

选 httpx 而非 litellm：embedding 是批量离线路径（索引/检索），单端点自控重试/错误分类，
测试可用 MockTransport 干净注入。API key 走 Settings（~/.LiBao/settings.json），不入库。
维度 EMBED_DIM 与迁移 0004 的 vector(1024) 一致（见 models/kb.py）。
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import ERR_INTERNAL, AppError
from app.storage.models.kb import EMBED_DIM

_BACKOFF_BASE_MS = 500
_MAX_RETRIES = 3


class EmbeddingService:
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        s = get_settings()
        self.model = model or s.embedding_model
        self.base_url = (base_url or s.embedding_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else s.embedding_api_key
        self.batch_size = s.embedding_batch_size
        self.timeout_s = s.embedding_timeout_s
        self._transport = transport  # 测试注入点

    async def embed_query(self, text: str) -> list[float]:
        vecs = await self._call([text])
        return vecs[0]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            out.extend(await self._call(texts[i : i + self.batch_size]))
        return out

    async def _call(self, inputs: list[str]) -> list[list[float]]:
        """单次请求（≤ batch_size 条）→ 维度校验后的向量列表。429/5xx/网络错误重试，401 快败。"""
        if not self.api_key:
            raise AppError(ERR_INTERNAL, "embedding API key 未配置（EMBEDDING_API_KEY）")
        body = {"model": self.model, "input": inputs if len(inputs) > 1 else inputs[0]}
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                    transport=self._transport, timeout=self.timeout_s, base_url=self.base_url
                ) as client:
                    resp = await client.post(
                        "/embeddings",
                        headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                        content=json.dumps(body, ensure_ascii=False),
                    )
                if resp.status_code == 401:
                    raise AppError(ERR_INTERNAL, "embedding API key 配置错误（401）")
                if resp.status_code != 200:
                    last_exc = RuntimeError(f"embedding HTTP {resp.status_code}")
                    if (resp.status_code == 429 or resp.status_code >= 500) and attempt < _MAX_RETRIES:
                        await asyncio.sleep(self._backoff(attempt))
                        continue
                    break
                data = resp.json()
                items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
                vecs = [self._validate(it["embedding"]) for it in items]
                if len(vecs) != len(inputs):
                    raise AppError(ERR_INTERNAL, f"embedding 返回条数不符: 期望 {len(inputs)}, 实际 {len(vecs)}")
                return vecs
            except AppError:
                raise
            except Exception as exc:  # noqa: BLE001  网络错误 → 重试
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                break
        raise AppError(ERR_INTERNAL, f"embedding 调用失败: {last_exc}")

    @staticmethod
    def _backoff(attempt: int) -> float:
        return _BACKOFF_BASE_MS / 1000 * (2**attempt) + random.uniform(0, _BACKOFF_BASE_MS / 1000)

    @staticmethod
    def _validate(vec: Any) -> list[float]:
        if not isinstance(vec, list) or len(vec) != EMBED_DIM:
            got = len(vec) if isinstance(vec, list) else type(vec).__name__
            raise AppError(ERR_INTERNAL, f"embedding 维度不匹配: 期望 {EMBED_DIM}, 实际 {got}")
        return vec
