from fastapi import Request, HTTPException, Depends
from fastapi.security import APIKeyHeader
from config.settings import settings

api_key_header = APIKeyHeader(name="X-Internal-API-Key", auto_error=False)

async def verify_internal_api_key(api_key: str = Depends(api_key_header)):
    """
    Middleware/Dependencia para FastAPI que valida el API Key interno.
    Solo se permite el acceso a los microservicios mediante esta key.
    """
    if not api_key:
        raise HTTPException(status_code=403, detail="X-Internal-API-Key header missing")
    if api_key != settings.internal_api_key:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key
