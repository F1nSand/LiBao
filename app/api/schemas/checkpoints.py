from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Discriminator, Field, Tag

RollbackMode = Literal["code_only", "conversation_only", "both"]


def _coerce_request_id(value: object) -> str | None:
    return None if value is None else str(value)


ClientRequestId = Annotated[str, BeforeValidator(_coerce_request_id)]
OptionalClientRequestId = Annotated[str | None, BeforeValidator(_coerce_request_id)]


def _get_restore_preview_target_type(value: object) -> str | None:
    """Resolve the preview branch, including the pre-v2 payload shape.

    The first static bundle shipped this endpoint with only
    ``target_checkpoint_id`` and ``mode``.  That payload is unambiguous, so
    select the checkpoint branch while leaving all malformed/unknown payloads
    to strict discriminated-union validation below.
    """
    if isinstance(value, dict):
        target_type = value.get("target_type")
        if target_type is not None:
            return str(target_type)
        if "target_checkpoint_id" in value:
            return "checkpoint"
    return None


class CheckpointRestorePreviewRequest(BaseModel):
    target_type: Literal["checkpoint"] = "checkpoint"
    target_checkpoint_id: uuid.UUID
    mode: RollbackMode = "both"
    # Frontend request IDs are opaque correlation tokens (the current UI uses
    # ``restore_request_<timestamp>_<counter>``); UUIDs remain valid strings.
    # A default keeps already-shipped bundles, which predate v2, callable.
    client_request_id: ClientRequestId = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    model_config = ConfigDict(extra="forbid")


class OperationBeforeRestorePreviewRequest(BaseModel):
    target_type: Literal["rollback_operation_before"]
    target_id: uuid.UUID
    client_request_id: ClientRequestId = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    model_config = ConfigDict(extra="forbid")


RestorePreviewRequest = Annotated[
    Annotated[CheckpointRestorePreviewRequest, Tag("checkpoint")]
    | Annotated[OperationBeforeRestorePreviewRequest, Tag("rollback_operation_before")],
    Discriminator(_get_restore_preview_target_type),
]


class RestoreExecuteRequest(BaseModel):
    preview_id: uuid.UUID
    # ``None`` is accepted only for compatibility with the pre-v2 static
    # bundle; v2 clients send both values and are checked by the service.
    expected_mode: RollbackMode | None = None
    client_request_id: OptionalClientRequestId = Field(default=None, min_length=1, max_length=128)
    model_config = ConfigDict(extra="forbid")
