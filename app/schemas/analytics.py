from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AnalyticsEventIn(BaseModel):
    event_name: str = Field(min_length=1, max_length=64)
    event_time: datetime | None = None
    user_id: int | None = None
    anonymous_id: str | None = Field(default=None, max_length=64)
    session_id: str | None = Field(default=None, max_length=64)
    gift_id: int | None = None
    surface: str | None = Field(default=None, max_length=64)
    action: str | None = Field(default=None, max_length=32)
    path: str | None = Field(default=None, max_length=255)
    duration_seconds: float | None = None
    payload: dict[str, Any] | None = None


class AnalyticsEventOut(BaseModel):
    ok: bool
