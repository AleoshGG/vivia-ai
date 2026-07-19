import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from shared.auth_middleware import verify_internal_api_key
from ..usecases.detect_anomaly import DetectAnomalyUseCase
from ..usecases.analyze_property import AnalyzePropertyUseCase
from ..usecases.list_inferences import ListInferencesUseCase
from ..models.property import (
    AnalysisPayload,
    InferenceListResponse,
    InferenceRecord,
    PropertyRequest,
)

router = APIRouter()


class AnomalyRequest(BaseModel):
    data_key: str  # Referencia a GCS o datos raw


def _model(request: Request):
    return request.app.state.anomaly_model


def _repository(request: Request):
    return request.app.state.inference_repository


def _text_risk(request: Request):
    return request.app.state.text_risk_service


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
    response_model=AnalysisPayload,
    response_model_by_alias=True,
    dependencies=[Depends(verify_internal_api_key)],
)
async def analyze_property(request: PropertyRequest, http_request: Request):
    """
    Recibe datos de una propiedad, ejecuta la inferencia de anomalías, persiste
    el resultado y notifica al servicio externo. Devuelve el mismo JSON que se
    envía al webhook (`draftId`, `approved`, `reason`).
    """
    use_case = AnalyzePropertyUseCase(
        model=_model(http_request),
        repository=_repository(http_request),
        text_risk=_text_risk(http_request),
        source="http",
    )
    result = await use_case.execute(request)
    return result


@router.get(
    "/inferences",
    response_model=InferenceListResponse,
    dependencies=[Depends(verify_internal_api_key)],
)
async def list_inferences(
    http_request: Request,
    draft_id: str | None = Query(None, description="Filtra por id del draft"),
    is_anomaly: bool | None = Query(None, description="Filtra por resultado de anomalía"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Lista paginada de inferencias realizadas, con filtros opcionales."""
    use_case = ListInferencesUseCase(_repository(http_request))
    return await use_case.list(
        draft_id=draft_id, is_anomaly=is_anomaly, limit=limit, offset=offset
    )


@router.get(
    "/inferences/{inference_id}",
    response_model=InferenceRecord,
    dependencies=[Depends(verify_internal_api_key)],
)
async def get_inference(inference_id: uuid.UUID, http_request: Request):
    """Devuelve el detalle de una inferencia por su id."""
    use_case = ListInferencesUseCase(_repository(http_request))
    record = await use_case.get(inference_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Inferencia no encontrada")
    return record
