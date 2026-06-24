class BaseServiceException(Exception):
    """
    Excepción base para todos los errores de dominio.
    """
    def __init__(self, message: str, code: str = "internal_error"):
        self.message = message
        self.code = code
        super().__init__(self.message)

class NotFoundException(BaseServiceException):
    def __init__(self, message: str):
        super().__init__(message, code="not_found")

class ValidationException(BaseServiceException):
    def __init__(self, message: str):
        super().__init__(message, code="validation_error")
