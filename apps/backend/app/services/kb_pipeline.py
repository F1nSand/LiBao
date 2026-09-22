"""Compatibility adapter for background KB document indexing."""

from __future__ import annotations

import logging
import uuid

from app.core.embeddings import EmbeddingService
from app.services.kb_generation import GenerationBuildError, KbGenerationService
from app.storage.repositories.kb import KbRepository

logger = logging.getLogger(__name__)


async def process_document(document_id: uuid.UUID, embedder: EmbeddingService | None = None) -> None:
    """Delegate document builds; generation service persists all handled failure states."""
    repo = KbRepository()
    document = await repo.get_document(uuid.UUID(int=0), document_id)
    if document is None or document.status != "uploaded":
        return
    try:
        await KbGenerationService(repo=repo).build(document_id, embedder=embedder)
    except GenerationBuildError as exc:
        logger.warning("KB indexing failed document_id=%s error=%s", document_id, exc)
