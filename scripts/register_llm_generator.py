"""
Registra el generador de anuncios LLM como una versión del Model Registry de
MLflow y la promueve a stage `Production`.

Artefactos registrados (aterrizan en el bucket vía MLFLOW_ARTIFACT_ROOT):
- los CSVs del grafo ponderado v4 (`src/llm_local_service/resources/graph/`),
- el system prompt v6 y el contrato de salida (`resources/prompts/`),
- un `metadata.json` generado aquí con el GGUF referenciado por URI gs:// y
  hash sha256 (el binario de ~1 GB NO se sube como artefacto de MLflow: se
  sube una sola vez al bucket con `scripts/upload_llm_model.py`).

Es IDEMPOTENTE: si ya existe una versión en `Production`, no hace nada. Para
forzar un nuevo registro, exporta `FORCE_REGISTER=1`.

Uso:
    python -m scripts.register_llm_generator

Requiere que el GGUF ya esté respaldado en el bucket (corre antes
`python -m scripts.upload_llm_model`) y que MLflow esté disponible.
"""
import json
import logging
import os
import tempfile
import time
from pathlib import Path

import mlflow
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from config.settings import settings
from data_lake.gcs_repository import GCSRepository
from scripts.upload_llm_model import GCS_KEY, sha256_of

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_NAME = settings.llm_model_name
STAGE = settings.llm_model_stage

RESOURCES_DIR = Path("src/llm_local_service/resources")
PROMPT_FILE = RESOURCES_DIR / "prompts/system_prompt_v6.txt"
SCHEMA_FILE = RESOURCES_DIR / "prompts/output_schema.json"
GRAPH_DIR = RESOURCES_DIR / "graph"

# Parámetros validados en notebooks/graph-ai/benchmark_prompt_v6.py.
SERVING_PARAMS = {
    "threads": 4,
    "ctx_size": 4096,
    "parallel": 1,
    "enable_thinking": False,
}
SAMPLING_PARAMS = {
    "temperature": 1.0,
    "top_p": 0.8,
    "top_k": 20,
    "max_tokens": 512,
}

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


def _validate_local_artifacts() -> list[Path]:
    graph_csvs = sorted(GRAPH_DIR.glob("*.csv"))
    if not graph_csvs:
        raise FileNotFoundError(f"No hay CSVs del grafo en {GRAPH_DIR}")
    for path in (PROMPT_FILE, SCHEMA_FILE):
        if not path.exists():
            raise FileNotFoundError(f"Artefacto no encontrado: {path}")
    return graph_csvs


def _validate_gguf_in_bucket() -> str:
    """Verifica que el GGUF esté respaldado en el bucket y regresa su URI."""
    if not settings.gcs_bucket_name:
        raise RuntimeError("GCS_BUCKET_NAME no está configurado en el entorno/.env.")
    repo = GCSRepository(settings.gcs_bucket_name, settings.gcs_credentials_path)
    uri = f"gs://{settings.gcs_bucket_name}/{GCS_KEY}"
    if not repo.exists(GCS_KEY):
        raise RuntimeError(
            f"El GGUF no está en el bucket ({uri}). "
            "Corre primero: python -m scripts.upload_llm_model"
        )
    return uri


def _build_metadata(gguf_path: Path, gguf_gcs_uri: str) -> dict:
    nombre = gguf_path.name  # p. ej. Qwen3-1.7B-Q4_K_M.gguf
    return {
        "model_file": nombre,
        "quantization": nombre.removesuffix(".gguf").split("-")[-1],
        "sha256": sha256_of(gguf_path),
        "gguf_gcs_uri": gguf_gcs_uri,
        "prompt_version": "v6",
        "graph_version": "v4",
        "serving": SERVING_PARAMS,
        "sampling": SAMPLING_PARAMS,
    }


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

    graph_csvs = _validate_local_artifacts()
    gguf_path = Path(settings.model_registry_path) / "llm" / settings.llm_gguf_file
    if not gguf_path.exists():
        raise FileNotFoundError(f"GGUF no encontrado en {gguf_path}")
    gguf_gcs_uri = _validate_gguf_in_bucket()

    metadata = _build_metadata(gguf_path, gguf_gcs_uri)
    logger.info("Metadata del registro: %s", json.dumps(metadata, indent=2))

    mlflow.set_experiment("llm-generation")
    with mlflow.start_run(run_name="register-llm-generator") as run:
        for csv in graph_csvs:
            mlflow.log_artifact(str(csv), artifact_path="model/graph")
        mlflow.log_artifact(str(PROMPT_FILE), artifact_path="model/prompts")
        mlflow.log_artifact(str(SCHEMA_FILE), artifact_path="model/prompts")
        with tempfile.TemporaryDirectory() as tmp:
            metadata_path = Path(tmp) / "metadata.json"
            metadata_path.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            mlflow.log_artifact(str(metadata_path), artifact_path="model")

        mlflow.register_model(f"runs:/{run.info.run_id}/model", MODEL_NAME)
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
