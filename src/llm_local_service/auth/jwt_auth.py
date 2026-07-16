import hashlib
import logging

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config.settings import settings

logger = logging.getLogger(__name__)

# auto_error=False para controlar nosotros el 401 (HTTPBearer regresa 403 por defecto).
bearer_scheme = HTTPBearer(auto_error=False)

_WWW_AUTHENTICATE = {"WWW-Authenticate": "Bearer"}

# Diagnóstico por tipo de error de PyJWT (todos son subclases de InvalidTokenError).
_REJECTION_HINTS = {
    "InvalidSignatureError": (
        "la firma no coincide: el JWT_SECRET de este servicio no es el mismo "
        "(byte por byte) con el que el emisor firmó el token"
    ),
    "InvalidAlgorithmError": (
        "el 'alg' del header del token no coincide con JWT_ALGORITHM configurado"
    ),
    "DecodeError": "el token no tiene formato JWT válido (¿llegó completo/sin comillas extra?)",
    "ImmatureSignatureError": "el token aún no es válido (claim nbf/iat en el futuro: ¿reloj desfasado?)",
}


def _secret_fingerprint() -> str:
    """Huella del secret configurado (longitud + hash, NUNCA el secret) para
    compararla contra la del emisor sin exponer el valor en los logs."""
    digest = hashlib.sha256(settings.jwt_secret.encode()).hexdigest()[:12]
    return f"len={len(settings.jwt_secret)} sha256[:12]={digest}"


async def verify_jwt(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """
    Dependencia de FastAPI que valida el JWT emitido por el backend transaccional.
    Este servicio recibe tráfico directo del cliente móvil, por lo que autentica
    con Bearer token en lugar de la API key interna. Devuelve los claims del token.
    """
    if credentials is None:
        logger.warning("JWT rechazado: no llegó el header 'Authorization: Bearer <token>'")
        raise HTTPException(
            status_code=401,
            detail="Authorization Bearer token missing",
            headers=_WWW_AUTHENTICATE,
        )
    token = credentials.credentials
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        unverified = jwt.decode(token, options={"verify_signature": False})
        logger.warning(
            "JWT rechazado: token expirado — exp=%s sub=%s",
            unverified.get("exp"), unverified.get("sub"),
        )
        raise HTTPException(
            status_code=401, detail="Token expired", headers=_WWW_AUTHENTICATE
        )
    except jwt.InvalidTokenError as exc:
        error_type = type(exc).__name__
        try:
            token_header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError:
            token_header = "<header no decodificable>"
        logger.warning(
            "JWT rechazado: %s (%s) — pista: %s | header del token: %s | "
            "alg esperado: %s | secret configurado: %s",
            error_type,
            exc,
            _REJECTION_HINTS.get(error_type, "revisar mensaje del error"),
            token_header,
            settings.jwt_algorithm,
            _secret_fingerprint(),
        )
        raise HTTPException(
            status_code=401, detail="Invalid token", headers=_WWW_AUTHENTICATE
        )
    return claims
