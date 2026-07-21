from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from ..services.subscription_client import SubscriptionServiceUnavailable, is_premium
from .jwt_auth import bearer_scheme


async def require_premium(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    """
    Dependencia de FastAPI que exige suscripción premium activa antes de generar
    contenido con IA. Debe declararse después de `verify_jwt` en la lista de
    dependencias, para que un JWT inválido siga devolviendo 401 primero.
    """
    authorization_header = f"Bearer {credentials.credentials}"

    try:
        active = await is_premium(authorization_header)
    except SubscriptionServiceUnavailable:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "subscription_check_failed",
                "message": "No se pudo verificar el estado de suscripción, intenta más tarde.",
            },
        )

    if not active:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "premium_required",
                "message": "Requiere suscripción Premium para generar contenido con IA.",
            },
        )
