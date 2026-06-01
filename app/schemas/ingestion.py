from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class IngestionRunRead(BaseModel):
    id: int
    status: str
    triggered_by: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    found_count: int
    new_count: int
    duplicate_count: int
    error_count: int
    error_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class GiftCandidateRead(BaseModel):
    id: int
    source_id: int
    run_id: int
    dedup_key: str
    name: str
    description: Optional[str] = None
    price: int
    image_url: str
    store_name: str
    store_url: str
    status: str
    duplicate_reason: Optional[str] = None
    published_gift_id: Optional[int] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    source_key: Optional[str] = None
    source_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class GiftCandidateListResponse(BaseModel):
    candidates: List[GiftCandidateRead]
    total: int


class CandidateApproveRequest(BaseModel):
    category_ids: List[int] = Field(default_factory=list)
    category_names: List[str] = Field(default_factory=list)
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[int] = Field(None, ge=0)


class IngestionRunRequest(BaseModel):
    triggered_by: str = "admin"


class IngestionClearResponse(BaseModel):
    deleted_candidates: int
    deleted_runs: int
