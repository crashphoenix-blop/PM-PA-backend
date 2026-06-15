import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_session
from app.core.embeddings import get_yandex_embedding, gift_to_embedding_text
from app.core.security import get_current_admin_user
from app.core.settings import get_settings
from app.ingestion.service import (
    approve_candidate,
    clear_ingestion_results,
    reject_candidate,
    run_ingestion,
)
from app.models import Gift, GiftCandidate, GiftEmbedding, GiftSource, IngestionRun, User
from app.schemas.ingestion import (
    CandidateApproveRequest,
    GiftCandidateListResponse,
    GiftCandidateRead,
    IngestionClearResponse,
    IngestionRunRead,
    IngestionRunRequest,
)

router = APIRouter()


@router.post("/run", response_model=IngestionRunRead, status_code=status.HTTP_201_CREATED)
async def start_ingestion_run(
    payload: IngestionRunRequest,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_admin_user),
) -> IngestionRunRead:
    run = await run_ingestion(session, triggered_by=payload.triggered_by)
    return IngestionRunRead.model_validate(run, from_attributes=True)


@router.delete("/results", response_model=IngestionClearResponse)
async def delete_ingestion_results(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_admin_user),
) -> IngestionClearResponse:
    """Удалить все кандидаты и прогоны парсера (для отладки). Каталог gifts не меняется."""
    stats = await clear_ingestion_results(session)
    return IngestionClearResponse(**stats)


@router.get("/runs", response_model=List[IngestionRunRead])
async def list_ingestion_runs(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_admin_user),
) -> List[IngestionRunRead]:
    result = await session.execute(
        select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)
    )
    runs = result.scalars().all()
    return [IngestionRunRead.model_validate(run, from_attributes=True) for run in runs]


@router.get("/candidates/{candidate_id}", response_model=GiftCandidateRead)
async def get_candidate(
    candidate_id: int,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_admin_user),
) -> GiftCandidateRead:
    result = await session.execute(
        select(GiftCandidate)
        .options(selectinload(GiftCandidate.source))
        .where(GiftCandidate.id == candidate_id)
    )
    candidate = result.scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    return _to_candidate_read(candidate)


@router.get("/candidates", response_model=GiftCandidateListResponse)
async def list_candidates(
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_admin_user),
) -> GiftCandidateListResponse:
    query = select(GiftCandidate).options(selectinload(GiftCandidate.source))
    count_query = select(func.count(GiftCandidate.id))
    if status_filter:
        query = query.where(GiftCandidate.status == status_filter)
        count_query = count_query.where(GiftCandidate.status == status_filter)

    total = int((await session.execute(count_query)).scalar_one())
    result = await session.execute(
        query.order_by(GiftCandidate.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    candidates = result.scalars().all()
    return GiftCandidateListResponse(
        candidates=[_to_candidate_read(item) for item in candidates],
        total=total,
    )


@router.post("/candidates/{candidate_id}/approve", response_model=GiftCandidateRead)
async def approve_gift_candidate(
    candidate_id: int,
    payload: CandidateApproveRequest,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_admin_user),
) -> GiftCandidateRead:
    try:
        candidate = await approve_candidate(
            session,
            candidate_id,
            category_ids=payload.category_ids,
            category_names=payload.category_names,
            name_override=payload.name,
            description_override=payload.description,
            price_override=payload.price,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    source = await session.get(GiftSource, candidate.source_id)
    return _to_candidate_read(candidate, source)


@router.post("/reindex-embeddings")
async def reindex_embeddings(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_admin_user),
) -> dict:
    """Генерирует (или обновляет) эмбеддинги для всех подарков в каталоге."""
    settings = get_settings()
    if not settings.yandex_api_key or not settings.yandex_folder_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Yandex API не настроен")

    gifts_result = await session.execute(select(Gift))
    gifts = gifts_result.scalars().all()

    indexed = 0
    failed = 0
    for gift in gifts:
        try:
            cat_names = [c.name for c in gift.categories] if gift.categories else []
            text = gift_to_embedding_text(gift.name, gift.description or "", cat_names)
            embedding = await get_yandex_embedding(
                text, "text-search-doc", settings.yandex_api_key, settings.yandex_folder_id
            )
            if embedding:
                ge = await session.get(GiftEmbedding, gift.id)
                if ge is None:
                    ge = GiftEmbedding(gift_id=gift.id, embedding_json=json.dumps(embedding))
                    session.add(ge)
                else:
                    ge.embedding_json = json.dumps(embedding)
                await session.flush()
                indexed += 1
            else:
                failed += 1
        except Exception:
            failed += 1

    await session.commit()
    return {"indexed": indexed, "failed": failed, "total": len(gifts)}


@router.post("/candidates/{candidate_id}/reject", response_model=GiftCandidateRead)
async def reject_gift_candidate(
    candidate_id: int,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_admin_user),
) -> GiftCandidateRead:
    try:
        candidate = await reject_candidate(session, candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    source = await session.get(GiftSource, candidate.source_id)
    return _to_candidate_read(candidate, source)


def _to_candidate_read(
    candidate: GiftCandidate,
    source: Optional[GiftSource] = None,
) -> GiftCandidateRead:
    linked_source = source or getattr(candidate, "source", None)
    return GiftCandidateRead(
        id=candidate.id,
        source_id=candidate.source_id,
        run_id=candidate.run_id,
        dedup_key=candidate.dedup_key,
        name=candidate.name,
        description=candidate.description,
        price=candidate.price,
        image_url=candidate.image_url,
        store_name=candidate.store_name,
        store_url=candidate.store_url,
        status=candidate.status,
        duplicate_reason=candidate.duplicate_reason,
        published_gift_id=candidate.published_gift_id,
        created_at=candidate.created_at,
        reviewed_at=candidate.reviewed_at,
        source_key=linked_source.key if linked_source else None,
        source_name=linked_source.name if linked_source else None,
    )
