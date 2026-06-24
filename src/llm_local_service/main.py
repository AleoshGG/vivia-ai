from fastapi import FastAPI
from contextlib import asynccontextmanager
from .controllers import llm_controller
from shared.health import router as health_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup inicial
    yield
    # Teardown

app = FastAPI(
    title="LLM Local Service",
    description="Microservicio para inferencia con LLM local.",
    version="0.1.0",
    lifespan=lifespan
)

# Incluir routers
app.include_router(health_router, prefix="/api/llm", tags=["health"])
app.include_router(llm_controller.router, prefix="/api/llm", tags=["llm"])
