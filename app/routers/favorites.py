from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import get_current_user
from app.models import Gift, User, favorites_table
from app.schemas.gift import GiftRead

router = APIRouter()


@router.get("", response_model=List[GiftRead])
async def get_favorites(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[GiftRead]:
    """
    Список избранного текущего юзера, отсортированный по дате добавления
    (сначала свежее). Дата берётся из favorites.created_at, не из gifts.created_at.
    """
    stmt = (
        select(Gift)
        .join(favorites_table, favorites_table.c.gift_id == Gift.id)
        .where(favorites_table.c.user_id == current_user.id)
        .order_by(favorites_table.c.created_at.desc())
    )
    result = await session.execute(stmt)
    gifts = result.scalars().all()
    return [
        GiftRead.model_validate(gift, from_attributes=True).model_copy(update={"is_favorite": True})
        for gift in gifts
    ]


@router.post("/{gift_id}", response_model=GiftRead, status_code=status.HTTP_201_CREATED)
async def add_favorite(
    gift_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> GiftRead:
    """Идемпотентный add: если уже в избранном — просто вернёт текущее состояние."""
    gift = await session.get(Gift, gift_id)
    if gift is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gift not found",
        )

    if gift not in current_user.favorites:
        current_user.favorites.append(gift)
        await session.commit()
        await session.refresh(gift)

    return GiftRead.model_validate(gift, from_attributes=True).model_copy(update={"is_favorite": True})


@router.delete("/{gift_id}", response_model=GiftRead)
async def remove_favorite(
    gift_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> GiftRead:
    """Идемпотентный remove: если не в избранном — просто вернёт is_favorite=false."""
    gift = await session.get(Gift, gift_id)
    if gift is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gift not found",
        )

    if gift in current_user.favorites:
        current_user.favorites.remove(gift)
        await session.commit()
        await session.refresh(gift)

    return GiftRead.model_validate(gift, from_attributes=True).model_copy(update={"is_favorite": False})


@router.post("/{gift_id}/toggle", response_model=GiftRead)
async def toggle_favorite(
    gift_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> GiftRead:
    """
    Сохранён для обратной совместимости с текущим iOS-кодом
    (FavoritesService использует /favorites/{id}/toggle).
    Внутри — то же самое, что POST + DELETE по состоянию.
    """
    gift = await session.get(Gift, gift_id)
    if gift is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gift not found",
        )

    if gift in current_user.favorites:
        current_user.favorites.remove(gift)
        is_favorite = False
    else:
        current_user.favorites.append(gift)
        is_favorite = True

    await session.commit()
    await session.refresh(gift)

    return GiftRead.model_validate(gift, from_attributes=True).model_copy(update={"is_favorite": is_favorite})
