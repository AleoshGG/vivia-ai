import logging

import mlflow
import mlflow.pyfunc
from mlflow.tracking import MlflowClient

from config.settings import settings

logger = logging.getLogger(__name__)


class ModelLoader:
    """
    Carga modelos desde el Model Registry de MLflow.

    Resuelve el URI `models:/<nombre>/<stage>` y devuelve el modelo `pyfunc`
    junto con el número de versión concreto al que apunta ese stage, para poder
    trazar con qué versión se generó cada inferencia.
    """

    def __init__(self):
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        self._client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)

    def load_model(self, model_name: str, stage: str = "Production"):
        model_uri = f"models:/{model_name}/{stage}"
        logger.info("Cargando modelo desde MLflow: %s", model_uri)
        model = mlflow.pyfunc.load_model(model_uri)
        version = self._resolve_version(model_name, stage)
        logger.info("Modelo %s cargado (versión %s).", model_name, version)
        return model, version

    def _resolve_version(self, model_name: str, stage: str) -> str:
        try:
            versions = self._client.get_latest_versions(model_name, stages=[stage])
            if versions:
                return str(versions[0].version)
        except Exception as exc:  # pragma: no cover - dependiente de MLflow
            logger.warning("No se pudo resolver la versión de %s: %s", model_name, exc)
        return "unknown"
