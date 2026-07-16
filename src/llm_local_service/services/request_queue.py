import asyncio
from typing import AsyncIterator

from ..exceptions.llm_exceptions import QueueFullError


class RequestQueue:
    """
    Cola de espera en memoria para las generaciones del LLM.

    El LLM atiende `max_concurrent` generaciones a la vez (1 en producción, el
    backend real correrá con --parallel 1); las peticiones excedentes se forman
    en una fila FIFO acotada por `max_queue_size`. Es estado efímero de
    coordinación: vive y muere con las conexiones SSE abiertas, por lo que no
    requiere un broker externo mientras el servicio corra en una sola réplica.
    """

    def __init__(self, max_concurrent: int, max_queue_size: int):
        self._max_concurrent = max_concurrent
        self._max_queue_size = max_queue_size
        self._active = 0
        # Un canal por petición en espera; recibe su posición (0 = turno concedido).
        self._waiters: list[asyncio.Queue[int]] = []
        self._lock = asyncio.Lock()

    @property
    def is_full(self) -> bool:
        return len(self._waiters) >= self._max_queue_size

    @property
    def waiting(self) -> int:
        return len(self._waiters)

    async def acquire(self) -> AsyncIterator[int]:
        """
        Generador asíncrono que emite la posición en la fila mientras se espera
        turno y termina cuando el turno fue tomado. El que llama debe liberar
        SIEMPRE con `release()` una vez agotado el generador.

        Lanza `QueueFullError` si la fila está llena.
        """
        async with self._lock:
            if self._active < self._max_concurrent and not self._waiters:
                self._active += 1
                return
            if len(self._waiters) >= self._max_queue_size:
                raise QueueFullError()
            channel: asyncio.Queue[int] = asyncio.Queue()
            self._waiters.append(channel)
            position = len(self._waiters)

        granted = False
        try:
            yield position
            while not granted:
                position = await channel.get()
                if position == 0:
                    granted = True
                else:
                    yield position
        finally:
            if not granted:
                await self._abandon(channel)

    async def release(self) -> None:
        """Libera el turno: se lo cede al primero de la fila o reduce los activos."""
        async with self._lock:
            if self._waiters:
                # El turno pasa directo al siguiente; _active no cambia.
                next_channel = self._waiters.pop(0)
                next_channel.put_nowait(0)
                self._notify_positions()
            else:
                self._active -= 1

    async def _abandon(self, channel: asyncio.Queue) -> None:
        """El que esperaba se desconectó: sale de la fila o devuelve el turno recibido."""
        async with self._lock:
            if channel in self._waiters:
                self._waiters.remove(channel)
                self._notify_positions()
                return
        # Ya no estaba en la fila: el turno le fue concedido justo antes de irse.
        await self.release()

    def _notify_positions(self) -> None:
        for index, waiter in enumerate(self._waiters):
            waiter.put_nowait(index + 1)
