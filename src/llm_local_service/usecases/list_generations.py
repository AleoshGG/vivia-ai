"""Lógica de lectura del historial de generaciones persistidas.

Espeja el patrón de `list_inferences.py` del servicio de anomalías.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from ..models.generation import GenerationListResponse, GenerationRecord
from ..persistence.generation_repository import GenerationRepository

logger = logging.getLogger(__name__)


class ListGenerationsUseCase:
    """Lógica de consulta del historial de generaciones persistidas."""

    def __init__(self, repository: GenerationRepository):
        self._repository = repository

    async def list(
        self,
        *,
        draft_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> GenerationListResponse:
        items, total = await self._repository.list(
            draft_id=draft_id, limit=limit, offset=offset
        )
        return GenerationListResponse(
            total=total,
            limit=limit,
            offset=offset,
            items=[GenerationRecord.model_validate(item) for item in items],
        )

    async def get(self, generation_id: uuid.UUID) -> Optional[GenerationRecord]:
        record = await self._repository.get(generation_id)
        return GenerationRecord.model_validate(record) if record else None
