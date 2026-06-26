import asyncio
import logging
import httpx

from config.settings import settings
from ..models.property import PropertyRequest, AnalysisPayload

logger = logging.getLogger(__name__)

_WEBHOOK_PATH = "/api/internal/validations/anomaly/result"
_MAX_RETRIES = 3
_RETRY_DELAYS = [2, 5, 10]


class AnalyzePropertyUseCase:

    async def execute(self, request: PropertyRequest) -> dict:
        await asyncio.sleep(2)

        analysis_payload = AnalysisPayload(
            draft_id=request.draft.id,
            approved=True,
            reason="Propiedad aprobada automáticamente por análisis simulado",
        )

        status_code = await self._post_result(analysis_payload)

        if status_code // 100 != 2:
            logger.error(
                "Webhook de anomalía respondió %d para draftId=%s. Enviando resultado de fallo.",
                status_code,
                request.draft.id,
            )
            fallback_payload = AnalysisPayload(
                draft_id=request.draft.id,
                approved=False,
                reason="Error interno en la validación de anomalías. El equipo revisará tu propiedad manualmente.",
            )
            fallback_status = await self._post_result(fallback_payload)
            if fallback_status // 100 != 2:
                raise RuntimeError(
                    f"Fallo al notificar resultado de anomalía (principal={status_code}, "
                    f"fallback={fallback_status}) para draftId={request.draft.id}"
                )
            return self._response(fallback_payload, fallback_status)

        return self._response(analysis_payload, status_code)

    async def _post_result(self, payload: AnalysisPayload) -> int:
        url = settings.external_service_url.rstrip("/") + _WEBHOOK_PATH
        headers = {"X-Internal-Api-Key": settings.internal_api_key}

        for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        url,
                        json=payload.model_dump(by_alias=True),
                        headers=headers,
                    )
                if response.status_code // 100 == 2:
                    return response.status_code
                logger.warning(
                    "Intento %d/%d: webhook respondió %d para draftId=%s",
                    attempt, _MAX_RETRIES, response.status_code, payload.draft_id,
                )
            except httpx.RequestError as exc:
                logger.warning(
                    "Intento %d/%d: error de conexión al webhook para draftId=%s: %s",
                    attempt, _MAX_RETRIES, payload.draft_id, exc,
                )
            if delay is not None:
                await asyncio.sleep(delay)

        return 503

    @staticmethod
    def _response(payload: AnalysisPayload, status_code: int) -> dict:
        return {
            "status": "completed",
            "draftId": payload.draft_id,
            "approved": payload.approved,
            "reason": payload.reason,
            "external_status_code": status_code,
        }
