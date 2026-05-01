from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import Category
from app.schemas.category import CategoryRead

router = APIRouter()


@router.get("", response_model=List[CategoryRead])
async def list_categories(
    session: AsyncSession = Depends(get_session),
) -> List[CategoryRead]:
    """
    Список всех категорий, отсортированный по имени.
    Используется на iOS для построения чипсов фильтра в FeedViewController.
    """
    stmt = select(Category).order_by(Category.name)
    result = await session.execute(stmt)
    categories = result.scalars().all()
    return [CategoryRead.model_validate(c, from_attributes=True) for c in categories]
