import json

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..auth.jwt_auth import verify_jwt
from ..models.generation import GenerationRequest
from ..services.request_queue import RequestQueue
from ..usecases.generate_listing import GenerateListingUseCase

router = APIRouter()


def _queue(request: Request) -> RequestQueue:
    return request.app.state.request_queue


def _use_case(request: Request) -> GenerateListingUseCase:
    return GenerateListingUseCase(
        client=request.app.state.llm_client,
        queue=request.app.state.request_queue,
    )


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
    summary="Genera título y descripción de un anuncio (streaming SSE)",
    description=_STREAM_DESCRIPTION,
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
