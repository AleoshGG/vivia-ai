import asyncio
import logging
import httpx

from config.settings import settings
from ..models.property import PropertyRequest, AnalysisPayload
from ..persistence.inference_repository import InferenceRepository
from ..services.anomaly_model import AnomalyModel
from ..services.features import build_features
from ..services.text_risk import TextRiskService

logger = logging.getLogger(__name__)

_WEBHOOK_PATH = "/internal/validations/anomaly/result"
_MAX_RETRIES  = 3
_RETRY_DELAYS = [2, 5, 10]


class AnalyzePropertyUseCase:

    def __init__(
        self,
        model: AnomalyModel,
        repository: InferenceRepository,
        text_risk: TextRiskService,
        source: str = "http",
    ):
        self._model      = model
        self._repository = repository
        self._text_risk  = text_risk
        self._source     = source

    async def execute(self, request: PropertyRequest) -> dict:
        draft = request.draft

        # 1. Análisis de texto PRIMERO. Si marca fraude, se rechaza sin correr el
        #    Isolation Forest (de todas formas se rechazaría) — cortocircuito.
        text = await self._text_risk.evaluate(draft.title, draft.description)

        if text.is_fraud_text:
            is_anomaly     = True
            approved       = False
            score          = None
            features_dict  = None
            anomaly_source = "text"
            reason = "Propiedad rechazada: " + "; ".join(text.reasons) + "."
            logger.info(
                "Rechazo por texto — draftId=%s  reasons=%s", draft.id, text.reasons,
            )
        else:
            # 2. Isolation Forest sobre features tabulares.
            loop     = asyncio.get_running_loop()
            features = build_features(draft, self._model.feature_cols)
            # predict() es síncrono (numpy/sklearn) — corre en thread pool para no bloquear el event loop
            is_anomaly, score = await loop.run_in_executor(
                None, self._model.predict, features
            )
            # cast a float nativo: numpy.float64 no es serializable a JSONB
            features_dict  = {k: float(v) for k, v in features.iloc[0].items()}
            approved       = not is_anomaly
            anomaly_source = "tabular" if is_anomaly else None
            reason = (
                "Propiedad aprobada tras análisis de anomalías y de redacción."
                if approved
                else f"Propiedad rechazada: anomalía detectada (score={score:.4f})."
            )
            logger.info(
                "Análisis completado — draftId=%s  is_anomaly=%s  score=%.4f",
                draft.id, is_anomaly, score,
            )

        # La inferencia se persiste ANTES del webhook: el registro no debe
        # depender del éxito de la notificación al servicio externo.
        await self._persist(
            request,
            is_anomaly=is_anomaly,
            score=score,
            approved=approved,
            reason=reason,
            features=features_dict,
            text_is_fraud=text.is_fraud_text,
            text_reasons=text.reasons,
            anomaly_source=anomaly_source,
        )

        analysis_payload = AnalysisPayload(
            draft_id=request.draft.id,
            approved=approved,
            reason=reason,
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

    async def _persist(
        self,
        request,
        *,
        is_anomaly,
        score,
        approved,
        reason,
        features,
        text_is_fraud,
        text_reasons,
        anomaly_source,
    ) -> None:
        """Guarda la inferencia. Un fallo de persistencia no aborta el análisis."""
        try:
            await self._repository.save(
                draft_id=request.draft.id,
                is_anomaly=is_anomaly,
                score=score,
                approved=approved,
                reason=reason,
                model_version=self._model.model_version,
                source=self._source,
                features=features,
                text_is_fraud=text_is_fraud,
                text_reasons=text_reasons,
                anomaly_source=anomaly_source,
            )
        except Exception as exc:
            logger.error(
                "No se pudo persistir la inferencia para draftId=%s: %s",
                request.draft.id, exc,
            )

    async def _post_result(self, payload: AnalysisPayload) -> int:
        url     = settings.external_service_url.rstrip("/") + _WEBHOOK_PATH
        headers = {"X-Internal-Api-Key": settings.internal_api_key}

        for attempt in range(1, _MAX_RETRIES + 1):
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
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_DELAYS[attempt - 1])

        return 503

    @staticmethod
    def _response(payload: AnalysisPayload, status_code: int) -> dict:
        # Se devuelve exactamente el mismo JSON que se envió al webhook.
        return payload.model_dump(by_alias=True)
