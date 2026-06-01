from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Gift, GiftImage
from app.schemas.gift import GiftCreate, GiftRead


async def create_gift_record(
    session: AsyncSession,
    payload: GiftCreate,
) -> GiftRead:
    categories: List[Category] = []
    if payload.category_ids:
        existing_by_id = await session.execute(
            select(Category).where(Category.id.in_(payload.category_ids))
        )
        categories.extend(existing_by_id.scalars().all())

    for raw_name in payload.category_names:
        normalized = raw_name.strip()
        if not normalized:
            continue
        existing = await session.execute(
            select(Category).where(func.lower(Category.name) == normalized.lower())
        )
        category = existing.scalar_one_or_none()
        if category is None:
            category = Category(name=normalized)
            session.add(category)
            await session.flush()
        categories.append(category)

    unique_categories: List[Category] = []
    seen_ids: set[int] = set()
    for category in categories:
        if category.id in seen_ids:
            continue
        seen_ids.add(category.id)
        unique_categories.append(category)

    image_url = str(payload.image_url)
    store_url = str(payload.store_url) if payload.store_url else None

    gift = Gift(
        name=payload.name,
        description=payload.description,
        price=float(payload.price),
        image_url=image_url,
        store_name=payload.store_name,
        store_url=store_url,
        categories=unique_categories,
    )
    session.add(gift)
    await session.flush()
    session.add(
        GiftImage(
            gift_id=gift.id,
            url=image_url,
            sort_order=0,
            is_primary=True,
        )
    )
    await session.commit()
    await session.refresh(gift)
    return GiftRead.model_validate(gift, from_attributes=True)
