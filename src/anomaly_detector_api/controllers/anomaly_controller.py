from fastapi import APIRouter, Depends
from pydantic import BaseModel
from shared.auth_middleware import verify_internal_api_key
from ..usecases.detect_anomaly import DetectAnomalyUseCase
from ..usecases.analyze_property import AnalyzePropertyUseCase
from ..models.property import PropertyRequest, PropertyAnalysisResponse

router = APIRouter()

class AnomalyRequest(BaseModel):
    data_key: str  # Referencia a GCS o datos raw

@router.post("/detect", dependencies=[Depends(verify_internal_api_key)])
async def detect_anomaly(request: AnomalyRequest):
    """
    Endpoint para encolar la petición de detección de anomalías.
    """
    use_case = DetectAnomalyUseCase()
    job_id = use_case.execute(request.data_key)
    return {"status": "accepted", "job_id": job_id}


@router.post(
    "/analyze",
    response_model=PropertyAnalysisResponse,
    dependencies=[Depends(verify_internal_api_key)],
)
async def analyze_property(request: PropertyRequest):
    """
    Recibe datos de una propiedad, simula un análisis (2s de delay)
    y notifica el resultado al servicio externo.
    """
    use_case = AnalyzePropertyUseCase()
    result = await use_case.execute(request)
    return result
