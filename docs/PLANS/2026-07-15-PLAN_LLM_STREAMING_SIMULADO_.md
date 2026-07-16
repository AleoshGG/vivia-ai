# Plan: LLM Local Service — Fase 1: comunicación por streaming (SSE) con inferencia simulada, cola de espera y JWT

## Contexto

`src/llm_local_service/` es hoy un esqueleto que encola en RabbitMQ ([generate_inference.py](src/llm_local_service/usecases/generate_inference.py)), pero el diseño real (definido en `docs/PLANS/2026-07-15-PLAN_LLM_GENERATORS_SERVICE_.md` tras la experimentación) es **streaming HTTP directo al cliente móvil**: el móvil manda el draft, el servicio responde por SSE.

Esta fase cubre **exclusivamente el mecanismo de comunicación**: petición de inferencia → cola de espera → respuesta por streaming SSE de punta a punta con datos simulados, autenticada con **JWT** (este servicio recibe tráfico directo del móvil, no usa la API key interna), y documentada en Swagger. **Todo lo relacionado con el modelo queda fuera** (cliente a llama-server, prompts, parseo de salida del LLM, motor de grafo, persistencia, MLflow, Docker).

Se toma como referencia la arquitectura del servicio de anomalías (`src/anomaly_detector_api/`): App Factory + lifespan con `app.state`, controllers delgados que delegan a use cases, modelos Pydantic con alias camelCase.

## Decisiones clave de diseño

1. **Backend simulado tras una interfaz.** El controller, el use case, la cola y el contrato SSE son código de producción real; lo único simulado es la fuente de los datos. Se define una interfaz `LlmClient` (`stream_chat(...) -> AsyncIterator[str]`) y en esta fase su única implementación es `SimulatedLlmClient`, que emite fragmentos de un anuncio pre-armado con `asyncio.sleep` entre cada uno (streaming observable de verdad). La fase del modelo enchufa la implementación real sin tocar nada más.

2. **Cola de espera en el propio servicio.** El LLM real atenderá una generación a la vez (`--parallel 1`), así que las peticiones concurrentes deben formarse. Se implementa con `asyncio.Semaphore(llm_max_concurrent)` + contador de posición: la petición que encuentra el turno ocupado emite un evento SSE `queued` con su posición y espera; si la cola está llena se rechaza con **503** antes de abrir el stream. Es una cola en memoria del proceso (suficiente: hay un solo worker de este servicio); RabbitMQ sale de este flujo.

   **¿Rompe esto el stateless del servidor? No.** Stateless significa que ninguna petición depende de datos que una petición *anterior* dejó en memoria (sesiones, resultados a medio consumir). El semáforo es otra categoría: **estado efímero de coordinación de peticiones en vuelo**, cuya vida es exactamente la de las conexiones SSE abiertas — la misma clase de estado de runtime que el pool de conexiones o el event loop, inevitable en cualquier servidor de streaming. Si el proceso se reinicia no se pierde nada recuperable (las conexiones encoladas mueren con él y el móvil reintenta), por eso encolarlo en un broker durable tampoco aportaría: RabbitMQ guardaría trabajos cuyo destinatario —la conexión— ya no existe. El estado que sí debe sobrevivir se externaliza donde corresponde: historial → PostgreSQL (fase siguiente), identidad → JWT (viaja en cada request). Límite conocido: con **varias réplicas** el límite de concurrencia dejaría de ser global; ese día el contador se muda a Redis, y como queda encapsulado en `RequestQueue`, el cambio no toca controller ni use case.

3. **JWT únicamente en este servicio.** El móvil se autentica con `Authorization: Bearer <token>`. Se crea una dependencia `verify_jwt` local al servicio (no en `shared/`, que conserva la API key para los demás). Validación con **PyJWT**: firma HS256 con `jwt_secret_key` (algoritmo configurable para migrar a RS256 si el emisor lo requiere), expiración (`exp`), y extracción de `sub` como identificador del usuario. Token ausente/inválido/expirado → **401** con `WWW-Authenticate: Bearer`.

## Alcance

**Incluido**
1. Interfaz `LlmClient` + implementación simulada (`services/llm_client.py`).
2. Cola de espera (`services/request_queue.py`) con evento SSE `queued` y rechazo 503 al llenarse.
3. Autenticación JWT propia del servicio (`auth/jwt_auth.py`).
4. Endpoint `POST /api/llm/generators/stream` con respuesta SSE simulada de punta a punta.
5. Documentación Swagger completa en `/api/llm/docs` (contrato SSE evento por evento, esquema Bearer, ejemplo de draft).
6. Modelos Pydantic del contrato (Draft, request, eventos SSE, resultado).
7. Eliminación del esqueleto viejo de RabbitMQ.
8. Tests de integración del endpoint.

