from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PropertyType(BaseModel):
    id: str
    name: str


class Address(BaseModel):
    neighborhood_name: str = Field(..., alias="neighborhoodName")

    model_config = {"populate_by_name": True}


class Draft(BaseModel):
    """Subconjunto del draft relevante para la generación de título y descripción."""

    id: str
    property_type: PropertyType = Field(..., alias="propertyType")
    address: Address
    available_to_rent: bool = Field(..., alias="availableToRent")
    area_m2: float = Field(..., alias="areaM2")
    bedrooms: int
    bathrooms: float
    parking_spaces: int = Field(..., alias="parkingSpaces")
    construction_year: int = Field(..., alias="constructionYear")
    condominium: bool
    listed_price: float = Field(..., alias="listedPrice")
    amenities: List[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class GenerationRequest(BaseModel):
    draft: Draft


class QueuedPayload(BaseModel):
    """Evento `queued`: posición en la fila mientras se espera turno."""

    position: int


class DecisionPayload(BaseModel):
    """Evento `decision`: decisiones narrativas que guiarán la generación."""

    narrative: str
    tone: str
    audience: str
    themes: List[str]
    highlight_amenities: List[str] = Field(..., serialization_alias="highlightAmenities")

    model_config = ConfigDict(populate_by_name=True)


class DeltaPayload(BaseModel):
    """Evento `delta`: fragmento de texto generado."""

    text: str


class GenerationResult(BaseModel):
    """Evento `done`: resultado completo de la generación."""

    generation_id: UUID = Field(..., serialization_alias="generationId")
    title: str
    description: str
    duration_s: float = Field(..., serialization_alias="durationS")
    warnings: List[str] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class ErrorPayload(BaseModel):
    """Evento `error`: detalle del fallo durante el stream."""

    detail: str


class TitlePayload(BaseModel):
    """Evento `title`: título completo del anuncio (una sola vez)."""

    text: str


class ContentResult(BaseModel):
    """Evento `done` de /contents/generations: lo mínimo que necesita el móvil."""

    generation_id: UUID = Field(..., serialization_alias="generationId")
    title: str
    description: str

    model_config = ConfigDict(populate_by_name=True)


class GenerationRecord(BaseModel):
    """Representación de salida de una generación persistida (historial)."""

    id: UUID
    draft_id: str = Field(..., serialization_alias="draftId")
    title: str
    description: str
    decision: dict
    warnings: List[str]
    graph_ms: float = Field(..., serialization_alias="graphMs")
    llm_s: float = Field(..., serialization_alias="llmS")
    duration_s: float = Field(..., serialization_alias="durationS")
    prompt_tokens: Optional[int] = Field(None, serialization_alias="promptTokens")
    output_tokens: Optional[int] = Field(None, serialization_alias="outputTokens")
    tokens_per_second: Optional[float] = Field(None, serialization_alias="tokensPerSecond")
    ram_mb: Optional[float] = Field(None, serialization_alias="ramMb")
    model_file: str = Field(..., serialization_alias="modelFile")
    prompt_version: str = Field(..., serialization_alias="promptVersion")
    graph_version: str = Field(..., serialization_alias="graphVersion")
    source: str
    created_at: datetime = Field(..., serialization_alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class GenerationListResponse(BaseModel):
    """Listado paginado de generaciones."""

    total: int
    limit: int
    offset: int
    items: List[GenerationRecord]
