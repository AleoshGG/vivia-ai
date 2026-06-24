# Convenciones — Vivia AI

## Estilo de Código

[PENDIENTE: no hay código en el repo todavía. Definir linter (ruff/flake8), formatter (black/ruff), y reglas específicas cuando se escriba el primer archivo Python.]

## Naming

| Elemento | Convención | Ejemplo |
|----------|-----------|---------|
| Archivos Python | snake_case | `anomaly_controller.py` |
| Clases | PascalCase | `DetectAnomalyUseCase` |
| Funciones / métodos | snake_case | `detect_anomaly()` |
| Variables de entorno | UPPER_SNAKE_CASE | `INTERNAL_API_KEY` |
| Carpetas de servicios | snake_case con guiones bajos | `anomaly_detector_api/` |

[PENDIENTE: convenciones para nombres de queues en RabbitMQ, nombres de modelos en MLflow, keys en GCS.]

## Patrones que Usamos

| Patrón | Dónde | Propósito |
|--------|-------|-----------|
| **Repository** | `data_lake/` | Abstraer el proveedor de almacenamiento (GCS hoy, otro mañana) |
| **MVC + Use Cases** | `src/<servicio>/` | Separar HTTP (controllers) de lógica (usecases) de datos (models) |
| **App Factory** | `src/<servicio>/main.py` | Crear la instancia FastAPI con toda su configuración |
| **Middleware** | `shared/auth_middleware.py` | Validación transversal (auth) sin repetir en cada endpoint |
| **Producer/Consumer** | `shared/queue_*.py` | Desacoplar recepción de peticiones de su procesamiento |

## Patrones Prohibidos

| Prohibido | Motivo |
|-----------|--------|
| Lógica de negocio en controllers | Los controllers solo parsean requests y delegan a use cases |
| Import directo de `google.cloud.storage` fuera de `data_lake/` | Todo acceso al Data Lake pasa por `StorageRepository` |
| Hardcodear credenciales o URLs | Todo va en `.env` y se carga con `pydantic-settings` |
| Llamadas a APIs de terceros para LLM | El LLM es local, cero dependencias externas |

## Tests

[PENDIENTE: no hay tests en el repo. Se planea usar pytest con la estructura `tests/unit/` + `tests/integration/` + `tests/fixtures/`.]

## Commits

[PENDIENTE: no hay historial de commits significativo. Definir convención (conventional commits, etc.) cuando se empiece a desarrollar.]
