"""Orquestación de la inferencia real: grafo → resumen → LLM → SSE → persistencia.

Flujo de eventos:
  queued*  → mientras espera su turno en la RequestQueue
  title    → una sola vez, al completarse el valor de \"titulo\" en el stream
  delta*   → fragmentos del valor de \"descripcion\" conforme llegan
  done     → (generationId, title, description) al terminar
  error    → ante cualquier excepción; el turno siempre se libera (finally)
"""

from __future__ import annotations

import logging
import re
import time
from typing import AsyncIterator
from uuid import uuid4

import psutil

from ..models.generation import (
    ContentResult,
    ErrorPayload,
    GenerationRecord,
    QueuedPayload,
    TitlePayload,
)
from ..models.graph import Decision, Domain
from ..persistence.generation_repository import GenerationRepository
from ..services.graph_inference import GraphInferenceService
from ..services.listing_stream_parser import ListingStreamParser
from ..services.llm_client import LlmClient
from ..services.request_queue import RequestQueue
from ..services.summary_builder import (
    GRAPH_VERSION,
    PROMPT_VERSION,
    build_summary,
)

logger = logging.getLogger(__name__)

# Expresiones de advertencia validadas en notebooks/graph-ai/benchmark_prompt_v6.py
RE_PRECIO = re.compile(
    r"\$|\bprecio\b|\bmxn\b|\bpesos?\b|mensualidad|mill[oó]n|\bmonto\b", re.I
)
RE_CONTACTO = re.compile(
    r"cont[aá]ct|ll[aá]m[ae]|tel[eé]fono|whatsapp|escr[ií]b[ae]|agend[ae]|vis[ií]t[ae]|"
    r"aprovecha|no te lo pierdas|[uú]ltimos d[ií]as|cita|oportunidad [uú]nica",
    re.I,
)


def _build_warnings(title: str, description: str) -> list[str]:
    """Verifica que el texto no filtre precio ni llamadas a la acción."""
    full = f"{title} {description}"
    warnings: list[str] = []
    if RE_PRECIO.search(full):
        warnings.append("precio_mencionado")
    if RE_CONTACTO.search(full):
        warnings.append("cta_detectada")
    return warnings


def _decision_to_dict(decision: Decision) -> dict:
    """Serializa Decision a un dict JSON-able para la columna JSONB."""
    return {
        "draft_id": decision.draft_id,
        "activations": decision.activations,
        "unknown_amenities": decision.unknown_amenities,
        "scores": decision.scores,
        "blocked": {
            k: [{"origin": e.origin, "target": e.target, "weight": e.weight,
                 "relation": e.relation, "reason": e.reason} for e in edges]
            for k, edges in decision.blocked.items()
        },
        "themes": decision.themes,
        "audience": decision.audience,
        "main_amenities": decision.main_amenities,
        "secondary_amenities": decision.secondary_amenities,
        "facts": decision.facts,
        "trace": decision.trace,
    }


class GenerateContentUseCase:
    """
    Orquesta la generación real de título y descripción como un stream de eventos.

    A diferencia del GenerateListingUseCase (simulado), este use case:
    - Corre el pipeline del grafo ponderado (v4) para inferir la Decision editorial.
    - Construye el resumen prescriptivo (v6) como único mensaje de usuario al LLM.
    - Usa LlamaServerHttpClient para streaming real desde llama-server.
    - Persiste el registro completo en llm_generations (fallo de persistencia se
      loguea pero no aborta el stream — patrón de anomalías).
    """

    def __init__(
        self,
        domain: Domain,
        inference: GraphInferenceService,
        client: LlmClient,
        queue: RequestQueue,
        repository: GenerationRepository,
        model_file: str,
    ):
        self._domain = domain
        self._inference = inference
        self._client = client
        self._queue = queue
        self._repository = repository
        self._model_file = model_file

    async def stream(self, draft) -> AsyncIterator[tuple[str, dict]]:
        """
        Genera el par (nombre_evento, payload) para cada momento del pipeline.
        El caller serializa con json.dumps y emite el SSE.
        """
        acquired = False
        try:
            # 1. Cola de espera.
            async for position in self._queue.acquire():
                yield "queued", QueuedPayload(position=position).model_dump()
            acquired = True

            total_start = time.perf_counter()
            draft_dict = draft.model_dump(by_alias=True)

            # 2. Inferencia sobre el grafo.
            graph_start = time.perf_counter()
            decision: Decision = self._inference.infer(draft_dict)
            graph_ms = (time.perf_counter() - graph_start) * 1000

            user_message = build_summary(self._domain, draft_dict, decision)

            # 3. Streaming desde llama-server con parseo incremental.
            parser = ListingStreamParser()
            llm_start = time.perf_counter()

            async for fragment in self._client.stream_chat(user_message):
                for event_name, text in parser.feed(fragment):
                    if event_name == "title":
                        yield "title", TitlePayload(text=text).model_dump()
                    else:
                        yield "delta", {"text": text}

            llm_s = time.perf_counter() - llm_start
            duration_s = time.perf_counter() - total_start

            # 4. Resultado final.
            title, description = parser.result()
            generation_id = uuid4()
            warnings = _build_warnings(title, description)

            result = ContentResult(
                generation_id=generation_id,
                title=title,
                description=description,
            )

            # 5. Métricas y persistencia (fallo aborta el stream → evento error).
            usage = getattr(self._client, "last_usage", None) or {}
            prompt_tokens = usage.get("prompt_tokens")
            output_tokens = usage.get("completion_tokens")
            tokens_per_second = (
                output_tokens / llm_s if (output_tokens and llm_s > 0) else None
            )
            try:
                ram_mb = psutil.Process().memory_info().rss / (1024 * 1024)
            except Exception:
                ram_mb = None

            await self._repository.save(
                id=generation_id,
                draft_id=draft.id,
                title=title,
                description=description,
                decision=_decision_to_dict(decision),
                warnings=warnings,
                graph_ms=round(graph_ms, 3),
                llm_s=round(llm_s, 3),
                duration_s=round(duration_s, 3),
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                tokens_per_second=tokens_per_second,
                ram_mb=ram_mb,
                model_file=self._model_file,
                prompt_version=PROMPT_VERSION,
                graph_version=GRAPH_VERSION,
                source="http",
            )

            # 6. Evento done (mínimo para el móvil).
            yield "done", result.model_dump(mode="json", by_alias=True)

        except Exception as exc:
            logger.error(
                "Fallo en generate_content para draftId=%s: %s", draft.id, exc
            )
            yield "error", ErrorPayload(detail=str(exc)).model_dump()
        finally:
            if acquired:
                await self._queue.release()
