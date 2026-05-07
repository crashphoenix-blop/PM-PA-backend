from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import get_current_user_optional
from app.models import AnalyticsEvent, User
from app.schemas.analytics import AnalyticsEventIn, AnalyticsEventOut

router = APIRouter()


@router.post("/events", response_model=AnalyticsEventOut, status_code=status.HTTP_201_CREATED)
async def ingest_event(
    payload: AnalyticsEventIn,
    session: AsyncSession = Depends(get_session),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> AnalyticsEventOut:
    event = AnalyticsEvent(
        event_name=payload.event_name,
        event_time=payload.event_time or datetime.now(timezone.utc),
        user_id=current_user.id if current_user else payload.user_id,
        anonymous_id=payload.anonymous_id,
        session_id=payload.session_id,
        gift_id=payload.gift_id,
        surface=payload.surface,
        action=payload.action,
        path=payload.path,
        duration_seconds=payload.duration_seconds,
        payload=payload.payload,
    )
    session.add(event)
    await session.commit()
    return AnalyticsEventOut(ok=True)
