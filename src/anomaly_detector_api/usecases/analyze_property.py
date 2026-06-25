import asyncio
import logging
import httpx

from config.settings import settings
from ..models.property import PropertyRequest, AnalysisPayload

logger = logging.getLogger(__name__)


class AnalyzePropertyUseCase:

    async def execute(self, request: PropertyRequest) -> dict:
        await asyncio.sleep(2)

        payload = AnalysisPayload(
            draft_id=request.draft.id,
            approved=True,
            reason="Propiedad aprobada automáticamente por análisis simulado",
        )

        base_url = settings.external_service_url.rstrip("/")
        path = "/internal/validations/anomaly/result"
        url = f"{base_url}{path}"

        headers = {"X-Internal-API-Key": settings.internal_api_key}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json=payload.model_dump(by_alias=True),
                    headers=headers,
                )
            external_status_code = response.status_code
        except httpx.RequestError as exc:
            logger.error(f"Error de conexión al servicio externo: {exc}")
            external_status_code = 503

        return {
            "status": "completed",
            "draftId": request.draft.id,
            "approved": payload.approved,
            "reason": payload.reason,
            "external_status_code": external_status_code,
        }
