# Plan: LLM Generators Service — FastAPI con streaming HTTP (SSE), persistencia e historial

## Objetivo

Reescribir `src/llm_local_service` (hoy esqueleto que encola en RabbitMQ) como el microservicio
real de generación de título + descripción: recibe el draft, responde por **streaming HTTP
directo al cliente móvil** (sin webhooks — solo responses bien estructurados), persiste cada
inferencia en PostgreSQL, expone el historial, documenta con Swagger y versiona sus artefactos
en MLflow.

Stack decidido en las fases de experimentación (ver fases 1–3 en
`2026-07-14-PLAN_LLM_GENERACION_TITULO_DESCRIPCION_.md` y `notebooks/llm/METRICAS.md`):
**Qwen3-4B-Instruct-2507 Q4_K_M** servido por **llama-server** (23 s/anuncio local, 9.3 tok/s)
+ **grafo ponderado v4** (motor con 67 tests, decide en <1 ms) + prompt v4 (~590 tokens,
0 violaciones de precio/contacto).

## Reglas de estructura

- Producción NUNCA importa desde `notebooks/` — se copian los archivos a las carpetas del
  servicio. Los notebooks siguen siendo laboratorio.
- `shared/` es solo para recursos que TODOS los microservicios conocen — el grafo es exclusivo
  del LLM y vive dentro de `src/llm_local_service/`.
- Nombres de recursos, código y contratos en inglés. El recurso se expone como **`/generators`**.

## Arquitectura

```
Cliente móvil ──POST /api/llm/generators/stream──> Nginx ──> llm_local_service (FastAPI :8003)
                                                                │ 1. graph inference engine (<1 ms)
                                                                │ 2. prompt v4
                                                                ▼
                                                             llama-server (contenedor :8080)
                                                                │ stream SSE (gramática JSON)
                                                                ▼
                                      SSE al móvil: decision → delta* → done
                                                                │
                                                                ▼ (al completar)
                                                          PostgreSQL (historial)
```

- **llama-server en contenedor propio** (`ghcr.io/ggml-org/llama.cpp:server`), GGUF montado
  desde `models_registry/`. El servicio FastAPI solo habla HTTP (sin llama-cpp-python).
- **Anti-saturación**: `--parallel 1` + `asyncio.Semaphore(llm_max_concurrent)` en el servicio.
- RabbitMQ sale de este flujo (streaming directo); se elimina el encolado del esqueleto.

### Contrato SSE (`text/event-stream`, payloads Pydantic camelCase)

| Evento | Cuándo | Payload |
|---|---|---|
| `decision` | inmediato | decisiones del grafo: narrative, tone, audience, themes, highlightAmenities, facts, unknownAmenities |
| `delta` | por fragmento | `{"text": "..."}` |
| `done` | al terminar | `{"generationId", "title", "description", "durationS", "promptTokens", "outputTokens", "warnings"}` |
| `error` | ante fallo | `{"detail"}` + códigos HTTP correctos (403 sin key, 422 draft inválido, 503 llama-server caído) |

### Endpoints (`/api/llm`, todos con `X-Internal-API-Key`, documentados en Swagger)

| Método y ruta | Función |
|---|---|
| `POST /generators/stream` | Genera título+descripción con SSE; persiste al completar |
| `POST /generators` | Igual sin streaming: espera y regresa el `GenerationResult` completo |
| `GET /generators` | Historial paginado de inferencias (filtros: `draft_id`, `limit`, `offset`) |
| `GET /generators/{generation_id}` | Detalle de una inferencia |
| `GET /health` | Ya existe (shared); el lifespan verifica llama-server al arranque |

Swagger: `summary`, `description` (incluyendo el contrato SSE evento por evento),
`response_model`, ejemplos de request con el draft real, `tags=["generators"]` — en
`/api/llm/docs`.

## Cambios por capa (`src/llm_local_service/`)

