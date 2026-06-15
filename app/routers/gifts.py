import imghdr
import json
import uuid
from pathlib import Path
from typing import List, Optional, Sequence

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.embeddings import cosine_similarity, get_yandex_embedding, parse_embedding
from app.core.security import get_current_admin_user, get_current_user_optional
from app.core.settings import get_settings
from app.ingestion.images import get_uploads_dir
from app.models import Category, Gift, GiftEmbedding, User, favorites_table
from app.schemas.gift import GiftCreate, GiftListResponse, GiftRead
from app.services.gifts import create_gift_record

router = APIRouter()


@router.post("", response_model=GiftRead, status_code=status.HTTP_201_CREATED)
async def create_gift(
    payload: GiftCreate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_admin_user),
) -> GiftRead:
    return await create_gift_record(session, payload)


@router.post("/upload-image")
async def upload_gift_image(
    file: UploadFile = File(...),
    _: User = Depends(get_current_admin_user),
) -> dict[str, str]:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")

    kind = imghdr.what(None, content)
    suffix = ".jpg" if kind == "jpeg" else f".{kind}" if kind else Path(file.filename or "").suffix or ".jpg"
    filename = f"{uuid.uuid4().hex}{suffix}"
    target = get_uploads_dir() / filename
    target.write_bytes(content)
    return {"image_url": f"/media/{filename}"}


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
    Семантический поиск по смыслу запроса (мультиязычный).
    Использует Yandex Embeddings; при их отсутствии — ILIKE fallback.
    """
    page, per_page = _normalize_pagination(page, per_page)
    settings = get_settings()

    # ── Семантический поиск ─────────────────────────────────────────────────
    if settings.yandex_api_key and settings.yandex_folder_id:
        query_vec = await get_yandex_embedding(
            q, "text-search-query", settings.yandex_api_key, settings.yandex_folder_id
        )
        if query_vec:
            emb_result = await session.execute(select(GiftEmbedding))
            all_embeddings = emb_result.scalars().all()

            if all_embeddings:
                scored: list[tuple[int, float]] = []
                for ge in all_embeddings:
                    try:
                        gift_vec = parse_embedding(ge.embedding_json)
                        scored.append((ge.gift_id, cosine_similarity(query_vec, gift_vec)))
                    except Exception:
                        continue

                scored.sort(key=lambda x: x[1], reverse=True)
                total = len(scored)
                paged_ids = [gid for gid, _ in scored[(page - 1) * per_page : page * per_page]]

                gifts_result = await session.execute(
                    select(Gift).where(Gift.id.in_(paged_ids))
                )
                by_id = {g.id: g for g in gifts_result.scalars().all()}
                ordered = [by_id[gid] for gid in paged_ids if gid in by_id]

                favorite_ids = await _fetch_favorite_ids(session, current_user, [g.id for g in ordered])
                gifts = [
                    GiftRead.model_validate(g, from_attributes=True).model_copy(
                        update={"is_favorite": g.id in favorite_ids}
                    )
                    for g in ordered
                ]
                return GiftListResponse(gifts=gifts, total=total, page=page, per_page=per_page)

    # ── Fallback: ILIKE по названию и описанию ──────────────────────────────
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
