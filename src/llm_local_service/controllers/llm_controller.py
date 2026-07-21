import json
import uuid as _uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..auth.jwt_auth import verify_jwt
from ..auth.premium_gate import require_premium
from ..models.generation import GenerationListResponse, GenerationRecord, GenerationRequest
from ..services.request_queue import RequestQueue
from ..usecases.generate_content import GenerateContentUseCase
from ..usecases.generate_listing import GenerateListingUseCase
from ..usecases.list_generations import ListGenerationsUseCase

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de dependencias
# ─────────────────────────────────────────────────────────────────────────────

def _queue(request: Request) -> RequestQueue:
    return request.app.state.request_queue


def _use_case(request: Request) -> GenerateListingUseCase:
    return GenerateListingUseCase(
        client=request.app.state.llm_client,
        queue=request.app.state.request_queue,
    )


def _content_use_case(request: Request) -> GenerateContentUseCase:
    return GenerateContentUseCase(
        domain=request.app.state.graph_domain,
        inference=request.app.state.graph_inference,
        client=request.app.state.llama_client,
        queue=request.app.state.request_queue,
        repository=request.app.state.generation_repository,
        model_file=request.app.state.llm_model_file,
    )


def _list_use_case(request: Request) -> ListGenerationsUseCase:
    return ListGenerationsUseCase(repository=request.app.state.generation_repository)


# ─────────────────────────────────────────────────────────────────────────────
# Ruta simulada (fase 1-2, referencia intacta)
# ─────────────────────────────────────────────────────────────────────────────

_STREAM_DESCRIPTION = """
Genera el título y la descripción de un anuncio a partir del draft y responde
por **streaming SSE** (`text/event-stream`). En esta fase la inferencia es
**simulada**: el contrato es el definitivo, solo cambia el origen de los datos.

### Contrato de eventos

| Evento | Cuándo | Payload |
|---|---|---|
| `queued` | si hay que esperar turno (0..n veces, se re-emite al avanzar la fila) | `{"position": 2}` |
| `decision` | al tomar turno | `{"narrative", "tone", "audience", "themes", "highlightAmenities"}` |
| `delta` | por fragmento generado | `{"text": "..."}` |
| `done` | al terminar | `{"generationId", "title", "description", "durationS", "warnings"}` |
| `error` | ante fallo durante el stream | `{"detail": "..."}` |

Cada evento se serializa como `event: <nombre>\\ndata: <json>\\n\\n`.
La autenticación es por JWT (`Authorization: Bearer <token>`) emitido por el
backend transaccional.
"""

_SSE_EXAMPLE = (
    'event: decision\ndata: {"narrative": "hogar familiar con vida al aire libre", '
    '"tone": "cálido", "audience": "familias", "themes": ["aire libre"], '
    '"highlightAmenities": ["terraza", "jardín"]}\n\n'
    'event: delta\ndata: {"text": "Una "}\n\n'
    'event: delta\ndata: {"text": "casa "}\n\n'
    'event: done\ndata: {"generationId": "8f14e45f-…", "title": "Casa en Prudencio '
    'Moscoso para renta", "description": "Una casa amplia…", "durationS": 1.85, '
    '"warnings": []}\n\n'
)

_DRAFT_EXAMPLE = {
    "draft": {
        "id": "draft-001",
        "propertyType": {"id": "pt-house", "name": "Casa"},
        "address": {"neighborhoodName": "Prudencio Moscoso"},
        "availableToRent": True,
        "areaM2": 200.0,
        "bedrooms": 4,
        "bathrooms": 3,
        "parkingSpaces": 2,
        "constructionYear": 2025,
        "condominium": False,
        "listedPrice": 18500.0,
        "amenities": ["terraza", "jardín", "gimnasio"],
    }
}


@router.post(
    "/generators/stream",
    summary="Genera título y descripción de un anuncio (streaming SSE, simulado)",
    description=_STREAM_DESCRIPTION,
    tags=["generators"],
    dependencies=[Depends(verify_jwt)],
    responses={
        200: {
            "description": "Stream de eventos SSE: queued* → decision → delta* → done (o error).",
            "content": {"text/event-stream": {"example": _SSE_EXAMPLE}},
        },
        401: {"description": "JWT ausente, inválido o expirado."},
        503: {"description": "La cola de espera de generación está llena."},
    },
)
async def stream_generation(
    http_request: Request,
    request: GenerationRequest = Body(
        ...,
        openapi_examples={
            "draft-casa": {
                "summary": "Casa en renta con amenidades",
                "value": _DRAFT_EXAMPLE,
            }
        },
    ),
):
    # El cupo se verifica antes de abrir el stream para poder responder un 503
    # plano; si la fila se llena en el instante posterior, el fallo llega como
    # evento SSE `error`.
    if _queue(http_request).is_full:
        raise HTTPException(
            status_code=503,
            detail="La cola de generación está llena, intenta más tarde.",
        )

    use_case = _use_case(http_request)

    async def event_stream():
        async for event, payload in use_case.stream(request.draft):
            yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Desactiva el buffering en Nginx cuando el servicio corra tras el proxy.
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Rutas de inferencia real (fase 3)
# ─────────────────────────────────────────────────────────────────────────────