### 1. Recursos del grafo (copias desde notebooks, API en inglés)
- `resources/graph/*.csv` + `README.md` — copia de `notebooks/graph-ai/datasets/`.
- `services/graph_inference.py` — copia adaptada de `motor_inferencia.py` con API pública en
  inglés: `load_domain()`, `activate()`, `infer() -> Decision`, `decision_summary()`,
  `draft_to_text()`. Misma semántica (k=2, umbral 0.5, bloqueos −10, traza).
- `services/prompts.py` — `SYSTEM_PROMPT` (v4) y `OUTPUT_SCHEMA` (gramática JSON).
- `tests/llm_service/test_graph_inference.py` — los 67 tests adaptados (mismos snapshots).

### 2. Modelos (`models/generation.py`) — contratos en inglés, alias camelCase
- `Draft` (propertyType, address.neighborhoodName, availableToRent, areaM2, bedrooms,
  bathrooms, parkingSpaces, constructionYear, condominium, listedPrice, amenities).
- `GenerationRequest {draft}`, `DecisionPayload`, `GenerationResult`,
  `GenerationRecord` / `GenerationListResponse` (espejo de los modelos de historial de
  anomalías).

### 3. Servicios
- `services/llama_client.py` — `httpx.AsyncClient` persistente: `stream_chat(system, user) ->
  AsyncIterator[str]` (parsea SSE OpenAI), `health()`, espera con reintentos al startup
  (patrón `_wait_for_mlflow`).
- `services/generator_engine.py` — carga el dominio del grafo una vez;
  `prepare(draft) -> (decision, user_message)`.

### 4. Use cases
- `usecases/generate_listing.py` — `GenerateListingUseCase.stream(draft)`: decisión → semáforo
  → deltas acumulados → parseo del JSON final → verificación regex (warnings) → persistencia
  (un fallo de persistencia no aborta, patrón de anomalías) → `done`. Método `execute(draft)`
  no-stream sobre el mismo generador.
- `usecases/list_generations.py` — espejo de `list_inferences.py`.
- Se eliminan `usecases/generate_inference.py` y `models/inference.py` (esqueleto viejo).

### 5. Persistencia (espejo del patrón de anomalías)
- `persistence/database.py` — `build_engine`, `build_session_factory`, `init_models`.
- `persistence/generation_repository.py` — tabla **`llm_generations`**: `id UUID PK`,
  `draft_id`, `title`, `description`, `decision JSONB`, `prompt_tokens int`,
  `output_tokens int`, `duration_s float`, `warnings JSONB`, `model_version str`,
  `graph_version str`, `source str`, `created_at timestamptz`. Métodos `save`, `list`, `get`.
- Migración: mismo mecanismo vigente que anomalías (`init_models` en lifespan; revisión
  alembic si el flujo del repo la usa).

### 6. Controller y main
- `controllers/llm_controller.py` — los 4 endpoints (StreamingResponse para SSE),
  `Depends(verify_internal_api_key)`, OpenAPI completo, inyección vía `app.state`.
- `main.py` — lifespan: engine+repository, dominio del grafo, `LlamaClient` con espera de
  `/health`; teardown cierra `AsyncClient` y `engine.dispose()`.
- `exceptions/llm_exceptions.py` — `LlamaServerUnavailable`, `InvalidGeneration`.

### 7. Config (`config/settings.py`, agregar)
`llama_server_url`, `llm_temperature=1.0`, `llm_max_tokens=512`, `llm_request_timeout=120.0`,
`llm_max_concurrent=1`, `llm_model_name="llm-listing-generator"`,
`llm_model_stage="Production"`, `llm_gguf_file="Qwen3-4B-Instruct-2507-Q4_K_M.gguf"`,
`graph_resources_path`.

### 8. Versionado en MLflow
- `scripts/register_llm_generator.py` — espejo idempotente de `register_anomaly_model.py`:
  registra **`llm-listing-generator`** con artefactos: CSVs del grafo, system prompt
  (prompt.txt) y `metadata.json` (nombre/quant del GGUF + hash sha256, temperatura,
  max_tokens, versión del grafo); promueve a `Production`. El GGUF de 2.5 GB NO se sube
  (vive en `models_registry/llm/`; queda referenciado por hash).
