import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .controllers import anomaly_controller
from .messaging.anomaly_queue_consumer import AnomalyQueueConsumer
from shared.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    consumer = AnomalyQueueConsumer()
    thread = threading.Thread(target=consumer.run, daemon=True, name="anomaly-queue-consumer")
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

# Incluir routers
app.include_router(health_router, prefix="/api/anomaly", tags=["health"])
app.include_router(anomaly_controller.router, prefix="/api/anomaly", tags=["anomaly"])
