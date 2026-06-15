from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.ingestion.config import (
    DEFAULT_SOURCES,
    collection_urls_from_json,
    collection_urls_to_json,
)
from app.ingestion.images import download_image_to_media
from app.ingestion.normalize import build_dedup_key
from app.ingestion.parsers import PARSERS
from app.ingestion.types import ScrapedGift
from app.models import Gift, GiftCandidate, GiftSource, IngestionRun
from app.schemas.gift import GiftCreate
from app.services.gifts import create_gift_record


async def _generate_gift_description(name: str, api_key: str, folder_id: str) -> Optional[str]:
    """Генерирует короткое описание подарка через YandexGPT. Возвращает None при любой ошибке."""
    body = {
        "modelUri": f"gpt://{folder_id}/yandexgpt-lite/latest",
        "completionOptions": {"stream": False, "temperature": 0.6, "maxTokens": "150"},
        "messages": [
            {
                "role": "system",
                "text": (
                    "Ты копирайтер для магазина подарков. "
                    "Пишешь короткие, тёплые и привлекательные описания товаров на русском языке. "
                    "2–3 предложения. Без кавычек, без лишних символов."
                ),
            },
            {
                "role": "user",
                "text": f"Напиши описание для подарка: «{name}»",
            },
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
                headers={
                    "Authorization": f"Api-Key {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
        text = resp.json()["result"]["alternatives"][0]["message"]["text"].strip()
        return text or None
    except Exception:
        return None


def _max_per_run() -> int:
    return int(os.environ.get("SURPRISE_INGESTION_MAX_PER_RUN", "100"))


def _per_source_limit(total_limit: int, sources_count: int) -> int:
    per_source = int(os.environ.get("SURPRISE_INGESTION_PER_SOURCE_LIMIT", "35"))
    if sources_count <= 0:
        return total_limit
    return min(per_source, max(1, total_limit // sources_count))


async def ensure_default_sources(session: AsyncSession) -> List[GiftSource]:
    result = await session.execute(select(GiftSource))
    existing = {source.key: source for source in result.scalars().all()}
    created: List[GiftSource] = []

    for item in DEFAULT_SOURCES:
        key = str(item["key"])
        if key in existing:
            created.append(existing[key])
            continue
        source = GiftSource(
            key=key,
            name=str(item["name"]),
            base_url=str(item["base_url"]),
            collection_urls=collection_urls_to_json(list(item["collection_urls"])),  # type: ignore[arg-type]
            is_active=True,
        )
        session.add(source)
        created.append(source)

    await session.commit()
    for source in created:
        await session.refresh(source)
    return created


async def run_ingestion(
    session: AsyncSession,
    triggered_by: str = "admin",
) -> IngestionRun:
    await ensure_default_sources(session)
    sources_result = await session.execute(
        select(GiftSource).where(GiftSource.is_active.is_(True))
    )
    sources = list(sources_result.scalars().all())

    run = IngestionRun(status="running", triggered_by=triggered_by)
    session.add(run)
    await session.flush()

    settings = get_settings()
    total_limit = _max_per_run()
    source_limit = _per_source_limit(total_limit, len(sources))
    found = 0
    new_count = 0
    duplicate_count = 0
    error_count = 0
    errors: list[str] = []

    for source in sources:
        parser_cls = PARSERS.get(source.key)
        if parser_cls is None:
            error_count += 1
            errors.append(f"unknown parser for source {source.key}")
            continue
        try:
            parser = parser_cls(
                base_url=source.base_url,
                store_name=source.name,
                collection_urls=collection_urls_from_json(source.collection_urls),
            )
            scraped_items = parser.collect(limit=source_limit)
        except Exception as exc:  # noqa: BLE001
            error_count += 1
            errors.append(f"{source.key}: {exc}")
            continue

        for scraped in scraped_items:
            found += 1
            saved, is_duplicate = await _store_candidate(
                session=session,
                source=source,
                run=run,
                scraped=scraped,
                settings=settings,
            )
            if is_duplicate:
                duplicate_count += 1
            elif saved:
                new_count += 1

    run.status = "completed" if error_count == 0 else "completed_with_errors"
    run.finished_at = datetime.now(timezone.utc)
    run.found_count = found
    run.new_count = new_count
    run.duplicate_count = duplicate_count
    run.error_count = error_count
    if errors:
        run.error_message = "; ".join(errors)[:4000]
    await session.commit()
    await session.refresh(run)
    return run


async def _store_candidate(
    session: AsyncSession,
    source: GiftSource,
    run: IngestionRun,
    scraped: ScrapedGift,
    settings=None,
) -> tuple[bool, bool]:
    dedup_key = build_dedup_key(scraped.store_url, source.base_url)
    duplicate_reason = await _detect_duplicate(session, dedup_key)
    if duplicate_reason:
        candidate = GiftCandidate(
            source_id=source.id,
            run_id=run.id,
            dedup_key=dedup_key,
            name=scraped.name[:255],
            description=scraped.description,
            price=scraped.price,
            image_url=scraped.image_url,
            store_name=scraped.store_name,
            store_url=scraped.store_url,
            status="duplicate",
            duplicate_reason=duplicate_reason,
            raw_payload=scraped.raw_payload,
        )
        session.add(candidate)
        await session.flush()
        return False, True

    # Генерируем описание через ИИ, если парсер не нашёл своё
    description = scraped.description
    if not description and settings and settings.yandex_api_key and settings.yandex_folder_id:
        description = await _generate_gift_description(
            scraped.name, settings.yandex_api_key, settings.yandex_folder_id
        )

    candidate = GiftCandidate(
        source_id=source.id,
        run_id=run.id,
        dedup_key=dedup_key,
        name=scraped.name[:255],
        description=description,
        price=scraped.price,
        image_url=scraped.image_url,
        store_name=scraped.store_name,
        store_url=scraped.store_url,
        status="pending",
        raw_payload=scraped.raw_payload,
    )
    session.add(candidate)
    await session.flush()
    return True, False


async def _detect_duplicate(session: AsyncSession, dedup_key: str):
    gifts = await session.execute(select(Gift.store_url))
    for store_url in gifts.scalars().all():
        if store_url and build_dedup_key(store_url) == dedup_key:
            return "already_published"

    pending = await session.execute(
        select(GiftCandidate).where(
            GiftCandidate.dedup_key == dedup_key,
            GiftCandidate.status.in_(("pending", "approved")),
        )
    )
    if pending.scalar_one_or_none():
        return "already_in_queue"
    return None


async def approve_candidate(
    session: AsyncSession,
    candidate_id: int,
    category_ids: Optional[List[int]] = None,
    category_names: Optional[List[str]] = None,
    name_override: Optional[str] = None,
    description_override: Optional[str] = None,
    price_override: Optional[int] = None,
) -> GiftCandidate:
    candidate = await session.get(GiftCandidate, candidate_id)
    if candidate is None:
        raise ValueError("candidate_not_found")
    if candidate.status not in ("pending", "duplicate"):
        raise ValueError("candidate_not_reviewable")

    media_url = download_image_to_media(candidate.image_url)
    payload = GiftCreate(
        name=(name_override or candidate.name).strip(),
        description=description_override if description_override is not None else candidate.description,
        price=price_override if price_override is not None else candidate.price,
        image_url=media_url,  # type: ignore[arg-type]
        store_name=candidate.store_name,
        store_url=candidate.store_url,  # type: ignore[arg-type]
        category_ids=category_ids or [],
        category_names=category_names or [],
    )
    gift = await create_gift_record(session, payload)
    candidate.status = "approved"
    candidate.published_gift_id = gift.id
    candidate.reviewed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(candidate)
    return candidate


async def reject_candidate(session: AsyncSession, candidate_id: int) -> GiftCandidate:
    candidate = await session.get(GiftCandidate, candidate_id)
    if candidate is None:
        raise ValueError("candidate_not_found")
    if candidate.status not in ("pending", "duplicate"):
        raise ValueError("candidate_not_reviewable")
    candidate.status = "rejected"
    candidate.reviewed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(candidate)
    return candidate


async def clear_ingestion_results(session: AsyncSession) -> Dict[str, int]:
    """
    Удаляет очередь парсера и журнал прогонов. Опубликованные подарки в каталоге не трогаем.
  """
    candidates_count = int(
        (await session.execute(select(func.count(GiftCandidate.id)))).scalar_one()
    )
    runs_count = int((await session.execute(select(func.count(IngestionRun.id)))).scalar_one())

    await session.execute(delete(GiftCandidate))
    await session.execute(delete(IngestionRun))
    await session.commit()

    return {
        "deleted_candidates": candidates_count,
        "deleted_runs": runs_count,
    }
