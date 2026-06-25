from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    """
    Configuración centralizada cargada desde variables de entorno y/o archivo .env.
    """
    # === General ===
    environment: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    # === Autenticación ===
    internal_api_key: str

    # === Google Cloud Storage ===
    gcs_bucket_name: str
    gcs_credentials_path: Optional[str] = None

    # === RabbitMQ ===
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "guest"
    rabbitmq_password: str = "guest"
    rabbitmq_vhost: str = "/"

    # === MLflow ===
    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_artifact_root: Optional[str] = None

    # === Servicios Externos ===
    external_service_url: str = "http://localhost:8080"

    # === Servicios ===
    anomaly_api_port: int = 8001
    clustering_service_port: int = 8002
    llm_local_port: int = 8003

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

# Instancia global de settings
settings = Settings()
