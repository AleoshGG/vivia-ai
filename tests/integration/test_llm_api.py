import asyncio
import json
import time

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from config.settings import settings
from src.llm_local_service.main import app
from src.llm_local_service.services.llm_client import SimulatedLlmClient
from src.llm_local_service.services.request_queue import RequestQueue

STREAM_URL = "/api/llm/generators/stream"

DRAFT_PAYLOAD = {
    "draft": {
        "id": "draft-001",
        "propertyType": {"id": "pt-house", "name": "Casa"},
        "address": {"neighborhoodName": "Prudencio Moscoso"},
        "availableToRent": True,
        "areaM2": 200.0,
        "bedrooms": 4,
        "bathrooms": 3,
        "parkingSpaces": 2,
        "constructionYear": 2025,
        "condominium": False,
        "listedPrice": 18500.0,
        "amenities": ["terraza", "jardín", "gimnasio"],
    }
}


def _token(exp_offset_s: int = 300, secret: str | None = None) -> str:
    return jwt.encode(
        {"sub": "user-1", "exp": int(time.time()) + exp_offset_s},
        secret or settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def _auth_headers(**kwargs) -> dict:
    return {"Authorization": f"Bearer {_token(**kwargs)}"}


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """Convierte el cuerpo SSE en una lista de (evento, payload)."""
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


@pytest.fixture
def llm_client():
    """Test client del LLM Local Service con lifespan (app.state) inicializado."""
    with TestClient(app) as client:
        # Backend rápido para no alargar los tests.
        app.state.llm_client = SimulatedLlmClient(delay_s=0.001)
        yield client


def test_llm_health(llm_client):
    response = llm_client.get("/api/llm/health")
    assert response.status_code == 200


def test_stream_without_token_returns_401(llm_client):
    response = llm_client.post(STREAM_URL, json=DRAFT_PAYLOAD)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_stream_with_expired_token_returns_401(llm_client):
    response = llm_client.post(
        STREAM_URL, json=DRAFT_PAYLOAD, headers=_auth_headers(exp_offset_s=-60)
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Token expired"


def test_stream_with_invalid_signature_returns_401(llm_client):
    response = llm_client.post(
        STREAM_URL, json=DRAFT_PAYLOAD, headers=_auth_headers(secret="otro-secret")
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token"


def test_stream_with_invalid_draft_returns_422(llm_client):
    response = llm_client.post(
        STREAM_URL, json={"draft": {"id": "x"}}, headers=_auth_headers()
    )
    assert response.status_code == 422


def test_stream_emits_decision_deltas_and_done(llm_client):
    response = llm_client.post(STREAM_URL, json=DRAFT_PAYLOAD, headers=_auth_headers())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response.text)
    names = [name for name, _ in events]

    assert names[0] == "decision"
    assert names.count("delta") >= 1
    assert names[-1] == "done"
    assert "error" not in names

    decision = events[0][1]
    assert decision["highlightAmenities"]

    done = events[-1][1]
    assert done["generationId"]
    assert done["title"] == "Casa en Prudencio Moscoso para renta"
    deltas = "".join(payload["text"] for name, payload in events if name == "delta")
    assert done["description"] == deltas.strip()
    assert done["warnings"] == []


def test_second_concurrent_request_is_queued(llm_client):
    app.state.llm_client = SimulatedLlmClient(delay_s=0.02)
    app.state.request_queue = RequestQueue(max_concurrent=1, max_queue_size=10)
    headers = _auth_headers()

    async def _run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            async def request_events():
                response = await ac.post(
                    STREAM_URL, json=DRAFT_PAYLOAD, headers=headers, timeout=30
                )
                return [name for name, _ in _parse_sse(response.text)]

            first = asyncio.create_task(request_events())
            await asyncio.sleep(0.05)  # garantiza que la primera ya tomó el turno
            second = asyncio.create_task(request_events())
            return await asyncio.gather(first, second)

    first_events, second_events = asyncio.run(_run())

    assert "queued" not in first_events
    assert second_events[0] == "queued"
    assert second_events[-1] == "done"


def test_stream_when_queue_is_full_returns_503(llm_client):
    app.state.request_queue = RequestQueue(max_concurrent=1, max_queue_size=0)
    response = llm_client.post(STREAM_URL, json=DRAFT_PAYLOAD, headers=_auth_headers())
    assert response.status_code == 503


def test_openapi_documents_stream_endpoint(llm_client):
    schema = llm_client.get("/api/llm/openapi.json").json()

    operation = schema["paths"][STREAM_URL]["post"]
    assert "streaming SSE" in operation["summary"]
    assert "text/event-stream" in operation["responses"]["200"]["content"]
    assert {"401", "422", "503"} <= set(operation["responses"])
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
