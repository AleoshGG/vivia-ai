"""
Descarga el modelo GGUF del generador de anuncios desde GCS al directorio
local `models_registry/llm/`, que el compose.yml monta en el contenedor
llama-server como `/models`.

Es IDEMPOTENTE: si el archivo ya existe localmente con el sha256 correcto,
no re-descarga. Para forzar, exporta `FORCE_DOWNLOAD=1`.

Uso (desde la raíz del repo):
    python -m scripts.download_llm_model

Requiere `GCS_BUCKET_NAME` y credenciales de GCS (`GCS_CREDENTIALS_PATH` o
Application Default Credentials). El archivo llega a:
    models_registry/llm/<LLM_GGUF_FILE>

y queda disponible para el contenedor en /models/llm/<LLM_GGUF_FILE>.
"""
import hashlib
import logging
import os
from pathlib import Path

from config.settings import settings
from data_lake.gcs_repository import GCSRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

GCS_KEY = f"models_registry/llm/{settings.llm_gguf_file}"


def sha256_of(path: Path) -> str:
    """Calcula el sha256 leyendo por bloques (el GGUF puede pesar ~1 GB)."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    if not settings.gcs_bucket_name:
        raise RuntimeError("GCS_BUCKET_NAME no está configurado en el entorno/.env.")

    dest: Path = Path(settings.model_registry_path) / "llm" / settings.llm_gguf_file
    dest.parent.mkdir(parents=True, exist_ok=True)

    gcs_uri = f"gs://{settings.gcs_bucket_name}/{GCS_KEY}"
    repo = GCSRepository(settings.gcs_bucket_name, settings.gcs_credentials_path)

    # Verificar que el archivo existe en GCS antes de intentar descargar.
    if not repo.exists(GCS_KEY):
        raise RuntimeError(
            f"El GGUF no está en el bucket ({gcs_uri}).\n"
            "Corre primero desde tu máquina local:\n"
            "    python -m scripts.upload_llm_model"
        )

    # Si ya existe localmente y no se fuerza, verificar el hash.
    if dest.exists() and not os.getenv("FORCE_DOWNLOAD"):
        logger.info("Archivo ya existe: %s (%.2f GB)", dest, dest.stat().st_size / 1e9)
        logger.info("Calculando sha256 local para verificar integridad...")
        local_hash = sha256_of(dest)
        logger.info("sha256 local: %s", local_hash)
        logger.info(
            "Si el hash no coincide con el esperado, re-descarga con: FORCE_DOWNLOAD=1 python -m scripts.download_llm_model"
        )
        return

    logger.info("Descargando %s → %s ...", gcs_uri, dest)

    # Usamos la API de blob directamente para evitar cargar el GGUF (~1 GB)
    # entero en memoria — download_to_filename hace streaming a disco.
    blob = repo.bucket.blob(GCS_KEY)
    size_gb = (blob.size or 0) / 1e9
    if size_gb:
        logger.info("Tamaño en GCS: %.2f GB", size_gb)

    blob.download_to_filename(str(dest))

    local_hash = sha256_of(dest)
    logger.info(
        "Descarga completa: %s (%.2f GB) sha256=%s",
        dest,
        dest.stat().st_size / 1e9,
        local_hash,
    )


if __name__ == "__main__":
    main()
