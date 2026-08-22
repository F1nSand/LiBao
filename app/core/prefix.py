"""静态前缀哈希（docs 01 §4.1）。seed 与 context_builder 共用同一算法，字节稳定。

缓存键 = sha256({model, system_prompt, tools(sorted)})；任何静态前缀改动即产生新 hash。
"""

from __future__ import annotations

import hashlib
import json


def compute_prefix_hash(model: str, system_prompt: str, tool_ids: list[str]) -> str:
    canonical = json.dumps(
        {"model": model, "system_prompt": system_prompt, "tools": sorted(tool_ids)},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