**Excluido (fases siguientes)**
- Cualquier cosa del modelo: cliente REST a llama-server, prompts, parseo de la salida del LLM, settings de inferencia.
- Persistencia/migraciones/historial (`GET /generators`), motor de grafo, MLflow.
- Emisión/refresh de JWT (los emite el backend transaccional; aquí solo se validan).
- Endpoint no-stream, contenedor llama-server, Dockerfile, nginx (`proxy_buffering off` se hará cuando se pruebe tras el proxy).

## Contrato SSE (`text/event-stream`, payloads camelCase)

| Evento | Cuándo | Payload |
|---|---|---|
| `queued` | si hay que esperar turno (0..n veces) | `{"position": 2}` (se re-emite cuando avanza la fila) |
| `decision` | al tomar turno | `DecisionPayload` (en esta fase: valores fijos de ejemplo — narrative, tone, audience, themes, highlightAmenities) |
| `delta` | por fragmento | `{"text": "..."}` |
| `done` | al terminar | `{"generationId", "title", "description", "durationS", "warnings"}` |
| `error` | ante fallo | `{"detail"}` |

Respuestas HTTP antes de abrir el stream: **401** (JWT ausente/inválido), **422** (draft inválido), **503** (cola llena). El móvil puede integrarse contra este contrato desde ya.

## Cambios por archivo

### `src/llm_local_service/auth/jwt_auth.py` (nuevo)
- `HTTPBearer(auto_error=False)` + dependencia `verify_jwt` que decodifica con PyJWT (`settings.jwt_secret_key`, `settings.jwt_algorithm`), valida `exp` y regresa los claims (`sub`).
- Errores → `HTTPException(401, headers={"WWW-Authenticate": "Bearer"})` con detalle distinguible (token faltante / inválido / expirado).

### `src/llm_local_service/models/generation.py` (nuevo)
Contratos Pydantic con alias camelCase y `populate_by_name` (mismo estilo que [models/property.py](src/anomaly_detector_api/models/property.py) de anomalías):
- `Draft` — subconjunto relevante para generación: `propertyType`, `address.neighborhoodName`, `availableToRent`, `areaM2`, `bedrooms`, `bathrooms`, `parkingSpaces`, `constructionYear`, `condominium`, `listedPrice`, `amenities: list[str]`.
- `GenerationRequest {draft: Draft}`.
- `QueuedPayload {position}`, `DecisionPayload`, `DeltaPayload {text}`, `GenerationResult` (payload del `done`), `ErrorPayload {detail}`.

### `src/llm_local_service/services/request_queue.py` (nuevo)
`RequestQueue(max_concurrent, max_queue_size)`:
- `acquire()` como async context manager: si hay cupo inmediato entra; si no, registra la posición y expone un async iterator/callback de cambios de posición (para emitir `queued`); si `en_espera >= max_queue_size` lanza `QueueFullError`.
- Implementación con `asyncio.Semaphore` + contador protegido por `asyncio.Lock`. Vive en `app.state`.

### `src/llm_local_service/services/llm_client.py` (nuevo)
- Interfaz (Protocol o ABC) `LlmClient`: `stream_chat(user_message: str) -> AsyncIterator[str]`, `close()`.
- `SimulatedLlmClient(LlmClient)` — anuncio canónico embebido (título + descripción de ejemplo); `stream_chat` trocea la descripción en fragmentos de pocos caracteres y hace yield con `await asyncio.sleep(settings.llm_simulated_delay_s)`.

### `src/llm_local_service/usecases/generate_listing.py` (nuevo)
`GenerateListingUseCase(client: LlmClient, queue: RequestQueue)` con `stream(draft) -> AsyncIterator[tuple[str, dict]]` (nombre de evento, payload):
1. Entra a la cola: mientras espera turno emite `queued {position}`.
2. Con turno tomado emite `decision` (payload fijo de ejemplo).
3. Itera `client.stream_chat(...)` acumulando el texto y emitiendo `delta` por fragmento.
4. Al terminar arma `GenerationResult` (uuid4, título simulado, descripción acumulada, duración medida real, `warnings=[]`) y emite `done`.
5. Ante excepción emite `error`, libera el turno y termina el stream (log con `logging`, patrón de [analyze_property.py](src/anomaly_detector_api/usecases/analyze_property.py)). El turno se libera siempre (context manager), incluida la desconexión del cliente.

La orquestación queued→decision→delta→done→error es la lógica real que sobrevive intacta a la fase con modelo.

