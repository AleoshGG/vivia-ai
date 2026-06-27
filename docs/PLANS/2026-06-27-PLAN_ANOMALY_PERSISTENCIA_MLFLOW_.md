# Plan: Persistencia de inferencias + versionado MLflow (servicio de anomalías)

## Objetivo

Completar los requerimientos faltantes del microservicio de detección de
anomalías: **almacenar cada inferencia en una base de datos** y **exponer un
endpoint para consultarlas**. Adicionalmente, llevar el versionado del modelo a
**MLflow Model Registry** (migración completa de serving).

El servicio ya cubre 5 de los 7 requerimientos: endpoint de inferencia
(`POST /api/anomaly/analyze`), validación y preprocesamiento (Pydantic `Draft` +
`build_features`), algoritmo no supervisado (Isolation Forest), respuesta JSON y
documentación Swagger automática (`/api/anomaly/docs`).

Decisiones confirmadas:
- **BD: PostgreSQL** (la misma instancia sirve de backend-store de MLflow).
- **MLflow: migración completa de serving** (`models:/anomaly/Production`).
- **Contrato de `/analyze` sin cambios**: se persiste la inferencia y se expone
  por endpoints nuevos de consulta; `PropertyAnalysisResponse` queda igual.

## Alcance

**Incluido:**
- Servicio PostgreSQL en `compose.yml` con volumen persistente.
- Capa de persistencia (SQLAlchemy async + asyncpg, migraciones Alembic).
- Repositorio de inferencias siguiendo el patrón Repository de `data_lake/`.
- Escritura de cada inferencia (path HTTP `/analyze` y path de cola RabbitMQ).
- Endpoints `GET /api/anomaly/inferences` (lista paginada/filtrable) y
  `GET /api/anomaly/inferences/{id}` (detalle).
- Migración completa de carga del modelo a MLflow Model Registry
  (implementar `shared/model_loader.py` + script de registro).
- Documentación Swagger de los nuevos endpoints (automática vía Pydantic).

**Excluido:**
- Persistencia/MLflow para `clustering-batch` y `llm-local`.
- Reentrenamiento automático o pipelines de CI de modelos.
- Autenticación distinta a `X-Internal-API-Key` para los endpoints de lectura.
- Dashboards/observabilidad (D6 sigue diferido).

## Cambios por capa

### 1. Infraestructura — `compose.yml`, `.env(.example)`, `config/settings.py`
- Nuevo servicio `postgres` (imagen `postgres:16`), volumen `vivia-pg-data`,
  healthcheck; `anomaly-api` y `mlflow` con `depends_on: postgres`.
- Nuevas variables en `config/settings.py` (`Settings`):
  `database_url` (`postgresql+asyncpg://...`) y credenciales PG.
  Añadir a `.env.example`. Reutiliza el patrón pydantic-settings (D2).
- `mlflow` arranca con `--backend-store-uri postgresql://...` apuntando a la
  misma instancia (cierra el plan de migración MLflow ya documentado).

### 2. Persistencia — nuevo paquete `src/anomaly_detector_api/persistence/`
- `database.py`: `AsyncEngine` + `async_sessionmaker` desde `settings.database_url`.
- `models_db.py`: tabla `anomaly_inferences` (SQLAlchemy ORM):
  `id` (UUID pk), `draft_id`, `is_anomaly` (bool), `score` (float),
  `approved` (bool), `reason` (text), `model_version` (str),
  `source` (`http`|`queue`), `features` (JSONB), `created_at` (timestamptz).
- `inference_repository.py`: `InferenceRepository` con `save(...)`,
  `list(filters, limit, offset)`, `get(id)`. Espeja el ABC `StorageRepository`.
- `alembic/`: configuración + primera migración que crea la tabla.

### 3. Modelos de respuesta — `src/anomaly_detector_api/models/property.py`
- Nuevos schemas de salida: `InferenceRecord` (detalle) e
  `InferenceListResponse` (items + total + paginación). No se toca
  `PropertyAnalysisResponse` (contrato de `/analyze` intacto).

### 4. Use case — `src/anomaly_detector_api/usecases/analyze_property.py`
- Inyectar `InferenceRepository` en `__init__` (junto al `model` existente).
- Tras obtener `is_anomaly, score`, **persistir la inferencia antes del webhook**
  (no debe depender del éxito del callback externo). Guardar `source="http"` y
  el `model_version` que exponga el modelo.
