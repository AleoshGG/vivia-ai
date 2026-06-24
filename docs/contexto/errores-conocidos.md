# Errores Conocidos / Gotchas — Vivia AI

> No hay código en el repo todavía, así que no hay errores detectados empíricamente. Los siguientes son riesgos anticipados basados en las decisiones de arquitectura.

## Riesgos Anticipados

### 1. Credenciales de GCS en desarrollo
El `GCS_CREDENTIALS_PATH` apunta a un archivo JSON de service account. Si este archivo no existe o la variable no está seteada, el servicio fallará al arrancar.
- **Mitigación planeada**: `LocalRepository` como fallback en `ENVIRONMENT=development`.

### 2. RabbitMQ no disponible al arrancar servicios
Si RabbitMQ tarda en iniciar y un servicio intenta conectarse antes, habrá connection refused.
- **Mitigación planeada**: `depends_on` en docker-compose + retry logic en `queue_consumer.py`.

### 3. `.env` no debe ir al repo
El `.gitignore` actual no incluye `.env`. Si se commitea, se filtran secretos.
- **Mitigación**: Agregar `.env` al `.gitignore` durante el scaffolding.

### 4. MLflow artifact storage
Si `MLFLOW_ARTIFACT_ROOT` apunta a GCS (`gs://...`) pero no hay credenciales configuradas para MLflow, el tracking server no podrá guardar artefactos.
- **Mitigación planeada**: En desarrollo usar artifact root local (`./mlruns`).

[PENDIENTE: gotchas reales se documentarán conforme aparezcan durante el desarrollo.]
