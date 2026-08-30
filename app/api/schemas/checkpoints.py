from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

RollbackMode = Literal["code_only", "conversation_only", "both"]


def _coerce_request_id(value: object) -> str | None:
    return None if value is None else str(value)


ClientRequestId = Annotated[str, BeforeValidator(_coerce_request_id)]
OptionalClientRequestId = Annotated[str | None, BeforeValidator(_coerce_request_id)]


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
    CheckpointRestorePreviewRequest | OperationBeforeRestorePreviewRequest,
    Field(discriminator="target_type"),
]


class RestoreExecuteRequest(BaseModel):
    preview_id: uuid.UUID
    # ``None`` is accepted only for compatibility with the pre-v2 static
    # bundle; v2 clients send both values and are checked by the service.
    expected_mode: RollbackMode | None = None
    client_request_id: OptionalClientRequestId = Field(default=None, min_length=1, max_length=128)
    model_config = ConfigDict(extra="forbid")
