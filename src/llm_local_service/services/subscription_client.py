import logging

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


class SubscriptionServiceUnavailable(Exception):
    """No se pudo consultar /subscriptions/me (timeout, red caída o respuesta no-200)."""


async def is_premium(authorization_header: str) -> bool:
    """
    Consulta GET {VIVIA_BACKEND_URL}/subscriptions/me reenviando el JWT del cliente.
    Fail-closed: cualquier falla se reporta como SubscriptionServiceUnavailable,
    nunca se asume premium por defecto.
    """
    url = settings.vivia_backend_url.rstrip("/") + "/subscriptions/me"
    try:
        async with httpx.AsyncClient(timeout=settings.subscriptions_check_timeout) as client:
            response = await client.get(url, headers={"Authorization": authorization_header})
    except httpx.RequestError as exc:
        logger.warning("Fallo al consultar /subscriptions/me: %s", exc)
        raise SubscriptionServiceUnavailable(str(exc)) from exc

    if response.status_code != 200:
        logger.warning("/subscriptions/me respondió %d", response.status_code)
        raise SubscriptionServiceUnavailable(f"status={response.status_code}")

    return response.json()["data"]["active"]
