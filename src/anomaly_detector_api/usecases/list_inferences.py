import logging
import uuid
from typing import Optional

from ..models.property import InferenceListResponse, InferenceRecord
from ..persistence.inference_repository import InferenceRepository

logger = logging.getLogger(__name__)


class ListInferencesUseCase:
    """Lógica de lectura de inferencias persistidas."""

    def __init__(self, repository: InferenceRepository):
        self._repository = repository

    async def list(
        self,
        *,
        draft_id: Optional[str] = None,
        is_anomaly: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> InferenceListResponse:
        items, total = await self._repository.list(
            draft_id=draft_id, is_anomaly=is_anomaly, limit=limit, offset=offset
        )
        return InferenceListResponse(
            total=total,
            limit=limit,
            offset=offset,
            items=[InferenceRecord.model_validate(item) for item in items],
        )

    async def get(self, inference_id: uuid.UUID) -> Optional[InferenceRecord]:
        record = await self._repository.get(inference_id)
        return InferenceRecord.model_validate(record) if record else None
