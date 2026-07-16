import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import settings
from shared.health import router as health_router
from .controllers import llm_controller
from .persistence.database import build_engine, build_session_factory, init_models
from .persistence.generation_repository import GenerationRepository
from .services.graph_inference import GraphInferenceService
from .services.graph_loader import load_domain
from .services.llm_client import LlamaServerHttpClient, SimulatedLlmClient
from .services.request_queue import RequestQueue
from .services.summary_builder import load_system_prompt

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 1. Cola compartida ────────────────────────────────────────────────────
    app.state.request_queue = RequestQueue(
        max_concurrent=settings.llm_max_concurrent,
        max_queue_size=settings.llm_max_queue_size,
    )

    # ── 2. Backend simulado (endpoint legacy /generators/stream) ──────────────
    simulated = SimulatedLlmClient(delay_s=settings.llm_simulated_delay_s)
    app.state.llm_client = simulated

    # ── 3. Grafo ponderado v4 ─────────────────────────────────────────────────
    resources_path = settings.graph_resources_path
    domain = load_domain(resources_path / "graph")
    app.state.graph_domain = domain
    app.state.graph_inference = GraphInferenceService(domain)
    logger.info(
        "Dominio del grafo cargado: %d amenidades, %d temas.",
        len(domain.amenities),
        len(domain.themes),
    )

    # ── 4. System prompt v6 ───────────────────────────────────────────────────
    system_prompt = load_system_prompt(resources_path)

    # ── 5. Cliente real a llama-server ────────────────────────────────────────
    llama_client = LlamaServerHttpClient(
        base_url=settings.llama_server_url,
        system_prompt=system_prompt,
        temperature=settings.llm_temperature,
        top_p=settings.llm_top_p,
        top_k=settings.llm_top_k,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_request_timeout,
    )
    app.state.llama_client = llama_client
    app.state.llm_model_file = settings.llm_gguf_file

    ready = await llama_client.wait_until_ready(retries=15, delay=2.0)
    if not ready:
        # Tolerante: el servicio arranca igual; las peticiones responderán 503
        # con evento SSE `error` hasta que llama-server esté disponible.
        logger.warning(
            "llama-server no disponible en %s — el endpoint /contents/generations "
            "responderá con error hasta que arranque.",
            settings.llama_server_url,
        )

    # ── 6. Base de datos y repositorio de generaciones ────────────────────────
    engine = build_engine()
    session_factory = build_session_factory(engine)
    await init_models(engine)
    app.state.generation_repository = GenerationRepository(session_factory)

    yield

    # ── Teardown ──────────────────────────────────────────────────────────────
    await simulated.close()
    await llama_client.close()
    await engine.dispose()
    logger.info("LLM Local Service cerrado limpiamente.")


app = FastAPI(
    title="LLM Local Service",
    description=(
        "Microservicio de generación de anuncios con LLM local. "
        "Responde por streaming SSE directo al cliente móvil y autentica con JWT."
    ),
    version="0.3.0",
    lifespan=lifespan,
    docs_url="/api/llm/docs",
    openapi_url="/api/llm/openapi.json",
)

app.include_router(health_router, prefix="/api/llm", tags=["health"])
app.include_router(llm_controller.router, prefix="/api/llm")

