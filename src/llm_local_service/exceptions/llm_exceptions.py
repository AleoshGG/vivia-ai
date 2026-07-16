from shared.exceptions import BaseServiceException


class GenerationError(BaseServiceException):
    """Fallo durante la generación; se reporta al cliente como evento SSE `error`."""

    def __init__(self, message: str):
        super().__init__(message, code="generation_error")


class QueueFullError(BaseServiceException):
    """La cola de espera alcanzó su capacidad máxima; la petición se rechaza con 503."""

    def __init__(self, message: str = "La cola de generación está llena, intenta más tarde."):
        super().__init__(message, code="queue_full")


class LlamaServerUnavailable(BaseServiceException):
    """No se pudo hablar con llama-server (caído o sin arrancar)."""

    def __init__(self, message: str = "El backend de inferencia no está disponible."):
        super().__init__(message, code="llama_server_unavailable")
