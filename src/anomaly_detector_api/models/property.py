from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from datetime import datetime


class PropertyType(BaseModel):
    id: str
    name: str


class Address(BaseModel):
    id: str
    neighborhood_id: str = Field(..., alias="neighborhoodId")
    neighborhood_name: str = Field(..., alias="neighborhoodName")
    postal_code: str = Field(..., alias="postalCode")
    street: str
    exterior_number: str = Field(..., alias="exteriorNumber")
    interior_number: Optional[str] = Field(None, alias="interiorNumber")

    model_config = {"populate_by_name": True}


class MediaFile(BaseModel):
    id: str
    draft_id: str = Field(..., alias="draftId")
    file_key: str = Field(..., alias="fileKey")
    content_type: str = Field(..., alias="contentType")
    storage_key: str = Field(..., alias="storageKey")
    status: str
    classification: str

    model_config = {"populate_by_name": True}


class Draft(BaseModel):
    id: str
    lessor_id: str = Field(..., alias="lessorId")
    property_type: PropertyType = Field(..., alias="propertyType")
    address: Address
    media_files: Dict[str, MediaFile] = Field(..., alias="mediaFiles")
    available_to_rent: bool = Field(..., alias="availableToRent")
    title: str
    description: Optional[str] = None
    area_m2: float = Field(..., alias="areaM2")
    bedrooms: int
    bathrooms: float
    parking_spaces: int = Field(..., alias="parkingSpaces")
    construction_year: int = Field(..., alias="constructionYear")
    condominium: bool
    listed_price: float = Field(..., alias="listedPrice")
    price_per_m2: float = Field(..., alias="pricePerM2")
    status: str
    total_files: int = Field(..., alias="totalFiles")
    total_images: int = Field(..., alias="totalImages")
    total_videos: int = Field(..., alias="totalVideos")
    approved_files: int = Field(..., alias="approvedFiles")
    rejected_files: int = Field(..., alias="rejectedFiles")
    amenity_ids: List[str] = Field(..., alias="amenityIds")
    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")
    expires_at: datetime = Field(..., alias="expiresAt")

    model_config = {"populate_by_name": True}


class PropertyRequest(BaseModel):
    draft: Draft


class AnalysisPayload(BaseModel):
    draft_id: str = Field(..., alias="draftId", serialization_alias="draftId")
    approved: bool
    reason: str

    model_config = {"populate_by_name": True}


class PropertyAnalysisResponse(BaseModel):
    status: str
    draft_id: str = Field(..., alias="draftId", serialization_alias="draftId")
    approved: bool
    reason: str
    external_status_code: int = Field(..., description="Código HTTP devuelto por el servicio externo")

    model_config = {"populate_by_name": True}
