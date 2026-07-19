import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base declarativa para los modelos ORM del servicio de anomalías."""


class AnomalyInference(Base):
    """
    Registro persistente de una inferencia de detección de anomalías.

    Se guarda una fila por cada predicción realizada, tanto desde el endpoint
    HTTP (`source='http'`) como desde el consumidor de la cola (`source='queue'`).
    """

    __tablename__ = "anomaly_inferences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    draft_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    # is_anomaly: decisión final (fraude de texto ∨ anomalía tabular).
    is_anomaly: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # score/features: nullable — quedan NULL cuando el texto rechaza y el
    # Isolation Forest no llega a ejecutarse (cortocircuito).
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    features: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Análisis de texto (título/descripción).
    text_is_fraud: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    text_reasons: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Origen del rechazo: "text" | "tabular".
    anomaly_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
