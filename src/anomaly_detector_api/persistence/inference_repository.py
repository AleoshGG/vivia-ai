import logging
import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from .models_db import AnomalyInference

logger = logging.getLogger(__name__)


class InferenceRepository:
    """
    Acceso a la persistencia de inferencias de anomalías.

    Espeja el patrón Repository usado en `data_lake/` para aislar la lógica de
    negocio del detalle de SQLAlchemy. Cada método abre su propia sesión.
    """

    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    async def save(
        self,
        *,
        draft_id: str,
        is_anomaly: bool,
        approved: bool,
        reason: str,
        model_version: str,
        source: str,
        score: Optional[float] = None,
        features: Optional[dict] = None,
        text_is_fraud: bool = False,
        text_reasons: Optional[list] = None,
        anomaly_source: Optional[str] = None,
    ) -> AnomalyInference:
        """Inserta una inferencia y devuelve el registro persistido.

        `score`/`features` quedan en None cuando el texto rechaza y el Isolation
        Forest no llega a ejecutarse (cortocircuito).
        """
        record = AnomalyInference(
            id=uuid.uuid4(),
            draft_id=draft_id,
            is_anomaly=is_anomaly,
            score=score,
            approved=approved,
            reason=reason,
            model_version=model_version,
            source=source,
            features=features,
            text_is_fraud=text_is_fraud,
            text_reasons=text_reasons,
            anomaly_source=anomaly_source,
        )
        async with self._session_factory() as session:
            async with session.begin():
                session.add(record)
            await session.refresh(record)
        logger.info("Inferencia persistida id=%s draftId=%s", record.id, draft_id)
        return record

    async def list(
        self,
        *,
        draft_id: Optional[str] = None,
        is_anomaly: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AnomalyInference], int]:
        """Lista inferencias con filtros opcionales. Devuelve (items, total)."""
        filters = []
        if draft_id is not None:
            filters.append(AnomalyInference.draft_id == draft_id)
        if is_anomaly is not None:
            filters.append(AnomalyInference.is_anomaly == is_anomaly)

        async with self._session_factory() as session:
            total = await session.scalar(
                select(func.count()).select_from(AnomalyInference).where(*filters)
            )
            result = await session.scalars(
                select(AnomalyInference)
                .where(*filters)
                .order_by(AnomalyInference.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(result.all()), int(total or 0)

    async def get(self, inference_id: uuid.UUID) -> Optional[AnomalyInference]:
        """Devuelve una inferencia por id, o None si no existe."""
        async with self._session_factory() as session:
            return await session.get(AnomalyInference, inference_id)
