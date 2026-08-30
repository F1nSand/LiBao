from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

RollbackMode = Literal["code_only", "conversation_only", "both"]


class CheckpointRestorePreviewRequest(BaseModel):
    target_type: Literal["checkpoint"] = "checkpoint"
    target_checkpoint_id: uuid.UUID
    mode: RollbackMode = "both"
    client_request_id: uuid.UUID
    model_config = ConfigDict(extra="forbid")


class OperationBeforeRestorePreviewRequest(BaseModel):
    target_type: Literal["rollback_operation_before"]
    target_id: uuid.UUID
    client_request_id: uuid.UUID
    model_config = ConfigDict(extra="forbid")


RestorePreviewRequest = Annotated[
    CheckpointRestorePreviewRequest | OperationBeforeRestorePreviewRequest,
    Field(discriminator="target_type"),
]


class RestoreExecuteRequest(BaseModel):
    preview_id: uuid.UUID
    expected_mode: RollbackMode
    client_request_id: uuid.UUID
    model_config = ConfigDict(extra="forbid")
