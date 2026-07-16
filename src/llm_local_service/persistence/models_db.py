import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base declarativa para los modelos ORM del servicio LLM."""


class LlmGeneration(Base):
    """
    Registro persistente de una generación de título + descripción.

    El móvil solo recibe el texto; aquí queda todo lo demás para trazabilidad:
    la decisión completa del grafo, los tiempos de cada etapa, los tokens y la
    RAM del proceso, más las estampas de versión de los artefactos usados.
    """

    __tablename__ = "llm_generations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    draft_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Decision del grafo serializada (temas, audiencia, protagonistas, scores, traza…).
    decision: Mapped[dict] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Tiempos por etapa y métricas de la inferencia.
    graph_ms: Mapped[float] = mapped_column(Float, nullable=False)
    llm_s: Mapped[float] = mapped_column(Float, nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_per_second: Mapped[float | None] = mapped_column(Float, nullable=True)
    ram_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Estampas de versión de los artefactos usados (MLflow: llm-listing-generator).
    model_file: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    graph_version: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="http")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
