# Plan: Migración del modelo de anomalías a MLflow Model Registry

## Objetivo
Reemplazar la carga de modelos desde archivos locales (`models_registry/anomaly/`)
por el **Model Registry de MLflow**, para tener versionado, stages
(Staging/Production) y trazabilidad de los modelos en lugar de gestionar los
artefactos `.joblib` a mano.

> Estado actual (Camino A, ya implementado): el contenedor `anomaly-api` carga
> el modelo desde un volumen persistente del VPS (`MODELS_REGISTRY_HOST`), y los
> artefactos se suben con `infrastructure/cloud_deploy/push_models.sh`. Este plan
> describe el siguiente paso, no algo urgente.

## Alcance
**Incluido:**
- Configurar el servidor MLflow con backend store y artifact store persistentes.
- Implementar `shared/model_loader.py::ModelLoader` (hoy es un stub).
- Adaptar `AnomalyModel` para cargar desde `models:/anomaly/Production`.
- Script para registrar el modelo entrenado en el registry.

**Excluido:**
- Migrar los servicios `clustering-batch` y `llm-local` (lo cargan después).
- Reentrenamiento automático / pipelines de CI de modelos.

## Cambios por capa

### Infraestructura (`infrastructure/docker/mlflow.Dockerfile` + `compose.yml`)
- Arrancar el servidor con backend store y artifact destination explícitos:
  ```
  mlflow server --host 0.0.0.0 --port 5000 \
    --backend-store-uri sqlite:////mlflow/mlflow.db \
    --artifacts-destination ${MLFLOW_ARTIFACT_ROOT}
  ```
  (para producción seria, sustituir SQLite por Postgres).
- Montar un volumen persistente para el backend store (`/mlflow`).
- Montar las credenciales de GCS y exportar `GOOGLE_APPLICATION_CREDENTIALS`
  para que MLflow escriba en `gs://vivia-ai-data-lake/mlflow-artifacts`.

### Carga del modelo (`shared/model_loader.py`)
- Implementar `load_model(model_name, stage)` con
  `mlflow.set_tracking_uri(settings.mlflow_tracking_uri)` +
  `mlflow.pyfunc.load_model(f"models:/{model_name}/{stage}")`.

### Servicio (`src/anomaly_detector_api/services/anomaly_model.py` + `main.py`)
- Reescribir `AnomalyModel.load()` para usar `ModelLoader` en vez de leer
  `*.joblib` del disco. Decidir cómo empaquetar scaler + threshold + columnas
  (modelo `pyfunc` custom o artefactos asociados a la versión).

### Registro del modelo (nuevo: `scripts/register_anomaly_model.py`)
- Cargar los artefactos actuales y registrarlos como versión en el registry,
  promoviéndola a stage `Production`.

## Dependencias
- Servicio `mlflow` operativo con persistencia (backend + artifacts).
- Credenciales de GCS disponibles en el contenedor de MLflow.
- Variables ya existentes: `MLFLOW_TRACKING_URI`, `MLFLOW_ARTIFACT_ROOT`.

## Pasos de implementación
1. Añadir backend store + artifact destination y volumen persistente al servicio MLflow.
2. Montar credenciales GCS y validar que MLflow escribe artefactos en el bucket.
3. Implementar `ModelLoader.load_model`.
4. Escribir y correr `scripts/register_anomaly_model.py` para subir el modelo actual.
5. Promover la versión a `Production` en el registry.
6. Adaptar `AnomalyModel.load()` para cargar desde MLflow.
7. Probar `anomaly-api` end-to-end y, una vez estable, retirar el volumen de
   `models_registry` del `compose.yml`.
