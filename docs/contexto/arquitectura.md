# Arquitectura — Vivia AI

## Stack Tecnológico

| Capa | Tecnología | Versión / Nota |
|------|-----------|----------------|
| Lenguaje | Python | 3.12 |
| Framework HTTP | FastAPI | — |
| Cola de mensajes | RabbitMQ | Persistencia + ACK |
| Data Lake | Google Cloud Storage | Abstracción vía patrón Repository |
| Model Registry | MLflow | Integración progresiva |
| LLM | Qwen3-1.7B-Q4_K_M (no-thinking) vía llama-server | Contenedor propio; sin APIs externas |
| Reverse Proxy | Nginx | + validación de API key |
| Contenedores | Docker + Docker Compose | — |
| Validación | Pydantic + pydantic-settings | — |

## Mapa de Carpetas

```
vivia-ai/
├── config/          → Configuración centralizada (settings, logging, .env)
├── data_lake/       → Patrón Repository para acceso al Data Lake
├── src/             → Microservicios (anomaly, clustering, llm)
│   └── <servicio>/  → models/ exceptions/ controllers/ usecases/ main.py
├── shared/          → Código reutilizable (auth, colas, health, model_loader)
├── notebooks/       → Experimentación y EDA
├── models_registry/ → Cache local de modelos (MLflow sincroniza)
├── tests/           → Unit + Integration tests
├── infrastructure/  → Dockerfiles, nginx.conf, cloud deploy scripts
├── docs/            → Documentación del proyecto
```

## Flujo de Datos

1. **API Transaccional** (externo) → webhook con `INTERNAL_API_KEY` en header
2. **Nginx** → valida API key, enruta al servicio
3. **FastAPI Service** → encola en **RabbitMQ** (mensaje persistente)
4. **Worker** → consume mensaje, ejecuta inferencia con modelo de **MLflow**
5. **Data Lake (GCS)** → accedido vía `StorageRepository` para lectura/escritura de datos

## Servicio LLM (generación de anuncios)

- **Flujo**: el móvil manda el draft con JWT → `llm_local_service` (FastAPI :8003) responde por **streaming SSE directo** (sin RabbitMQ ni webhooks). La inferencia real la hace el contenedor **llama-server** (`vivia-llama-server`, imagen oficial pineada a `server-b10015`, `--threads 4 --ctx-size 4096 --parallel 1`, no-thinking).
- **Stack versionado**: Qwen3-1.7B-Q4_K_M + prompt v6 + grafo ponderado v4. Los artefactos de producción viven en `src/llm_local_service/resources/` y se registran en MLflow como `llm-listing-generator` (`scripts/register_llm_generator.py`).
- **Respaldo en GCS**: el GGUF se sube al bucket con `scripts/upload_llm_model.py` (`gs://<bucket>/models_registry/llm/`) y MLflow lo referencia por URI + sha256; los demás artefactos aterrizan en el bucket vía `MLFLOW_ARTIFACT_ROOT`. Para servir, el GGUF se monta en el contenedor desde `models_registry/llm/`.

### Endpoints del servicio LLM

| Endpoint | Método | Descripción |
|---|---|---|
| `/api/llm/generators/stream` | POST | Generación **simulada** (referencia de contrato, fase 1-2) |
| `/api/llm/contents/generations` | POST | Generación **real**: grafo v4 → resumen v6 → llama-server (fase 3) |
| `/api/llm/contents/generations` | GET | Historial paginado de generaciones (filtro por `draftId`) |
| `/api/llm/contents/generations/{id}` | GET | Detalle de una generación por UUID |

### Pipeline de inferencia real (`POST /api/llm/contents/generations`)

```
Draft (JWT) → GraphInferenceService (grafo v4) → Decision editorial
           → build_summary (resumen v6 ~100 tokens)
           → LlamaServerHttpClient (stream SSE OpenAI-compat)
           → ListingStreamParser (deltas de texto limpio al móvil)
           → GenerationRepository (llm_generations en PostgreSQL)
```

Contrato de eventos SSE: `queued*` → `title` → `delta*` → `done` | `error`.
El evento `done` solo contiene `{generationId, title, description}` (mínimo para el móvil).
Todo lo demás (decisión del grafo, tiempos, tokens/s, RAM, versiones) queda en la tabla `llm_generations`.

### Persistencia de generaciones (`llm_generations`)

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | Identificador de la generación |
| `draft_id` | str (index) | ID del draft de origen |
| `title` / `description` | text | Salida del LLM |
| `decision` | JSONB | Decisión completa del grafo (temas, audiencia, scores, traza) |
| `warnings` | JSONB | Alertas detectadas (precio_mencionado, cta_detectada) |
| `graph_ms` / `llm_s` / `duration_s` | float | Tiempos por etapa |
| `prompt_tokens` / `output_tokens` / `tokens_per_second` | int/float | Métricas del LLM |
| `ram_mb` | float | RSS del proceso al finalizar |
| `model_file` / `prompt_version` / `graph_version` | str | Estampas de versión |
| `source` | str | `"http"` (siempre, por ahora) |
| `created_at` | timestamptz | Marca de tiempo del servidor |

