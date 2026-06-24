from shared.exceptions import BaseServiceException

class LLMInferenceError(BaseServiceException):
    def __init__(self, message: str):
        super().__init__(message, code="llm_inference_error")
