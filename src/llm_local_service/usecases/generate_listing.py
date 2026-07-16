import logging
import time
from typing import AsyncIterator
from uuid import uuid4

from ..models.generation import (
    DecisionPayload,
    DeltaPayload,
    Draft,
    ErrorPayload,
    GenerationResult,
    QueuedPayload,
)
from ..services.llm_client import LlmClient
from ..services.request_queue import RequestQueue

logger = logging.getLogger(__name__)

# Decisión fija de ejemplo. En la fase del modelo la producirá el motor de
# inferencia del grafo; el contrato del evento `decision` no cambia.
_EXAMPLE_DECISION = DecisionPayload(
    narrative="hogar familiar con vida al aire libre",
    tone="cálido",
    audience="familias",
    themes=["aire libre", "convivencia familiar", "tranquilidad"],
    highlight_amenities=["terraza", "jardín"],
)


class GenerateListingUseCase:
    """
    Orquesta la generación de título y descripción como un stream de eventos
    (nombre, payload): queued* → decision → delta* → done, o error ante fallo.
    """

    def __init__(self, client: LlmClient, queue: RequestQueue):
        self._client = client
        self._queue = queue

    async def stream(self, draft: Draft) -> AsyncIterator[tuple[str, dict]]:
        acquired = False
        try:
            async for position in self._queue.acquire():
                yield "queued", QueuedPayload(position=position).model_dump()
            acquired = True

            started = time.perf_counter()
            yield "decision", _EXAMPLE_DECISION.model_dump(by_alias=True)

            fragments: list[str] = []
            user_message = draft.model_dump_json(by_alias=True)
            async for fragment in self._client.stream_chat(user_message):
                fragments.append(fragment)
                yield "delta", DeltaPayload(text=fragment).model_dump()

            result = GenerationResult(
                generation_id=uuid4(),
                title=self._build_title(draft),
                description="".join(fragments).strip(),
                duration_s=round(time.perf_counter() - started, 3),
                warnings=[],
            )
            yield "done", result.model_dump(mode="json", by_alias=True)
        except Exception as exc:
            logger.error(
                "Fallo en la generación para draftId=%s: %s", draft.id, exc
            )
            yield "error", ErrorPayload(detail=str(exc)).model_dump()
        finally:
            if acquired:
                await self._queue.release()

    @staticmethod
    def _build_title(draft: Draft) -> str:
        # Título simulado con el formato definido para producción:
        # "<Tipo de propiedad> en <Colonia> para <renta|venta>".
        operation = "renta" if draft.available_to_rent else "venta"
        return (
            f"{draft.property_type.name} en "
            f"{draft.address.neighborhood_name} para {operation}"
        )
