from pydantic import BaseModel

class InferenceResult(BaseModel):
    text: str
    tokens_used: int
