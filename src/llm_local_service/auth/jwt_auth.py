import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config.settings import settings

# auto_error=False para controlar nosotros el 401 (HTTPBearer regresa 403 por defecto).
bearer_scheme = HTTPBearer(auto_error=False)

_WWW_AUTHENTICATE = {"WWW-Authenticate": "Bearer"}


async def verify_jwt(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """
    Dependencia de FastAPI que valida el JWT emitido por el backend transaccional.
    Este servicio recibe tráfico directo del cliente móvil, por lo que autentica
    con Bearer token en lugar de la API key interna. Devuelve los claims del token.
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authorization Bearer token missing",
            headers=_WWW_AUTHENTICATE,
        )
    try:
        claims = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401, detail="Token expired", headers=_WWW_AUTHENTICATE
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401, detail="Invalid token", headers=_WWW_AUTHENTICATE
        )
    return claims
