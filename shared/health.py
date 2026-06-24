from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health_check():
    """
    Endpoint básico de health check reutilizable en todos los servicios.
    """
    return {"status": "ok"}
