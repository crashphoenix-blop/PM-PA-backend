from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.schemas.category import CategoryRead
from app.schemas.gift_image import GiftImageRead


class GiftBase(BaseModel):
    name: str
    description: Optional[str] = None
    price: int = Field(..., ge=0)
    image_url: str
    store_name: Optional[str] = None
    store_url: Optional[str] = None


class GiftRead(GiftBase):
    id: int
    is_favorite: bool = False
    created_at: datetime
    categories: List[CategoryRead] = []
    images: List[GiftImageRead] = []

    model_config = ConfigDict(from_attributes=True)


class GiftListResponse(BaseModel):
    gifts: List[GiftRead]
    total: int
    page: int
    per_page: int


class GiftCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    price: int = Field(..., ge=0)
    image_url: str
    store_name: Optional[str] = Field(None, max_length=255)
    store_url: Optional[str] = None
    category_ids: List[int] = Field(default_factory=list)
    category_names: List[str] = Field(default_factory=list)

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str) -> str:
        normalized = value.strip()
        if normalized.startswith("/media/"):
            return normalized
        HttpUrl(normalized)
        return normalized

    @field_validator("store_url")
    @classmethod
    def validate_store_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        normalized = str(value).strip()
        HttpUrl(normalized)
        return normalized
