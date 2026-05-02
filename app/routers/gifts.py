from typing import List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import get_current_admin_user, get_current_user_optional
from app.models import Category, Gift, GiftImage, User, favorites_table
from app.schemas.gift import GiftCreate, GiftListResponse, GiftRead

router = APIRouter()


@router.post("", response_model=GiftRead, status_code=status.HTTP_201_CREATED)
async def create_gift(
    payload: GiftCreate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_admin_user),
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

    gift = Gift(
        name=payload.name,
        description=payload.description,
        price=payload.price,
        image_url=str(payload.image_url),
        store_name=payload.store_name,
        store_url=str(payload.store_url) if payload.store_url else None,
        categories=unique_categories,
    )
    session.add(gift)
    await session.flush()

    session.add(
        GiftImage(
            gift_id=gift.id,
            url=str(payload.image_url),
            sort_order=0,
            is_primary=True,
        )
    )
    await session.commit()
    await session.refresh(gift)
    return GiftRead.model_validate(gift, from_attributes=True)


@router.get("/recommended", response_model=GiftListResponse)
async def get_recommended_gifts(
    page: int = 1,
    per_page: int = 20,
    session: AsyncSession = Depends(get_session),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> GiftListResponse:
    """
    Лента рекомендованных подарков. Пока без персонализации:
    последние добавленные. Сортировка по gifts.created_at desc.
    """
    page, per_page = _normalize_pagination(page, per_page)

    base_query = select(Gift).order_by(Gift.created_at.desc())
    count_query = select(func.count(Gift.id))

    return await _paginate_gifts(
        base_query=base_query,
        count_query=count_query,
        page=page,
        per_page=per_page,
        session=session,
        current_user=current_user,
    )


@router.get("", response_model=GiftListResponse)
async def list_gifts(
    category_id: Optional[int] = Query(
        None,
        description="ID категории. Отсутствие параметра = все категории.",
    ),
    min_price: Optional[int] = Query(None, ge=0, description="Минимальная цена"),
    max_price: Optional[int] = Query(None, ge=0, description="Максимальная цена"),
    page: int = 1,
    per_page: int = 20,
    session: AsyncSession = Depends(get_session),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> GiftListResponse:
    """
    Список подарков с фильтрами по категории и цене.

    Фильтр по категории — через EXISTS-сабкуэри по gift_categories,
    чтобы не плодить дубликаты на JOIN'е.
    """
    page, per_page = _normalize_pagination(page, per_page)

    conditions = []

    if category_id is not None:
        conditions.append(Gift.categories.any(Category.id == category_id))

    if min_price is not None:
        conditions.append(Gift.price >= min_price)
    if max_price is not None:
        conditions.append(Gift.price <= max_price)

    where_clause = and_(*conditions) if conditions else None

    base_query = select(Gift)
    count_query = select(func.count(Gift.id))

    if where_clause is not None:
        base_query = base_query.where(where_clause)
        count_query = count_query.where(where_clause)

    return await _paginate_gifts(
        base_query=base_query.order_by(Gift.created_at.desc()),
        count_query=count_query,
        page=page,
        per_page=per_page,
        session=session,
        current_user=current_user,
    )


@router.get("/search", response_model=GiftListResponse)
async def search_gifts(
    q: str = Query(..., min_length=1, description="Поисковый запрос"),
    page: int = 1,
    per_page: int = 20,
    session: AsyncSession = Depends(get_session),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> GiftListResponse:
    """
    Поиск по названию и описанию (ILIKE с экранированием).
    """
    page, per_page = _normalize_pagination(page, per_page)

    ilike_pattern = f"%{q}%"

    where_clause = or_(
        Gift.name.ilike(ilike_pattern),
        Gift.description.ilike(ilike_pattern),
    )

    base_query = select(Gift).where(where_clause).order_by(Gift.created_at.desc())
    count_query = select(func.count(Gift.id)).where(where_clause)

    return await _paginate_gifts(
        base_query=base_query,
        count_query=count_query,
        page=page,
        per_page=per_page,
        session=session,
        current_user=current_user,
    )


@router.get("/{gift_id}", response_model=GiftRead)
async def get_gift(
    gift_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> GiftRead:
    """
    Детали одного подарка с галереей и категориями.
    Раньше iOS вытаскивал детали из общего списка — теперь есть прямой эндпоинт.
    """
    gift = await session.get(Gift, gift_id)
    if gift is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gift not found",
        )

    favorite_ids = await _fetch_favorite_ids(
        session=session,
        user=current_user,
        gift_ids=[gift.id],
    )

    return GiftRead.model_validate(gift, from_attributes=True).model_copy(
        update={"is_favorite": gift.id in favorite_ids}
    )


def _normalize_pagination(page: int, per_page: int) -> tuple[int, int]:
    if page < 1:
        page = 1
    if per_page < 1 or per_page > 100:
        per_page = 20
    return page, per_page


async def _fetch_favorite_ids(
    session: AsyncSession,
    user: Optional[User],
    gift_ids: Sequence[int],
) -> set[int]:
    """
    Возвращает подмножество gift_ids, лежащих в favorites текущего юзера.
    Если юзер не залогинен или список пуст — пустой set, без обращения в БД.
    """
    if user is None or not gift_ids:
        return set()
    stmt = select(favorites_table.c.gift_id).where(
        favorites_table.c.user_id == user.id,
        favorites_table.c.gift_id.in_(gift_ids),
    )
    result = await session.execute(stmt)
    return {row for row in result.scalars().all()}


async def _paginate_gifts(
    base_query,
    count_query,
    page: int,
    per_page: int,
    session: AsyncSession,
    current_user: Optional[User],
) -> GiftListResponse:
    total_result = await session.execute(count_query)
    total = int(total_result.scalar_one())

    result = await session.execute(
        base_query.offset((page - 1) * per_page).limit(per_page)
    )
    gifts_orm: List[Gift] = result.scalars().all()

    favorite_ids = await _fetch_favorite_ids(
        session=session,
        user=current_user,
        gift_ids=[g.id for g in gifts_orm],
    )

    gifts = [
        GiftRead.model_validate(gift, from_attributes=True).model_copy(
            update={"is_favorite": gift.id in favorite_ids}
        )
        for gift in gifts_orm
    ]

    return GiftListResponse(
        gifts=gifts,
        total=total,
        page=page,
        per_page=per_page,
    )
