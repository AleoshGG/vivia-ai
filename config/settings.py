from pathlib import Path
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
    gcs_bucket_name: Optional[str] = None
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
    anomaly_model_name: str = "anomaly"
    anomaly_model_stage: str = "Production"

    # === Base de datos (PostgreSQL) ===
    database_url: str = "postgresql+asyncpg://vivia:changeme@localhost:5432/vivia"

    # === Servicios Externos ===
    external_service_url: str = "http://localhost:8080"

    # === Model Registry ===
    model_registry_path: Path = Path('models_registry')

    # === Análisis de texto (riesgo textual del servicio de anomalías) ===
    # Reusa `llama_server_url` como backend (Qwen3 zero-shot). El feature-flag
    # permite operar solo con reglas si el llama-server no está disponible.
    text_risk_enabled: bool = True
    text_risk_timeout: float = 30.0
    text_risk_max_tokens: int = 400

    # === Servicios ===
    anomaly_api_port: int = 8001
    clustering_service_port: int = 8002
    llm_local_port: int = 8003

    # === LLM Local Service ===
    # JWT: el servicio LLM recibe tráfico directo del cliente móvil (no usa la API key interna).
    # El backend transaccional firma con HS512, que requiere un secret de al menos 64 bytes.
    jwt_secret: str = "changeme-jwt-secret-of-at-least-64-bytes-for-hs512-change-me-now!"
    jwt_algorithm: str = "HS512"
    # Cola de espera: una generación a la vez (el LLM real correrá con --parallel 1).
    llm_max_concurrent: int = 1
    llm_max_queue_size: int = 10
    # Backend simulado: pausa entre fragmentos para observar el streaming real.
    llm_simulated_delay_s: float = 0.05
    # Versionado del generador (MLflow Model Registry) y modelo servido.
    llm_model_name: str = "llm-listing-generator"
    llm_model_stage: str = "Production"
    llm_gguf_file: str = "Qwen3-1.7B-Q4_K_M.gguf"
    # URL del contenedor llama-server (en compose: http://llama-server:8080).
    llama_server_url: str = "http://localhost:8080"
    # Sampling validado en notebooks/graph-ai/benchmark_prompt_v6.py (Qwen3 no-thinking).
    llm_temperature: float = 1.0
    llm_top_p: float = 0.8
    llm_top_k: int = 20
    llm_max_tokens: int = 512
    llm_request_timeout: float = 120.0
    # Artefactos de producción del generador (grafo v4 + prompt v6).
    graph_resources_path: Path = Path("src/llm_local_service/resources")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

# Instancia global de settings
settings = Settings()
