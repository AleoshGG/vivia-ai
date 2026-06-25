# Plan: Endpoint de Análisis de Propiedad (Simulado)

## Objetivo
Crear un endpoint POST dentro de `src/anomaly_detector_api/` que reciba un JSON simulando la publicación de una propiedad inmobiliaria, simule un análisis con un delay asíncrono de 2 segundos, y luego haga una petición HTTP autenticada a un endpoint externo enviando un payload estructurado con el resultado del análisis.

El propósito es **verificar el flujo HTTP completo** del microservicio sin involucrar RabbitMQ, workers ni orquestación.

## Alcance

### Incluido
- Modelo Pydantic para el request (datos de propiedad + `draftId` obligatorio)
- Modelo Pydantic para el payload de salida hacia el servicio externo (`draftId`, `approved`, `reason`)
- Modelo Pydantic para el response del endpoint
- Endpoint `POST /analyze` en el controller de anomaly
- UseCase que orqueste: delay de 2s → llamada HTTP externa autenticada
- Cliente HTTP asíncrono (`httpx.AsyncClient`) con header `X-Internal-API-Key` en la petición saliente
- URL del endpoint externo en `config/settings.py`, leída desde `.env`

### Excluido
- RabbitMQ, colas, workers, QueuePublisher
- Persistencia en Data Lake / GCS
- Modelos de ML reales o MLflow
- Tests (se harán después si se requiere)

## Cambios por capa

### Config (`config/settings.py`)
- **Modificar**: Agregar campo `external_service_url: str` a la clase `Settings`
  - Se lee desde la variable de entorno `EXTERNAL_SERVICE_URL` vía `.env`
  - Es la URL base del servicio externo al que se hace POST tras el análisis

### Models (`src/anomaly_detector_api/models/`)
- **Nuevo archivo**: `property.py`
  - `PropertyRequest` — modelo Pydantic de entrada con:
    - `draftId: str` (obligatorio — identificador del borrador de propiedad)
    - `title: str` (título de la propiedad)
    - `price: float` (precio)
    - `location: str` (ubicación)
    - `description: Optional[str]` (descripción opcional)
  - `AnalysisPayload` — modelo Pydantic del payload que se envía al servicio externo:
    - `draftId: str` (el mismo que llegó en el request)
    - `approved: bool` (resultado del análisis simulado)
    - `reason: str` (motivo de aprobación/rechazo)
  - `PropertyAnalysisResponse` — modelo Pydantic para el response del endpoint:
    - `status: str` (ej: "completed")
    - `draftId: str`
    - `approved: bool`
    - `reason: str`
    - `external_status_code: int` (código HTTP que devolvió el servicio externo)

### UseCases (`src/anomaly_detector_api/usecases/`)
- **Nuevo archivo**: `analyze_property.py`
  - `AnalyzePropertyUseCase` — clase con método asíncrono `execute()` que:
    1. Recibe los datos de la propiedad (incluyendo `draftId`)
    2. Hace `await asyncio.sleep(2)` para simular análisis
    3. Construye el `AnalysisPayload` con `draftId`, `approved=True`, y un `reason` descriptivo
    4. Lee `settings.external_service_url` para la URL destino
    5. Lee `settings.internal_api_key` para el header de autenticación
    6. Usa `httpx.AsyncClient` para hacer POST al endpoint externo con:
       - Body: `AnalysisPayload` serializado como JSON
       - Header: `X-Internal-API-Key: <settings.internal_api_key>`
    7. Retorna el resultado con el status code de la respuesta externa

### Controllers (`src/anomaly_detector_api/controllers/`)
- **Modificar**: `anomaly_controller.py`
  - Agregar endpoint `POST /analyze` con dependencia de `verify_internal_api_key`
  - Request body: `PropertyRequest`
  - Response model: `PropertyAnalysisResponse`
  - Documentado con modelos Pydantic para Swagger automático

## Dependencias

- **httpx** — cliente HTTP asíncrono para la petición al endpoint externo. Agregar a `requirements.txt`.
- **asyncio** — incluido en Python estándar.
- No se toca RabbitMQ ni ningún otro servicio.

## Pasos de implementación

1. Confirmar con el usuario la **ruta exacta del endpoint externo** (se anexará a `external_service_url`)
2. Agregar `external_service_url` a `config/settings.py`
3. Verificar/agregar `httpx` en las dependencias del proyecto
4. Crear `src/anomaly_detector_api/models/property.py` con los 3 modelos Pydantic
5. Crear `src/anomaly_detector_api/usecases/analyze_property.py` con el use case asíncrono
6. Modificar `src/anomaly_detector_api/controllers/anomaly_controller.py` para agregar `POST /analyze`
7. Levantar el microservicio y probar desde Swagger (`/docs`)

## Notas

- El delay de 2 segundos usa `asyncio.sleep()` (no `time.sleep()`) para no bloquear el event loop de FastAPI
- La URL del servicio externo se configura en `config/settings.py` y se lee desde `.env` — nunca hardcodeada en el use case
- La petición saliente incluye el header `X-Internal-API-Key` con la misma clave de `settings.internal_api_key`
- Este endpoint es independiente del flujo existente de `POST /detect` — no lo modifica ni lo afecta
- **Pendiente**: la ruta exacta del endpoint externo (el usuario la proporcionará antes de la implementación)