### `src/llm_local_service/controllers/llm_controller.py` (reescribir)
- `POST /generators/stream` → `StreamingResponse(media_type="text/event-stream")` serializando `event: <nombre>\ndata: <json>\n\n`; `dependencies=[Depends(verify_jwt)]`; cliente y cola desde `app.state` vía helpers (patrón del controller de anomalías).
- `QueueFullError` → `HTTPException(503)` (se verifica cupo antes de arrancar el `StreamingResponse` para poder responder 503 plano).
- OpenAPI completo: `summary`, `description` en Markdown con la tabla del contrato SSE, `responses` declarando `text/event-stream` en el 200 y las respuestas 401/422/503, esquema de seguridad Bearer (visible el candado en Swagger UI), y ejemplo de request con un draft realista (`Body(openapi_examples=...)`).

### `src/llm_local_service/exceptions/llm_exceptions.py` (completar)
`GenerationError` (fallo durante el stream → evento `error`), `QueueFullError`.

### `src/llm_local_service/main.py` (ajustar lifespan)
Lifespan: instanciar `SimulatedLlmClient` y `RequestQueue`, guardarlos en `app.state`; teardown llama `close()`. `docs_url`/`openapi_url` ya están bien configurados. El router de health se mantiene (sin auth).

### `config/settings.py` (agregar)
`llm_simulated_delay_s: float = 0.05`, `llm_max_concurrent: int = 1`, `llm_max_queue_size: int = 10`, `jwt_secret_key: str` (desde `.env`), `jwt_algorithm: str = "HS256"`. Agregar `JWT_SECRET_KEY` a `.env.example`.

### Limpieza del esqueleto viejo
Eliminar `usecases/generate_inference.py` y `models/inference.py`; en `src/llm_local_service/requirements.txt` quitar `pika` y agregar `PyJWT`.

### Tests — `tests/integration/test_llm_api.py` (nuevo, espejo de `test_anomaly_api.py`)
Con `TestClient` (genera JWT de prueba firmado con el secret de test en `conftest`):
- `/api/llm/health` → 200.
- `POST /generators/stream` sin token → 401; con token expirado/firma inválida → 401.
- Con token válido: respuesta `text/event-stream`; el stream contiene `decision`, ≥1 `delta`, y termina con `done` cuyo payload trae `generationId`, `title` y `description` no vacíos (descripción del `done` == concatenación de los `delta`).
- Cola: con `llm_max_concurrent=1`, dos peticiones concurrentes → la segunda recibe `queued` antes de `decision`; con cola llena → 503.
- `/api/llm/openapi.json` incluye el endpoint con su descripción y el esquema Bearer.

### Documentación
- Paso 1 de la implementación: crear `docs/PLANS/2026-07-15-PLAN_LLM_STREAMING_SIMULADO_.md` con este plan (requisito del CLAUDE.md del proyecto). El plan maestro `2026-07-15-PLAN_LLM_GENERATORS_SERVICE_.md` queda como referencia de las fases siguientes.

## Dependencias

- `shared/health.py` (se reutiliza). `shared/auth_middleware.py` NO se usa aquí (JWT propio del servicio).
- `PyJWT` (nueva dependencia del servicio).
- Ningún servicio externo: no se necesita llama-server, Postgres ni RabbitMQ.

## Pasos de implementación

1. Crear el plan en `docs/PLANS/2026-07-15-PLAN_LLM_STREAMING_SIMULADO_.md`.
2. Settings nuevos (`llm_*`, `jwt_*`) y `.env.example`.
3. `auth/jwt_auth.py`.
4. `models/generation.py` (contratos).
5. `exceptions/llm_exceptions.py`.
6. `services/llm_client.py` (interfaz + simulado) y `services/request_queue.py`.
7. `usecases/generate_listing.py` (orquestación del stream).
8. `controllers/llm_controller.py` + ajuste de `main.py` (lifespan con `app.state`).
9. Eliminar esqueleto viejo y actualizar `requirements.txt`.
10. `tests/integration/test_llm_api.py`.
11. Verificación end-to-end.

## Verificación

1. `pytest tests/` — verde (incluye los tests existentes de anomalías).
2. Levantar solo el servicio: `uvicorn src.llm_local_service.main:app --port 8003`.
3. Generar un JWT de prueba (script/una línea con PyJWT y el secret del `.env`) y:
   `curl -N -X POST http://localhost:8003/api/llm/generators/stream -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d @draft_ejemplo.json` → `decision` inmediato, `delta` llegando progresivamente (streaming real, no de golpe) y `done` final.
4. Dos curls simultáneos → el segundo muestra `queued` antes de su `decision`.
5. Sin token o token inválido → 401; draft malformado → 422.
6. Abrir `http://localhost:8003/api/llm/docs` → endpoint documentado con contrato SSE, candado Bearer y ejemplo de draft.