_CONTENTS_DESCRIPTION = """
Genera el título y la descripción de un anuncio con **inferencia real**:
ejecuta el pipeline completo grafo v4 → resumen v6 → llama-server (Qwen3).
Responde por **streaming SSE** (`text/event-stream`).

### Contrato de eventos

| Evento | Cuándo | Payload |
|---|---|---|
| `queued` | mientras espera turno en la cola | `{"position": n}` |
| `title` | al completarse el valor de `"titulo"` en el stream del LLM | `{"text": "..."}` |
| `delta` | por fragmento del valor de `"descripcion"` | `{"text": "..."}` |
| `done` | al terminar | `{"generationId", "title", "description"}` |
| `error` | ante fallo | `{"detail": "..."}` |

Cada evento: `event: <nombre>\\ndata: <json>\\n\\n`.
La autenticación es por JWT (`Authorization: Bearer <token>`).
"""

_CONTENTS_SSE_EXAMPLE = (
    'event: title\ndata: {"text": "Casa en Prudencio Moscoso para renta"}\n\n'
    'event: delta\ndata: {"text": "Un espacio "}\n\n'
    'event: delta\ndata: {"text": "pensado para la familia,"}\n\n'
    'event: done\ndata: {"generationId": "8f14e45f-cecc-4a06-bfef-3b8d29c28fd7", '
    '"title": "Casa en Prudencio Moscoso para renta", '
    '"description": "Un espacio pensado para la familia…"}\n\n'
)


@router.post(
    "/contents/generations",
    summary="Genera título y descripción con inferencia real (streaming SSE)",
    description=_CONTENTS_DESCRIPTION,
    tags=["contents"],
    dependencies=[Depends(verify_jwt), Depends(require_premium)],
    responses={
        200: {
            "description": "Stream SSE: queued* → title → delta* → done (o error).",
            "content": {"text/event-stream": {"example": _CONTENTS_SSE_EXAMPLE}},
        },
        401: {"description": "JWT ausente, inválido o expirado."},
        403: {"description": "El usuario no tiene suscripción Premium activa."},
        422: {"description": "Draft inválido (falta un campo requerido)."},
        503: {
            "description": (
                "Cola de generación llena, llama-server no disponible al "
                "iniciar el stream, o no se pudo verificar el estado de suscripción."
            )
        },
    },
)
async def stream_content_generation(
    http_request: Request,
    request: GenerationRequest = Body(
        ...,
        openapi_examples={
            "draft-casa": {
                "summary": "Casa en renta con amenidades",
                "value": _DRAFT_EXAMPLE,
            }
        },
    ),
):
    if _queue(http_request).is_full:
        raise HTTPException(
            status_code=503,
            detail="La cola de generación está llena, intenta más tarde.",
        )

    use_case = _content_use_case(http_request)

    async def event_stream():
        async for event, payload in use_case.stream(request.draft):
            yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/contents/generations",
    summary="Historial paginado de generaciones",
    description=(
        "Lista las generaciones persistidas, con filtro opcional por `draftId`. "
        "Ordenadas de más reciente a más antigua."
    ),
    tags=["contents"],
    response_model=GenerationListResponse,
    dependencies=[Depends(verify_jwt)],
    responses={
        401: {"description": "JWT ausente, inválido o expirado."},
    },
)
async def list_generations(
    http_request: Request,
    draft_id: str | None = Query(None, alias="draftId"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    use_case = _list_use_case(http_request)
    return await use_case.list(draft_id=draft_id, limit=limit, offset=offset)


@router.get(
    "/contents/generations/{generation_id}",
    summary="Detalle de una generación por ID",
    tags=["contents"],
    response_model=GenerationRecord,
    dependencies=[Depends(verify_jwt)],
    responses={
        401: {"description": "JWT ausente, inválido o expirado."},
        404: {"description": "Generación no encontrada."},
    },
)
async def get_generation(http_request: Request, generation_id: _uuid.UUID):
    use_case = _list_use_case(http_request)
    record = await use_case.get(generation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Generación no encontrada.")
    return record

