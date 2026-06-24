# Decisiones Técnicas — Vivia AI

Decisiones tomadas durante la fase de planificación arquitectónica. No hay código aún, por lo que todas provienen de conversaciones de diseño.

## D1: Proveedor de almacenamiento → Google Cloud Storage

- **Decidido**: GCS como Data Lake.
- **Por qué**: Es el proveedor cloud que se prevé usar para el ecosistema.
- **Descartado**: AWS S3, Azure Blob, MinIO.
- **Mitigación**: Se usa patrón Repository (`StorageRepository` ABC) para no depender del proveedor. Cambiar a S3 = crear una nueva clase, sin tocar servicios.

## D2: Gestión de configuración → `.env` + pydantic-settings

- **Decidido**: Archivo `.env` leído por `pydantic-settings`.
- **Por qué**: Simple, estándar en el ecosistema Python/FastAPI, compatible con Docker.
- **Descartado**: HashiCorp Vault, AWS SSM, GCP Secret Manager.

## D3: Model Registry → MLflow

- **Decidido**: MLflow para tracking de experimentos y registro de modelos.
- **Por qué**: Open source, estándar de la industria, buena integración con Python.
- **Descartado**: Weights & Biases, S3 simple con convención de nombres.
- **Nota**: Integración progresiva en 4 fases (setup → tracking → registry → serving).

## D4: Comunicación inter-servicios → Pendiente

- **Decidido**: Diferir la decisión.
- **Por qué**: No se necesita comunicación entre servicios en el MVP.

## D5: LLM → Local, sin APIs externas

- **Decidido**: LLM local como microservicio separado expuesto con FastAPI.
- **Por qué**: Cero dependencia de terceros, control total de costos y latencia.
- **Descartado**: OpenAI API, Anthropic API, cualquier servicio SaaS.

## D6: Observabilidad → Pendiente

- **Decidido**: Diferir la decisión.
- **Por qué**: No se trabaja de lleno en modelos ML todavía.

## D7: Autenticación → INTERNAL_API_KEY + RabbitMQ

- **Decidido**: Header `X-Internal-API-Key` validado por middleware. Cola con RabbitMQ.
- **Por qué**: Los servicios NO se exponen a clientes finales, solo los llama una API transaccional vía webhook. RabbitMQ garantiza que ninguna petición se pierda.
- **Descartado**: JWT, mTLS, OAuth. También se descartó Redis como capa adicional de cola (RabbitMQ basta por sí solo con persistencia + ACK + dead-letter queues).

## D8: Versión de Python → 3.12

- **Decidido**: Python 3.12.
- **Por qué**: Requerimiento explícito.
- **Descartado**: 3.11, 3.13.

## D9: Estructura interna de servicios → MVC + Use Cases

- **Decidido**: Cada servicio tiene `models/`, `exceptions/`, `controllers/`, `usecases/`, `main.py`.
- **Por qué**: Separación clara de responsabilidades. Controllers no contienen lógica de negocio.
- **Descartado**: Flat structure (todo en `main.py`), Domain-Driven Design completo (overengineering para el alcance actual).
