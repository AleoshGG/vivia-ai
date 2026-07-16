# Plan: LLM Local Service — Fase 2: versionado de artefactos (MLflow + GCS) y llama-server dockerizado

## Objetivo

La fase 1 (streaming SSE simulado + cola + JWT, `2026-07-15-PLAN_LLM_STREAMING_SIMULADO_.md`) ya está implementada. Antes de enchufar la inferencia real hay que dejar listos dos cimientos:

1. **Versionar** el grafo ponderado, el modelo LLM y el prompt que se usarán, para que cada inferencia sea reproducible y rastreable (mismo patrón que anomalías con MLflow), con **todos los artefactos respaldados en el bucket de GCS** (nada vive solo en disco local).
2. **Dockerizar llama-server** con 4 threads, para que el backend de inferencia exista como servicio del compose.

**Stack decidido:** Qwen3-1.7B-Q4_K_M en modo no-thinking + **prompt v6** (`notebooks/graph-ai/prompt.py`, `SYSTEM_PROMPT_V6`) + **grafo ponderado v4** (`notebooks/graph-ai/datasets/`). Esto actualiza al plan maestro (`2026-07-15-PLAN_LLM_GENERATORS_SERVICE_.md`, que decía Qwen3-4B + v4): los benchmarks más recientes (`benchmark_qwen17b_v6_par1_*.csv`) validaron 1.7B + v6 a ~10-14 tok/s.

**Orden de los puntos** (B depende de saber QUÉ artefactos se sirven; A fija eso):

- **A. Versionado** — A1) copiar grafo y prompt a su casa de producción en el servicio; A2) script de subida del GGUF al bucket de GCS; A3) script idempotente de registro en MLflow.
- **B. Dockerización** — B1) servicio `llama-server` en compose (4 threads); B2) cablear `llm-local` para conocerlo (depends_on + URL).

## Alcance

