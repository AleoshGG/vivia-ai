import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx

from ..exceptions.llm_exceptions import LlamaServerUnavailable

logger = logging.getLogger(__name__)


class LlmClient(ABC):
    """
    Interfaz del backend de generación. El controller y los use cases solo
    conocen esta interfaz; la fase del modelo real (cliente REST a llama-server)
    se enchufa aquí sin tocar el resto del servicio.
    """

    @abstractmethod
    def stream_chat(self, user_message: str) -> AsyncIterator[str]:
        """Genera la respuesta y la emite por fragmentos."""

    async def close(self) -> None:
        """Libera recursos del cliente (conexiones HTTP en la implementación real)."""


class LlamaServerHttpClient(LlmClient):
    """
    Backend real: cliente HTTP streaming al contenedor llama-server
    (API OpenAI-compatible, `/v1/chat/completions` con `stream: true`).

    Después de agotar `stream_chat`, `last_usage` contiene el `usage` (y
    `timings` si el servidor los manda) del chunk final — es seguro leerlo
    porque el semáforo del servicio (`llm_max_concurrent=1`) serializa las
    generaciones.
    """

    def __init__(
        self,
        base_url: str,
        system_prompt: str,
        *,
        temperature: float = 1.0,
        top_p: float = 0.8,
        top_k: int = 20,
        max_tokens: int = 512,
        timeout: float = 120.0,
    ):
        self._system_prompt = system_prompt
        self._temperature = temperature
        self._top_p = top_p
        self._top_k = top_k
        self._max_tokens = max_tokens
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self.last_usage: dict | None = None

    async def stream_chat(self, user_message: str) -> AsyncIterator[str]:
        self.last_usage = None
        payload = {
            "model": "local",
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_message},
            ],
            # Sampling recomendado por Qwen para modo no-thinking (benchmarks v6).
            "temperature": self._temperature,
            "top_p": self._top_p,
            "top_k": self._top_k,
            "max_tokens": self._max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        try:
            async with self._client.stream(
                "POST", "/v1/chat/completions", json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if not data or data == "[DONE]":
                        continue
                    chunk = json.loads(data)
                    if chunk.get("usage"):
                        self.last_usage = chunk["usage"]
                        if chunk.get("timings"):
                            self.last_usage["timings"] = chunk["timings"]
                    for choice in chunk.get("choices") or []:
                        content = (choice.get("delta") or {}).get("content")
                        if content:
                            yield content
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise LlamaServerUnavailable(f"llama-server inalcanzable: {exc}") from exc

    async def health(self) -> bool:
        """True si llama-server responde 200 en /health."""
        try:
            response = await self._client.get("/health")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def wait_until_ready(self, retries: int = 15, delay: float = 2.0) -> bool:
        """Espera (con reintentos) a que llama-server esté listo al startup."""
        for attempt in range(1, retries + 1):
            if await self.health():
                logger.info("llama-server disponible (intento %d).", attempt)
                return True
            logger.info("llama-server no disponible aún (intento %d/%d).", attempt, retries)
            await asyncio.sleep(delay)
        return False

    async def close(self) -> None:
        await self._client.aclose()


class SimulatedLlmClient(LlmClient):
    """
    Backend simulado: emite un anuncio pre-armado fragmento por fragmento con
    una pausa entre cada uno, para que el streaming sea observable de verdad.
    """

    CANNED_DESCRIPTION = (
        "Una casa amplia de 200 m² en Prudencio Moscoso, a estrenar, donde el "
        "aire libre es una constante. Espacios para disfrutar el aire libre sin "
        "salir de casa, con terraza y jardín que invitan a relajarse y compartir "
        "momentos. Pensada para la convivencia en familia, con recámaras para "
        "cada miembro y un ambiente que fomenta la tranquilidad diaria."
    )

    def __init__(self, delay_s: float = 0.05):
        self._delay_s = delay_s

    async def stream_chat(self, user_message: str) -> AsyncIterator[str]:
        # Fragmentos tipo token: palabra + espacio siguiente.
        for fragment in re.findall(r"\S+\s*", self.CANNED_DESCRIPTION):
            await asyncio.sleep(self._delay_s)
            yield fragment
