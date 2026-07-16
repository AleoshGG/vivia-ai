# Plan: LLM Local Service — Fase 3: inferencia real (grafo → llama-server) con POST /contents/generations + historial persistido

## Contexto

Las fases 1 (streaming SSE simulado + cola + JWT) y 2 (artefactos versionados en MLflow/GCS + contenedor `llama-server`) ya están implementadas. Ahora se implementa la **inferencia real**: un endpoint nuevo `POST /api/llm/contents/generations` que recibe el draft, corre el pipeline validado en los notebooks — **1) cargar el grafo, 2) inferir sobre él, 3) generar con el LLM** — y responde por streaming SSE.

Decisiones del usuario:
- **La simulación NO se elimina**: `POST /generators/stream` queda intacto como referencia; el endpoint nuevo se construye con la misma lógica de streaming.
- **El móvil solo recibe texto** (title y description) para renderizar rápido; todo lo demás — decisión del grafo, tiempos, tokens/s, tokens de entrada, RAM — se **persiste en PostgreSQL** en una tabla de inferencias con endpoints de historial.

Pipeline de referencia: [notebooks/graph-ai/prompt.py](notebooks/graph-ai/prompt.py) (v6: el LLM solo ve `resumen_para_llm`, nunca el draft crudo) con motor en [notebooks/graph-ai/motor_inferencia.py](notebooks/graph-ai/motor_inferencia.py) (343 líneas, 16 tests en `test_motor.py`). Sampling validado: `temperature=1.0, top_p=0.8, top_k=20, max_tokens=512`, `chat_template_kwargs={"enable_thinking": false}`.

## Alcance

**Incluido**
1. Motor del grafo **refactorizado a inglés** y separado por responsabilidad única en `models/` (estructuras), `services/` (carga del grafo, inferencia, construcción del resumen) y `usecases/` (orquestación).
2. Cliente HTTP real a llama-server (streaming SSE OpenAI-compat) implementando la interfaz `LlmClient` existente.
3. Parser incremental del JSON del LLM → deltas de texto limpio para el móvil.
4. `POST /api/llm/contents/generations` (SSE: `queued* → title → delta* → done | error`) con JWT y la misma `RequestQueue`.
5. Persistencia en tabla `llm_generations` (espejo del patrón de anomalías) + migración alembic `0002`.
6. Historial: `GET /contents/generations` (paginado, filtro `draft_id`) y `GET /contents/generations/{id}`.

**Excluido**
- Eliminar/renombrar `POST /generators/stream` (queda como referencia con el cliente simulado).
- Tests (decisión del usuario).
- Nginx, deploy al VPS, emisión de JWT, réplicas múltiples.

## Contrato del endpoint nuevo (`text/event-stream`, JWT Bearer)

`POST /api/llm/contents/generations` — body `{"draft": {...}}` (el `Draft` existente en [models/generation.py](src/llm_local_service/models/generation.py) ya acepta el draft esperado; los campos extra como `lessorId` se ignoran).

| Evento | Cuándo | Payload |
|---|---|---|
| `queued` | mientras espera turno | `{"position": n}` |
| `title` | al completarse el valor de `"titulo"` en el stream del LLM | `{"text": "..."}` |
| `delta` | por fragmento del valor de `"descripcion"` | `{"text": "..."}` |
| `done` | al terminar | `{"generationId", "title", "description"}` |
| `error` | ante fallo | `{"detail"}` |

HTTP: 401 (JWT), 422 (draft inválido), 503 (cola llena o llama-server caído al arranque del stream).

## Cambios por capa (`src/llm_local_service/`)

### 1. Motor del grafo — refactor a inglés con responsabilidad única (desde `notebooks/graph-ai/motor_inferencia.py`)

Misma semántica que el motor validado (pesos {0.3, 0.6, 0.9}, bloqueo −10, prior máx 0.8, k=2, umbral 0.5, traza), pero separado por capa y con identificadores en inglés. Los textos que produce (frases, hechos, resumen) siguen en español — son contenido del prompt, no código.

- **`models/graph.py`** (nuevo) — solo estructuras de datos (dataclasses):
  - `Edge` (origin, target, weight, relation, reason) ← `Arista`.
  - `Domain` (amenities, themes, property_types, operations, audiences, buckets, edges, alias_to_amenity, edges_from()) ← `Dominio`.
  - `Decision` (draft_id, activations, unknown_amenities, scores, blocked, themes, audience, main_amenities, secondary_amenities, facts, trace) ← `Decision`.
