"""Versioned, typed checkpoint value codec with safe legacy compatibility."""

from __future__ import annotations

import ast
import base64
import binascii
import json
import re
from typing import Any

from langchain_core.load import loads as lc_loads
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Interrupt

CODEC_FORMAT = "langgraph-typed-v1"
_MAX_LEGACY_REPR = 65_536
_MAX_LITERAL_DEPTH = 16
_MAX_LITERAL_NODES = 2_048
_INTERRUPT_MARKER = "__libao_interrupt__"


class CheckpointDecodeError(ValueError):
    """Raised when a checkpoint value is malformed or unsafe to decode."""


def _literal_limits(value: Any, depth: int = 0, count: list[int] | None = None) -> None:
    count = count or [0]
    count[0] += 1
    if count[0] > _MAX_LITERAL_NODES or depth > _MAX_LITERAL_DEPTH:
        raise CheckpointDecodeError("legacy checkpoint literal exceeds safety limits")
    if isinstance(value, dict):
        for key, item in value.items():
            _literal_limits(key, depth + 1, count)
            _literal_limits(item, depth + 1, count)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _literal_limits(item, depth + 1, count)


def _legacy_interrupts(raw: str) -> list[Interrupt] | None:
    try:
        encoded = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    items = encoded if isinstance(encoded, list) else [encoded]
    restored: list[Interrupt] = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "not_implemented":
            return None
        if item.get("id") != ["langgraph", "types", "Interrupt"]:
            raise CheckpointDecodeError("invalid legacy Interrupt class id")
        text = item.get("repr")
        if not isinstance(text, str) or len(text) > _MAX_LEGACY_REPR:
            raise CheckpointDecodeError("legacy Interrupt repr is invalid")
        match = re.fullmatch(r"Interrupt\(value=(.*), id=([\'\"].*)\)", text, flags=re.DOTALL)
        if match is None:
            raise CheckpointDecodeError("legacy Interrupt repr is invalid")
        try:
            value = ast.literal_eval(match.group(1))
            interrupt_id = ast.literal_eval(match.group(2))
        except (SyntaxError, ValueError, TypeError) as exc:
            raise CheckpointDecodeError("legacy Interrupt repr is invalid") from exc
        _literal_limits(value)
        if not isinstance(interrupt_id, str):
            raise CheckpointDecodeError("legacy Interrupt id is invalid")
        restored.append(Interrupt(value=value, id=interrupt_id))
    return restored


class JsonCheckpointCodec:
    """Serialize values using LangGraph's typed serializer in a JSON envelope."""

    def __init__(self, serde: Any | None = None) -> None:
        self.serde = serde or JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=None)

    def dumps(self, value: Any) -> dict[str, str]:
        type_name, payload = self.serde.dumps_typed(value)
        if type_name not in {"null", "bytes", "bytearray", "json", "msgpack"}:
            raise CheckpointDecodeError(f"unsupported checkpoint serialization type: {type_name}")
        if not isinstance(payload, (bytes, bytearray)):
            raise CheckpointDecodeError("serializer returned a non-byte payload")
        return {
            "format": CODEC_FORMAT,
            "type": type_name,
            "data": base64.b64encode(bytes(payload)).decode("ascii"),
        }

    def _loads_envelope(self, payload: dict[str, Any]) -> Any:
        if payload.get("format") != CODEC_FORMAT:
            raise CheckpointDecodeError("unknown checkpoint envelope format")
        type_name = payload.get("type")
        encoded = payload.get("data")
        if type_name not in {"null", "bytes", "bytearray", "json", "msgpack"} or not isinstance(encoded, str):
            raise CheckpointDecodeError("invalid checkpoint envelope")
        try:
            raw = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
            raise CheckpointDecodeError("invalid checkpoint envelope data") from exc
        try:
            return self.serde.loads_typed((type_name, raw))
        except Exception as exc:
            raise CheckpointDecodeError("checkpoint value cannot be decoded") from exc

    def loads(self, payload: str | dict[str, Any], *, channel: str | None = None) -> Any:
        if isinstance(payload, dict):
            return self._loads_envelope(payload)
        if not isinstance(payload, str):
            raise CheckpointDecodeError("checkpoint value must be a string or envelope")
        if channel == "__interrupt__":
            try:
                marker = json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                marker = None
            if isinstance(marker, dict) and isinstance(marker.get(_INTERRUPT_MARKER), list):
                restored: list[Interrupt] = []
                for item in marker[_INTERRUPT_MARKER]:
                    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                        raise CheckpointDecodeError("invalid Interrupt marker")
                    restored.append(Interrupt(value=item.get("value"), id=item["id"]))
                return restored
            legacy = _legacy_interrupts(payload)
            if legacy is not None:
                return legacy
        try:
            return lc_loads(payload)
        except NotImplementedError as exc:
            if channel == "__error__":
                try:
                    value = json.loads(payload)
                    error_id = value.get("id") or []
                except (json.JSONDecodeError, AttributeError, TypeError):
                    error_id = []
                return {"error_type": str(error_id[-1]) if error_id else "UnserializableError"}
            raise CheckpointDecodeError("legacy checkpoint value cannot be decoded") from exc
        except Exception as exc:
            raise CheckpointDecodeError("legacy checkpoint value cannot be decoded") from exc
