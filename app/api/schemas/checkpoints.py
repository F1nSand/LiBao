from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict


class RestorePreviewRequest(BaseModel):
    target_checkpoint_id: uuid.UUID | None = None
    target_type: Literal["checkpoint", "rollback_operation_before"] = "checkpoint"
    target_id: uuid.UUID | None = None
    mode: Literal["code_only", "conversation_only", "both"] = "both"
    model_config = ConfigDict(extra="forbid")


class RestoreExecuteRequest(BaseModel):
    preview_id: uuid.UUID
    model_config = ConfigDict(extra="forbid")