- **`services/graph_loader.py`** (nuevo) — SOLO carga y validación: `load_domain(datasets_path) -> Domain` ← `cargar_dominio` + `_leer` (lee los 10 CSVs de `resources/graph/`, valida pesos/relaciones/referencias). Incluye `normalize()` ← `_normalizar` (util compartida del grafo).
- **`services/graph_inference.py`** (nuevo) — SOLO la inferencia: `GraphInferenceService(domain)` con `infer(draft: dict, k=2, threshold=0.5) -> Decision` ← `inferir` + `activar` + `buckets_de` + constantes (`BLOCK_WEIGHT`, `VALID_WEIGHTS`, `MAX_PRIOR`, `BUCKET_FACTS`).
- **`services/summary_builder.py`** (nuevo) — SOLO la construcción del mensaje al LLM: `build_summary(domain, draft, decision) -> str` ← `resumen_para_llm` (v6: es lo ÚNICO que ve el LLM; `draft_json_a_texto` no se migra porque v6 no manda el draft crudo). Carga también el system prompt: `load_system_prompt(resources_path) -> str` desde `resources/prompts/system_prompt_v6.txt`.
- `cargar_drafts` no se migra (utilería de notebook). El notebook original queda intacto como laboratorio.

### 2. Arranque del dominio
`main.py` carga el `Domain` UNA vez en el lifespan (`load_domain`) y construye `GraphInferenceService`; ambos viven en `app.state`. No hay clase "engine" adicional: la orquestación grafo→LLM es responsabilidad del use case (sección 7).

### 3. Cliente real — `services/llm_client.py` (agregar clase, interfaz intacta)
`LlamaServerHttpClient(LlmClient)`:
- `httpx.AsyncClient` persistente; `stream_chat(user_message)` → `POST {settings.llama_server_url}/v1/chat/completions` con `stream: true`, system prompt v6, sampling de settings, `chat_template_kwargs {"enable_thinking": false}` y `stream_options {"include_usage": true}`; parsea líneas `data: {...}` del SSE y hace yield del `delta.content` de cada chunk.
- Guarda el chunk final con `usage` (y `timings` si llama-server lo manda) en `self.last_usage` — seguro porque el semáforo (`llm_max_concurrent=1`) serializa las generaciones.
- `health()` (GET `/health`) y `wait_until_ready(retries, delay)` para el startup (patrón `_wait_for_mlflow`); `close()` cierra el `AsyncClient`.
- El system prompt se inyecta en el constructor (viene del `GeneratorEngine`); `SimulatedLlmClient` no se toca.

### 4. Parser incremental — `services/listing_stream_parser.py` (nuevo)
`ListingStreamParser` con `feed(fragment) -> list[tuple[str, str]]` (eventos `("title", texto)` / `("delta", texto)`): acumula el JSON crudo del LLM, ignora el preámbulo hasta `{`, detecta las claves `"titulo"` y `"descripcion"` y emite el contenido de sus valores string conforme llega, manejando escapes (`\"`, `\n`, `\uXXXX`) y cualquier orden de claves. Al final, `result() -> (title, description)` con el JSON completo parseado (`json.loads` como verificación; si difiere, ganan los valores completos). Unit-testeable en aislamiento.

### 5. Persistencia — `persistence/` (nuevo, espejo de anomalías)
- `database.py` — copia del patrón de [anomaly database.py](src/anomaly_detector_api/persistence/database.py): `build_engine`, `build_session_factory`, `init_models` con `Base` propia.
- `models_db.py` — tabla **`llm_generations`**: `id UUID PK`, `draft_id str (index)`, `title str`, `description text`, `decision JSONB` (el `Decision` completo del grafo: temas, audiencia, protagonistas, secundarias, desconocidas, hechos, scores, activaciones, traza), `warnings JSONB`, `graph_ms float`, `llm_s float`, `duration_s float`, `prompt_tokens int`, `output_tokens int`, `tokens_per_second float`, `ram_mb float`, `model_file str`, `prompt_version str`, `graph_version str`, `source str`, `created_at timestamptz server_default now()`.
- `generation_repository.py` — `GenerationRepository` con `save(**campos)`, `list(draft_id, limit, offset) -> (items, total)`, `get(id)` (espejo de [inference_repository.py](src/anomaly_detector_api/persistence/inference_repository.py)).
- Migración `alembic/versions/0002_create_llm_generations.py` (espejo de `0001`); `init_models` en el lifespan mantiene la conveniencia dev (ambos caminos conviven, ver docstring de anomalías).

### 6. Modelos — `models/generation.py` (agregar)
- `TitlePayload {text}` (o reutilizar `DeltaPayload`), `ContentResult {generation_id→generationId, title, description}` (payload del `done`, mínimo para el móvil).
- `GenerationRecord` (espejo de `InferenceRecord`: todos los campos de la tabla, camelCase, `from_attributes=True`) y `GenerationListResponse {total, limit, offset, items}`.

