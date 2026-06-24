from fastapi import APIRouter, Depends
from pydantic import BaseModel
from shared.auth_middleware import verify_internal_api_key
from ..usecases.generate_inference import GenerateInferenceUseCase

router = APIRouter()

class InferenceRequest(BaseModel):
    prompt: str

@router.post("/generate", dependencies=[Depends(verify_internal_api_key)])
async def generate_inference(request: InferenceRequest):
    """
    Endpoint para encolar o procesar directamente una inferencia LLM.
    """
    use_case = GenerateInferenceUseCase()
    job_id = use_case.execute(request.prompt)
    return {"status": "accepted", "job_id": job_id}
