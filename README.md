# Vivia AI - Ecosistema de ML No Supervisado

Este repositorio contiene la arquitectura de microservicios para los modelos de Machine Learning no supervisado de Vivia AI.

## Arquitectura

El ecosistema consta de:
- **Anomaly Detector API**: Servicio en tiempo real.
- **Clustering Batch Service**: Servicio de procesamiento asíncrono.
- **LLM Local Service**: Servicio de inferencia LLM local.

## Stack Tecnológico
- Python 3.12
- FastAPI
- RabbitMQ
- Google Cloud Storage (Data Lake)
- MLflow (Model Registry)
- Docker & Docker Compose

## Desarrollo Local

1. Copiar `.env.example` a `.env` y configurar variables.
2. Levantar la infraestructura base con Docker Compose:

```bash
make dev
```

Para ejecutar pruebas:

```bash
make test
```

Ver la carpeta `docs/contexto/` para más detalles sobre la arquitectura y decisiones de diseño.
