# Glosario — Vivia AI

## Términos del Dominio

| Término | Definición |
|---------|-----------|
| **Vivia** | Ecosistema de software al que pertenece este proyecto de IA |
| **Data Lake** | Almacenamiento centralizado de datos crudos y procesados (actualmente GCS) |
| **Anomaly Detection** | Técnica de ML no supervisado para detectar patrones inusuales en datos |
| **Clustering** | Técnica de ML no supervisado para agrupar datos en clusters por similitud |
| **Batch Processing** | Procesamiento de datos en lotes, no en tiempo real |

## Entidades Principales

[PENDIENTE: no hay modelos de dominio definidos en código. Se definirán cuando se implementen los Pydantic models en `src/<servicio>/models/`.]

## Componentes del Sistema

| Componente | Rol |
|-----------|-----|
| **API Transaccional** | Servicio externo de Vivia que llama a los microservicios de IA vía webhook |
| **Anomaly Detector API** | Microservicio FastAPI para detección de anomalías |
| **Clustering Batch Service** | Microservicio FastAPI para agrupamiento por lotes |
| **LLM Local Service** | Microservicio FastAPI para inferencia con LLM local |
| **StorageRepository** | Interfaz abstracta para acceso al Data Lake |
| **Model Loader** | Componente shared que descarga modelos desde MLflow |

## Siglas Internas

| Sigla | Significado |
|-------|------------|
| **GCS** | Google Cloud Storage |
| **RMQ** | RabbitMQ |
| **MVC** | Model–View–Controller (adaptado: Model–Controller–UseCase) |
| **DTO** | Data Transfer Object (los Pydantic models de request/response) |
| **ACK** | Acknowledgment (confirmación de procesamiento de mensaje en RabbitMQ) |
| **DLQ** | Dead-Letter Queue (cola de mensajes fallidos en RabbitMQ) |

[PENDIENTE: siglas o términos específicos del negocio de Vivia que aún no se conocen.]