**Incluido**
1. Copia de los artefactos del grafo (CSVs) y el prompt v6 a `src/llm_local_service/resources/` (producción nunca importa desde `notebooks/`).
2. `scripts/upload_llm_model.py`: sube el GGUF al bucket de GCS (`vivia-ai-data-lake`). Idempotente.
3. `scripts/register_llm_generator.py`: registra `llm-listing-generator` en MLflow con los artefactos + metadata (hash y URI gs:// del GGUF) y promueve a `Production`. Idempotente. Los artefactos de MLflow ya aterrizan en el bucket vía `MLFLOW_ARTIFACT_ROOT=gs://vivia-ai-data-lake/mlflow-artifacts` — con esto **todo** queda respaldado en GCS.
4. Servicio `llama-server` en `compose.yml` (imagen oficial, `--threads 4`, healthcheck) y `depends_on` + `LLAMA_SERVER_URL` en `llm-local`.
5. Settings nuevos en `config/settings.py` y `.env.example`.

**Excluido (fases siguientes)**
- Cliente real a llama-server (`LlmClient` HTTP que reemplace a `SimulatedLlmClient`), motor de grafo como código del servicio, parseo de salida.
- Persistencia/historial, nginx, deploy real al VPS.
- Subir el GGUF (~1 GB) como artefacto *de MLflow* (pasaría dos veces por la red y duplicaría el objeto en el bucket): el binario se sube UNA vez directo al bucket con `upload_llm_model.py` y MLflow lo referencia por URI gs:// + hash sha256. Para servir, sigue montado desde `models_registry/llm/`.

## Cambios por capa

### A1. Recursos de producción — `src/llm_local_service/resources/` (nuevo)

- `resources/graph/` — copia de los 10 CSVs de `notebooks/graph-ai/datasets/` (`amenidades`, `audiencias`, `bloqueos`, `buckets`, `operaciones`, `pesos_evoca`, `pesos_priors`, `reglas_audiencia`, `temas`, `tipos_propiedad`) + `README.md` explicando el flujo de sincronización notebook → producción → MLflow. NO se copian `drafts_ejemplo.json` ni artefactos de benchmark.
- `resources/prompts/system_prompt_v6.txt` — el texto de `SYSTEM_PROMPT_V6` extraído de `notebooks/graph-ai/prompt.py`.
- `resources/prompts/output_schema.json` — JSON-schema del contrato de salida del anuncio (`{"titulo", "descripcion"}`). Nota: en v6 el server NO fuerza gramática; el contrato se pide por prompt y se valida al parsear — el schema es el contrato documentado/versionado.

### A2. Subida del GGUF al bucket — `scripts/upload_llm_model.py` (nuevo)

Sube `models_registry/llm/Qwen3-1.7B-Q4_K_M.gguf` a `gs://{settings.gcs_bucket_name}/models_registry/llm/Qwen3-1.7B-Q4_K_M.gguf`, reutilizando `data_lake/gcs_repository.py` (`GCSRepository`).

- **Idempotente**: si `exists(key)` regresa `True`, no re-sube; `FORCE_UPLOAD=1` fuerza re-subida.
- Calcula el `sha256` local antes de subir y lo imprime — el mismo hash que estampa el registro en MLflow.
- Uso: `python -m scripts.upload_llm_model`.

### A3. Registro en MLflow — `scripts/register_llm_generator.py` (nuevo)

Espejo idempotente de `scripts/register_anomaly_model.py`: `_wait_for_mlflow` con reintentos, guard de versión en `Production` + `FORCE_REGISTER=1`, registro + `transition_model_version_stage(..., archive_existing_versions=True)`.

- Modelo registrado: **`llm-listing-generator`** (experimento `llm-generation`).
- Artefactos: CSVs de `resources/graph/`, `system_prompt_v6.txt`, `output_schema.json` y un `metadata.json` generado por el script con: nombre y quant del GGUF, `sha256`, `gguf_gcs_uri`, `prompt_version: "v6"`, `graph_version: "v4"`, y parámetros de servicio/inferencia (`threads: 4`, `ctx_size: 4096`, `parallel: 1`, `enable_thinking: false`, `temperature: 1.0`, `top_p: 0.8`, `top_k: 20`, `max_tokens: 512`).
- Antes de registrar **verifica que el GGUF ya esté en el bucket** (`GCSRepository.exists`); si no está, falla indicando correr `upload_llm_model` primero.
- Sin `python_model` ejecutable (el modelo corre en llama-server): `mlflow.log_artifacts` + `mlflow.register_model` sobre el run.

### A4. Config — `config/settings.py` (sección LLM Local Service)

- `llm_model_name: str = "llm-listing-generator"`, `llm_model_stage: str = "Production"`.
- `llm_gguf_file: str = "Qwen3-1.7B-Q4_K_M.gguf"`.
- `llama_server_url: str = "http://localhost:8080"` (en compose: `http://llama-server:8080`).
- Agregar `LLAMA_SERVER_URL` a `.env.example`.

### B1. compose.yml — servicio `llama-server` (nuevo)

- Imagen oficial `ghcr.io/ggml-org/llama.cpp` con tag **pineado** a la release del binario validado localmente (`server-b10015`, ver `notebooks/graph-ai/tools/`).
- `container_name: vivia-llama-server`; volumen `${MODELS_REGISTRY_HOST:-./models_registry}:/models:ro`.
- Comando: `-m /models/llm/Qwen3-1.7B-Q4_K_M.gguf --host 0.0.0.0 --port 8080 --threads 4 --ctx-size 4096 --parallel 1 --chat-template-kwargs '{"enable_thinking": false}'` (valores de los benchmarks; **4 threads** requerido).
- `healthcheck` contra `GET /health`; red `vivia_network`.

### B2. compose.yml — servicio `llm-local` (ajustar)

- `depends_on: llama-server: condition: service_healthy`.
- `environment: LLAMA_SERVER_URL=http://llama-server:8080`.
- El Dockerfile de `llm-local` no cambia (la copia de `src/llm_local_service/` ya arrastra `resources/`).

## Dependencias

- MLflow y su backend ya en compose (`vivia-mlflow`); GGUF ya presente en `models_registry/llm/`.
- GCS: bucket `vivia-ai-data-lake` y credencial del service account (la misma que usa MLflow); se reutiliza `GCSRepository` sin cambios.
- Fuentes de copia validadas: `notebooks/graph-ai/datasets/` (grafo v4) y `notebooks/graph-ai/prompt.py` (v6).
- No toca anomalías, clustering, ni el flujo SSE simulado vigente.

## Pasos de implementación

1. Crear este plan en `docs/PLANS/`.
2. **A1** — Copiar CSVs del grafo a `resources/graph/` + README; extraer prompt v6 y schema a `resources/prompts/`.
3. **A4** — Settings nuevos y `.env.example`.
4. **A2** — `scripts/upload_llm_model.py` (GGUF → bucket GCS, idempotente, sha256).
5. **A3** — `scripts/register_llm_generator.py` (idempotente, metadata con sha256 + URI gs:// del GGUF, verifica el bucket).
6. **B1** — Servicio `llama-server` en `compose.yml`.
7. **B2** — Ajustar `llm-local` (depends_on + `LLAMA_SERVER_URL`).
8. Actualizar `docs/contexto/arquitectura.md` (stack 1.7B + v6, llama-server como contenedor, GGUF respaldado en GCS).
