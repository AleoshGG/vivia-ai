from pydantic import BaseModel

class AnomalyResult(BaseModel):
    is_anomaly: bool
    score: float
