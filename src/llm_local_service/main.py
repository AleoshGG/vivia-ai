from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import settings
from shared.health import router as health_router
from .controllers import llm_controller
from .services.llm_client import SimulatedLlmClient
from .services.request_queue import RequestQueue


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Backend de generación (simulado en esta fase) y cola de espera compartida.
    client = SimulatedLlmClient(delay_s=settings.llm_simulated_delay_s)
    app.state.llm_client = client
    app.state.request_queue = RequestQueue(
        max_concurrent=settings.llm_max_concurrent,
        max_queue_size=settings.llm_max_queue_size,
    )
    yield
    await client.close()


app = FastAPI(
    title="LLM Local Service",
    description=(
        "Microservicio de generación de anuncios con LLM local. "
        "Responde por streaming SSE directo al cliente móvil y autentica con JWT."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/llm/docs",
    openapi_url="/api/llm/openapi.json",
)

app.include_router(health_router, prefix="/api/llm", tags=["health"])
app.include_router(llm_controller.router, prefix="/api/llm", tags=["generators"])
