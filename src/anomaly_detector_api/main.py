from fastapi import FastAPI
from contextlib import asynccontextmanager
from .controllers import anomaly_controller
from shared.health import router as health_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup inicial (ej: cargar modelo desde MLflow, conectar RabbitMQ)
    yield
    # Teardown (ej: cerrar conexiones)

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
