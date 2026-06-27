import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from config.settings import settings
from .controllers import anomaly_controller
from .messaging.anomaly_queue_consumer import AnomalyQueueConsumer
from .services.anomaly_model import AnomalyModel
from shared.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    model = AnomalyModel(Path(settings.model_registry_path) / 'anomaly')
    model.load()
    app.state.anomaly_model = model

    consumer = AnomalyQueueConsumer(model=model)
    thread   = threading.Thread(target=consumer.run, daemon=True, name="anomaly-queue-consumer")
    thread.start()
    yield
    consumer.stop()


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
