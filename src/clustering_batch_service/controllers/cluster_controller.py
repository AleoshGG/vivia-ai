from fastapi import APIRouter, Depends
from pydantic import BaseModel
from shared.auth_middleware import verify_internal_api_key
from ..usecases.run_clustering import RunClusteringUseCase

router = APIRouter()

class ClusteringRequest(BaseModel):
    data_key: str  # Referencia a GCS o datos raw
    
@router.post("/run", dependencies=[Depends(verify_internal_api_key)])
async def run_clustering(request: ClusteringRequest):
    """
    Endpoint para encolar un job de clustering batch.
    """
    use_case = RunClusteringUseCase()
    job_id = use_case.execute(request.data_key)
    return {"status": "accepted", "job_id": job_id}
