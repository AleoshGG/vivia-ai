# Arquitectura — Vivia AI

## Stack Tecnológico

| Capa | Tecnología | Versión / Nota |
|------|-----------|----------------|
| Lenguaje | Python | 3.12 |
| Framework HTTP | FastAPI | — |
| Cola de mensajes | RabbitMQ | Persistencia + ACK |
| Data Lake | Google Cloud Storage | Abstracción vía patrón Repository |
| Model Registry | MLflow | Integración progresiva |
| LLM | Local (sin APIs externas) | Microservicio separado |
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

## Qué NO Existe Todavía

- ❌ No hay código fuente — el repo solo tiene `.gitignore` y archivos de configuración de IDE
- ❌ No hay modelos de ML entrenados
- ❌ No hay Dockerfiles ni docker-compose
- ❌ No hay tests
- ❌ No hay notebooks de experimentación
- ❌ No hay configuración de CI/CD
- ❌ No hay integración con GCS ni MLflow
- ❌ No hay configuración de RabbitMQ
