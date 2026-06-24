from fastapi import FastAPI
from contextlib import asynccontextmanager
from .controllers import cluster_controller
from shared.health import router as health_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup inicial (ej: cargar modelo desde MLflow, conectar RabbitMQ)
    yield
    # Teardown (ej: cerrar conexiones)

app = FastAPI(
    title="Clustering Batch Service",
    description="Microservicio de IA para clustering batch.",
    version="0.1.0",
    lifespan=lifespan
)

# Incluir routers
app.include_router(health_router, prefix="/api/clustering", tags=["health"])
app.include_router(cluster_controller.router, prefix="/api/clustering", tags=["clustering"])