- El servicio lee la versión del registry al startup y la estampa en `llm_generations`.

### 9. Infraestructura
- `compose.yml`: servicio `llama-server` (imagen oficial, volumen de `models_registry`,
  `--ctx-size 4096 --threads 4 --parallel 1`, healthcheck `/health`); `llm-local` con
  `depends_on` y `LLAMA_SERVER_URL`.
- `infrastructure/docker/llm_local.Dockerfile`: copiar `config/`, `shared/`,
  `src/llm_local_service/` (incluye `resources/graph/`); requirements sin llama-cpp-python
  (fastapi, uvicorn, httpx, pydantic, pydantic-settings, sqlalchemy[asyncio], asyncpg, mlflow).
- `infrastructure/nginx.conf`: location `/api/llm/` con `proxy_buffering off` y
  `proxy_read_timeout` amplio para SSE.

### 10. Tests (`tests/llm_service/`)
- `test_graph_inference.py` — los 67 del motor.
- `test_generate_listing.py` — usecase con cliente y repositorio falsos: orden
  decision→delta→done, JSON final, warnings, persistencia, evento `error`.
- `test_llm_controller.py` — 403 sin key; SSE termina en `done`; no-stream regresa
  `GenerationResult`; historial pagina; OpenAPI incluye los 4 endpoints.

### 11. Documentación
- Este plan + actualización de `docs/contexto/arquitectura.md` (LLM: llama-server + streaming
  directo al móvil, sin cola).
- `resources/graph/README.md` — flujo de sincronización notebook → producción → MLflow.

## Dependencias

- Artefactos ya existentes: GGUF en `models_registry/llm/`, grafo validado en
  `notebooks/graph-ai/` (fuente de las copias), binario llama-server local para pruebas.
- Servicios del compose: PostgreSQL (misma BD que anomalías), MLflow, Nginx.

## Fuera de alcance

- Webhooks/callbacks de cualquier tipo (la response estructurada ES el resultado).
- Subir el GGUF como artefacto MLflow (referenciado por hash).
- Deploy real al VPS; cambios en anomalías/clustering.

## Pasos de implementación

1. Copiar recursos del grafo al servicio (`resources/graph/`, `graph_inference.py` con API en
   inglés, `prompts.py`) + tests del motor adaptados → `pytest` verde.
2. Modelos Pydantic de contratos (`models/generation.py`).
3. Persistencia (`database.py`, `generation_repository.py`, tabla `llm_generations`).
4. Servicios (`llama_client.py`, `generator_engine.py`) y excepciones.
5. Use cases (`generate_listing.py` streaming + no-stream, `list_generations.py`).
6. Controller con los 4 endpoints + Swagger; `main.py` con lifespan completo.
7. Settings nuevos; eliminar esqueleto viejo (encolado).
8. Tests de usecase y controller.
9. `scripts/register_llm_generator.py` (MLflow, idempotente).
10. Infra: compose (llama-server), Dockerfile, nginx.
11. Verificación end-to-end local (curl SSE + historial) y actualización de documentación.

## Verificación

1. `pytest tests/` — todo verde.
2. End-to-end local sin Docker: llama-server (binario de `notebooks/graph-ai/tools/`) +
   Postgres + uvicorn; con draft-001: `curl -N POST /api/llm/generators/stream` → `decision`
   inmediato, deltas, `done` sin warnings; `POST /generators` → JSON; `GET /generators` →
   la inferencia aparece; sin API key → 403; `/api/llm/docs` documenta los 4 endpoints.
3. `python -m scripts.register_llm_generator` registra y promueve en MLflow (idempotente).
4. `docker compose config` valida; (opcional) `up llama-server llm-local` + curl.