### 7. Use cases
- `usecases/generate_content.py` — `GenerateContentUseCase(domain, inference, client, queue, repository)` con `stream(draft)`:
  1. cola (`queued*`, patrón del use case simulado);
  2. `inference.infer(draft.model_dump(by_alias=True))` midiendo `graph_ms` → `Decision`; `build_summary(...)` → user message;
  3. `client.stream_chat(...)` midiendo `llm_s`, alimentando el `ListingStreamParser` y emitiendo `title`/`delta`;
  4. arma `ContentResult` (uuid4), verifica con regex precio/contacto (los `RE_PRECIO`/`RE_CONTACto` de los benchmarks) → `warnings`;
  5. persiste (fallo de persistencia se loguea y NO aborta — patrón de anomalías); métricas: tokens de `client.last_usage`, `tokens_per_second = output_tokens / llm_s`, `ram_mb` = RSS del proceso vía `psutil`; estampas `model_file=settings.llm_gguf_file`, `prompt_version="v6"`, `graph_version="v4"`;
  6. `done`; ante excepción `error` + liberación del turno (mismo `finally` del simulado).
- `usecases/list_generations.py` — `ListGenerationsUseCase` (espejo de [list_inferences.py](src/anomaly_detector_api/usecases/list_inferences.py)).

### 8. Controller — `controllers/llm_controller.py` (agregar rutas; las existentes intactas)
- `POST /contents/generations` — mismo esqueleto SSE que `/generators/stream` (503 si `is_full`, `StreamingResponse`, headers anti-buffering), `Depends(verify_jwt)`, OpenAPI completo con la tabla de eventos y el draft de ejemplo del usuario.
- `GET /contents/generations` — `response_model=GenerationListResponse`, filtros `draft_id`, `limit`, `offset`, JWT.
- `GET /contents/generations/{generation_id}` — `response_model=GenerationRecord`, 404 si no existe, JWT.
- Tag nuevo `contents` en el router.

### 9. main.py (lifespan)
- Engine de BD + session factory + `init_models` + `GenerationRepository` en `app.state`.
- `load_domain(...)` + `GraphInferenceService` + system prompt (`load_system_prompt`) en `app.state`.
- `LlamaServerHttpClient` con `wait_until_ready` (no bloquea el arranque si falla: loguea y el endpoint responderá 503, patrón tolerante) en `app.state.llama_client` — el simulado sigue en `app.state.llm_client` para el endpoint viejo.
- Teardown: `llama_client.close()`, `engine.dispose()`.

### 10. Config y dependencias
- `config/settings.py` (sección LLM): `llm_temperature: float = 1.0`, `llm_top_p: float = 0.8`, `llm_top_k: int = 20`, `llm_max_tokens: int = 512`, `llm_request_timeout: float = 120.0`, `graph_resources_path: Path = Path("src/llm_local_service/resources")`.
- `src/llm_local_service/requirements.txt`: agregar `httpx`, `sqlalchemy[asyncio]`, `asyncpg`, `psutil`.
- `pyproject.toml`: agregar los mismos si faltan (hoy no lista sqlalchemy/asyncpg/httpx/psutil).

### 11. Documentación
- `docs/PLANS/2026-07-16-PLAN_LLM_INFERENCIA_REAL_CONTENTS_GENERATIONS_.md` con este plan (paso 1, requisito del CLAUDE.md).
- Actualizar `docs/contexto/arquitectura.md` (endpoint real + historial persistido).

## Dependencias

- Fase 2 ya entregada: contenedor `llama-server` (compose) y artefactos en `resources/`.
- PostgreSQL del compose (misma BD que anomalías); alembic ya configurado (`0001` como plantilla).
- Para correr end-to-end local: llama-server arriba (contenedor o binario de `notebooks/graph-ai/tools/`) y Postgres.

## Pasos de implementación

1. Crear el plan en `docs/PLANS/`.
2. Settings y requirements/pyproject.
3. Refactor del motor: `models/graph.py`, `services/graph_loader.py`, `services/graph_inference.py`, `services/summary_builder.py`.
4. `services/listing_stream_parser.py`.
5. Persistencia (`database.py`, `models_db.py`, `generation_repository.py`) + alembic `0002`.
6. Modelos Pydantic nuevos (`ContentResult`, `GenerationRecord`, `GenerationListResponse`).
7. `LlamaServerHttpClient`.
8. Use cases (`generate_content.py`, `list_generations.py`).
9. Controller (3 rutas nuevas) + lifespan en `main.py`.
10. Actualizar documentación de contexto.
