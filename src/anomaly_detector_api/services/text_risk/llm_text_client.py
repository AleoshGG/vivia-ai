"""Capa 1 — cliente HTTP no-streaming al contenedor `llama-server`.

Reutiliza Qwen3 vía la API OpenAI-compatible (`/v1/chat/completions`) con salida
JSON restringida por esquema. Abre un `httpx.AsyncClient` por llamada (mismo
patrón que `AnalyzePropertyUseCase._post_result`) para no atar el cliente a un
event loop concreto — el consumidor de cola corre en su propio hilo/loop.

Ante cualquier fallo del servidor devuelve `None`: el `TextRiskService` degrada
a solo reglas sin abortar el análisis.
"""

from __future__ import annotations

import json
import logging

import httpx

from ...models.text_risk import LlmVerdict
from .prompt import FRAUD_SCHEMA, SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class LlamaTextRiskClient:
    """Clasificador binario de fraude servido por `llama-server`."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        max_tokens: int = 400,
        temperature: float = 0.1,
        top_p: float = 0.8,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._top_p = top_p

    async def classify(self, title: str, description: str) -> LlmVerdict | None:
        """Devuelve el veredicto del LLM, o None si el servidor no responde."""
        payload = {
            "model": "local",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f'TÍTULO: {title}\nDESCRIPCIÓN: {description or ""}',
                },
            ],
            "temperature": self._temperature,
            "top_p": self._top_p,
            "max_tokens": self._max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_object", "schema": FRAUD_SCHEMA},
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout
            ) as client:
                response = await client.post("/v1/chat/completions", json=payload)
                response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return self._parse(content)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning(
                "Análisis de texto por LLM no disponible, se degrada a reglas: %s", exc
            )
            return None

    @staticmethod
    def _parse(content: str) -> LlmVerdict:
        data = json.loads(content)
        label = data.get("label", "limpio")
        return LlmVerdict(
            label=label if label in ("limpio", "fraude") else "limpio",
            reasons=data.get("reasons", []),
            extracted=data.get("extracted", {}),
        )
