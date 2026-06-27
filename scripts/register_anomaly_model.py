"""
Registra el modelo de anomalías actual (artefactos en `models_registry/anomaly/`)
como una versión del Model Registry de MLflow y la promueve a stage `Production`.

Es IDEMPOTENTE: si ya existe una versión en `Production`, no hace nada. Esto
permite ejecutarlo en cada deploy sin acumular versiones duplicadas. Para forzar
un nuevo registro, exporta `FORCE_REGISTER=1`.

Uso:
    python -m scripts.register_anomaly_model

Espera a que el servidor MLflow (`settings.mlflow_tracking_uri`) esté disponible.
"""
import logging
import os
import time
from pathlib import Path

import mlflow
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from config.settings import settings
from src.anomaly_detector_api.services.anomaly_pyfunc import AnomalyDetectorModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_NAME = settings.anomaly_model_name
STAGE = settings.anomaly_model_stage

_WAIT_RETRIES = 30
_WAIT_DELAY = 5


def _wait_for_mlflow(client: MlflowClient) -> None:
    """Espera (con reintentos) a que el servidor MLflow responda."""
    for attempt in range(1, _WAIT_RETRIES + 1):
        try:
            client.search_registered_models(max_results=1)
            return
        except Exception as exc:  # conexión rechazada mientras MLflow arranca
            logger.info(
                "MLflow no disponible aún (intento %d/%d): %s",
                attempt, _WAIT_RETRIES, exc,
            )
            time.sleep(_WAIT_DELAY)
    raise RuntimeError("MLflow no respondió tras varios intentos.")


def _has_production_version(client: MlflowClient) -> bool:
    try:
        return bool(client.get_latest_versions(MODEL_NAME, stages=[STAGE]))
    except MlflowException:
        # El modelo registrado aún no existe.
        return False


def main() -> None:
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)

    _wait_for_mlflow(client)

    if not os.getenv("FORCE_REGISTER") and _has_production_version(client):
        logger.info(
            "El modelo '%s' ya tiene una versión en %s. Omitiendo registro.",
            MODEL_NAME, STAGE,
        )
        return

    artifacts_dir = Path(settings.model_registry_path) / "anomaly"
    artifacts = {
        "model": str(artifacts_dir / "isolation_forest_v1.joblib"),
        "scaler": str(artifacts_dir / "scaler_v1.joblib"),
        "feature_columns": str(artifacts_dir / "feature_columns_v1.json"),
        "metadata": str(artifacts_dir / "metadata_v1.json"),
    }
    for key, path in artifacts.items():
        if not Path(path).exists():
            raise FileNotFoundError(f"Artefacto '{key}' no encontrado en {path}")

    mlflow.set_experiment("anomaly-detection")
    with mlflow.start_run(run_name="register-anomaly") as run:
        mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=AnomalyDetectorModel(),
            artifacts=artifacts,
            registered_model_name=MODEL_NAME,
            pip_requirements=["scikit-learn", "joblib", "pandas", "numpy"],
        )
        logger.info("Modelo registrado desde run %s", run.info.run_id)

    latest = client.get_latest_versions(MODEL_NAME, stages=["None"])
    if not latest:
        raise RuntimeError("No se encontró la versión recién registrada.")
    version = latest[0].version
    client.transition_model_version_stage(
        name=MODEL_NAME,
        version=version,
        stage=STAGE,
        archive_existing_versions=True,
    )
    logger.info("Versión %s de '%s' promovida a %s.", version, MODEL_NAME, STAGE)


if __name__ == "__main__":
    main()
