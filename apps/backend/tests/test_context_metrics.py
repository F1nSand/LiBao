from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.orchestration.context_metrics import measure_context


def test_measure_context_counts_text_blocks_and_tool_schema():
    metrics = measure_context(
        [
            SystemMessage(content="system"),
            HumanMessage(
                content=[
                    {"type": "text", "text": "你好 hello"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,secret"}},
                ]
            ),
        ],
        [{"function": {"name": "shell", "description": "run", "parameters": {"type": "object"}}}],
    )

    assert metrics["message_count"] == 2
    assert metrics["text_chars"] == len("system你好 hello")
    assert metrics["image_count"] == 1
    assert metrics["tool_schema_chars"] > 0
    assert metrics["estimated_prompt_tokens"] > 0
    assert metrics["estimated"] is True
    assert metrics["estimate_method"] == "unicode_heuristic_v1"


def test_measure_context_does_not_copy_image_or_document_payload():
    nonce = "document-secret-nonce"
    metrics = measure_context(
        [
            HumanMessage(
                content=[
                    {"type": "image", "data": "image-secret-nonce"},
                    {"type": "document_ref", "text": nonce, "payload": "full-document-secret"},
                ]
            )
        ],
        [],
    )

    serialized = json.dumps(metrics, ensure_ascii=False)
    assert "image-secret-nonce" not in serialized
    assert "full-document-secret" not in serialized
    assert metrics["image_count"] == 1
    assert metrics["document_chars"] == len(nonce)
