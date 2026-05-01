from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import get_current_user
from app.models import User
from app.schemas.user import UserRead, UserUpdate

router = APIRouter()


@router.get("/me", response_model=UserRead)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
):
    return UserRead.model_validate(current_user, from_attributes=True)


@router.put("/me", response_model=UserRead)
async def update_current_user_profile(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if payload.name is not None:
        current_user.name = payload.name
    if payload.email is not None:
        existing = await session.execute(select(User).where(User.email == payload.email, User.id != current_user.id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already exists")
        current_user.email = payload.email
    if payload.phone is not None:
        existing = await session.execute(select(User).where(User.phone == payload.phone, User.id != current_user.id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Phone already exists")
        current_user.phone = payload.phone
    if payload.avatar_url is not None:
        current_user.avatar_url = payload.avatar_url
    await session.commit()
    await session.refresh(current_user)
    return UserRead.model_validate(current_user, from_attributes=True)
