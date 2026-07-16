import asyncio
import re
from abc import ABC, abstractmethod
from typing import AsyncIterator


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
