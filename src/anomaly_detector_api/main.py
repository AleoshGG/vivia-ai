import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import settings
from .controllers import anomaly_controller
from .messaging.anomaly_queue_consumer import AnomalyQueueConsumer
from .persistence.database import build_engine, build_session_factory, init_models
from .persistence.inference_repository import InferenceRepository
from .services.anomaly_model import AnomalyModel
from shared.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Base de datos: engine + repositorio de inferencias
    engine          = build_engine()
    session_factory = build_session_factory(engine)
    await init_models(engine)
    repository = InferenceRepository(session_factory)
    app.state.db_engine            = engine
    app.state.inference_repository = repository

    # Modelo desde el Model Registry de MLflow
    model = AnomalyModel(settings.anomaly_model_name, settings.anomaly_model_stage)
    model.load()
    app.state.anomaly_model = model

    # Consumidor de la cola de RabbitMQ
    consumer = AnomalyQueueConsumer(model=model, repository=repository)
    thread   = threading.Thread(target=consumer.run, daemon=True, name="anomaly-queue-consumer")
    thread.start()
    yield
    consumer.stop()
    await engine.dispose()


app = FastAPI(
    title="Anomaly Detector API",
    description="Microservicio de IA para detección de anomalías.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/anomaly/docs",
    openapi_url="/api/anomaly/openapi.json",
)

app.include_router(health_router, prefix="/api/anomaly", tags=["health"])
app.include_router(anomaly_controller.router, prefix="/api/anomaly", tags=["anomaly"])