- El mismo cambio aplica al consumidor de cola
  (`messaging/anomaly_queue_consumer.py`) con `source="queue"`.

### 5. Endpoints de consulta — `controllers/anomaly_controller.py` + nuevo use case
- Nuevo `usecases/list_inferences.py` (lógica de lectura, sin lógica en controller, D9).
- `GET /api/anomaly/inferences` con query params (`draft_id`, `is_anomaly`,
  `limit`, `offset`) y `GET /api/anomaly/inferences/{id}`, ambos protegidos con
  `Depends(verify_internal_api_key)`. Documentados vía `response_model`.

### 6. MLflow — migración de serving (integra el plan existente)
- `mlflow.Dockerfile` + `compose.yml`: backend-store Postgres + artifact root GCS.
- Implementar `shared/model_loader.py::ModelLoader.load_model()` real
  (`mlflow.set_tracking_uri` + `mlflow.pyfunc.load_model("models:/anomaly/Production")`).
- `scripts/register_anomaly_model.py`: empaqueta modelo+scaler+threshold+columnas
  como una versión `pyfunc` y la promueve a `Production`.
- Reescribir `AnomalyModel.load()` para usar `ModelLoader` en vez de `joblib`;
  exponer `model_version` (lo consume la persistencia). `main.py` conecta el
  engine de BD al lifespan y pasa el repo a los use cases.

## Dependencias
- Nuevas libs en `src/anomaly_detector_api/requirements.txt`:
  `sqlalchemy[asyncio]>=2.0`, `asyncpg>=0.29`, `alembic>=1.13`.
- `mlflow` ya está en `pyproject.toml`.
- Servicio `postgres` operativo y `mlflow` con persistencia (backend + artifacts GCS).
- Cierra el plan `2026-06-27-PLAN_MIGRACION_MLFLOW_MODEL_REGISTRY_.md`.

## Observación encontrada (a confirmar en implementación)
`controllers/anomaly_controller.py:33` instancia `AnalyzePropertyUseCase()` sin
argumentos, pero `AnalyzePropertyUseCase.__init__` exige `model`
(`usecases/analyze_property.py:19`). Hay un desajuste; al inyectar el repo se
debe pasar también el `model` desde `app.state.anomaly_model`. Verificar/corregir.

## Pasos de implementación
1. Añadir servicio `postgres` + volumen a `compose.yml`; variables PG en
   `settings.py` y `.env.example`.
2. Crear paquete `persistence/` (engine, ORM `anomaly_inferences`, repositorio)
   y configurar Alembic + primera migración.
3. Añadir schemas `InferenceRecord` / `InferenceListResponse`.
4. Conectar el engine de BD en el `lifespan` de `main.py` y exponer el repo.
5. Persistir la inferencia en `analyze_property.py` y en el consumidor de cola.
6. Crear `list_inferences.py` y los endpoints `GET /inferences` y `/inferences/{id}`.
7. MLflow: backend Postgres + artifacts GCS, implementar `ModelLoader`, correr
   `register_anomaly_model.py`, promover a `Production`, reescribir
   `AnomalyModel.load()` y exponer `model_version`.
8. Verificar end-to-end y retirar el volumen `models_registry` del compose.

## Verificación
- `docker compose up postgres mlflow anomaly-api` arranca sin errores; Postgres
  pasa healthcheck y `anomaly-api` carga el modelo desde `models:/anomaly/Production`.
- `alembic upgrade head` crea la tabla `anomaly_inferences`.
- `POST /api/anomaly/analyze` (con `X-Internal-API-Key`) → responde el JSON
  habitual; `SELECT * FROM anomaly_inferences` muestra la fila con `score`,
  `is_anomaly` y `model_version`.
- Publicar un mensaje en la cola RabbitMQ → fila con `source="queue"`.
- `GET /api/anomaly/inferences?limit=10` y `GET /api/anomaly/inferences/{id}`
  devuelven los registros; aparecen documentados en `/api/anomaly/docs` (Swagger).
- Tests de integración en `tests/integration/test_anomaly_api.py` ampliados para
  cubrir persistencia y los endpoints de consulta.
