import logging
import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from .models_db import LlmGeneration

logger = logging.getLogger(__name__)


class GenerationRepository:
    """
    Acceso a la persistencia de generaciones del LLM.

    Espeja el patrón Repository del servicio de anomalías para aislar la lógica
    de negocio del detalle de SQLAlchemy. Cada método abre su propia sesión.
    """

    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    async def save(
        self,
        *,
        id: uuid.UUID,
        draft_id: str,
        title: str,
        description: str,
        decision: dict,
        warnings: list,
        graph_ms: float,
        llm_s: float,
        duration_s: float,
        prompt_tokens: Optional[int],
        output_tokens: Optional[int],
        tokens_per_second: Optional[float],
        ram_mb: Optional[float],
        model_file: str,
        prompt_version: str,
        graph_version: str,
        source: str = "http",
    ) -> LlmGeneration:
        """Inserta una generación y devuelve el registro persistido."""
        record = LlmGeneration(
            id=id,
            draft_id=draft_id,
            title=title,
            description=description,
            decision=decision,
            warnings=warnings,
            graph_ms=graph_ms,
            llm_s=llm_s,
            duration_s=duration_s,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            tokens_per_second=tokens_per_second,
            ram_mb=ram_mb,
            model_file=model_file,
            prompt_version=prompt_version,
            graph_version=graph_version,
            source=source,
        )
        async with self._session_factory() as session:
            async with session.begin():
                session.add(record)
            await session.refresh(record)
        logger.info("Generación persistida id=%s draftId=%s", record.id, draft_id)
        return record

    async def list(
        self,
        *,
        draft_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[LlmGeneration], int]:
        """Lista generaciones con filtros opcionales. Devuelve (items, total)."""
        filters = []
        if draft_id is not None:
            filters.append(LlmGeneration.draft_id == draft_id)

        async with self._session_factory() as session:
            total = await session.scalar(
                select(func.count()).select_from(LlmGeneration).where(*filters)
            )
            result = await session.scalars(
                select(LlmGeneration)
                .where(*filters)
                .order_by(LlmGeneration.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(result.all()), int(total or 0)

    async def get(self, generation_id: uuid.UUID) -> Optional[LlmGeneration]:
        """Devuelve una generación por id, o None si no existe."""
        async with self._session_factory() as session:
            return await session.get(LlmGeneration, generation_id)
