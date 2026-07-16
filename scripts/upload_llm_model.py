"""
Sube el modelo GGUF del generador de anuncios (`models_registry/llm/`) al
bucket de GCS, para que el binario no viva solo en disco local.

Es IDEMPOTENTE: si el objeto ya existe en el bucket, no re-sube. Para forzar
una re-subida (p. ej. si el archivo local cambió), exporta `FORCE_UPLOAD=1`.

Imprime el hash sha256 del archivo local — es el mismo hash que
`scripts/register_llm_generator.py` estampa en el `metadata.json` del Model
Registry, garantizando que bucket y registry hablan del mismo binario.

Uso:
    python -m scripts.upload_llm_model

Requiere `GCS_BUCKET_NAME` y credenciales de GCS (`GCS_CREDENTIALS_PATH` o
Application Default Credentials).
"""
import hashlib
import logging
import os
from pathlib import Path

from config.settings import settings
from data_lake.gcs_repository import GCSRepository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GCS_KEY = f"models_registry/llm/{settings.llm_gguf_file}"


def sha256_of(path: Path) -> str:
    """Calcula el sha256 leyendo por bloques (el GGUF pesa ~1 GB)."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def main() -> None:
    if not settings.gcs_bucket_name:
        raise RuntimeError("GCS_BUCKET_NAME no está configurado en el entorno/.env.")

    gguf_path = Path(settings.model_registry_path) / "llm" / settings.llm_gguf_file
    if not gguf_path.exists():
        raise FileNotFoundError(f"GGUF no encontrado en {gguf_path}")

    digest = sha256_of(gguf_path)
    logger.info("GGUF local: %s (%.2f GB) sha256=%s",
                gguf_path, gguf_path.stat().st_size / 1e9, digest)

    repo = GCSRepository(settings.gcs_bucket_name, settings.gcs_credentials_path)
    uri = f"gs://{settings.gcs_bucket_name}/{GCS_KEY}"

    if not os.getenv("FORCE_UPLOAD") and repo.exists(GCS_KEY):
        logger.info("El objeto ya existe en %s. Omitiendo subida.", uri)
        return

    logger.info("Subiendo a %s ...", uri)
    with open(gguf_path, "rb") as f:
        repo.upload(GCS_KEY, f)
    logger.info("Subida completa: %s", uri)


if __name__ == "__main__":
    main()
