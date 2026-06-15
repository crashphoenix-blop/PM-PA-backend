from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.ingestion.config import (
    DEFAULT_SOURCES,
    collection_urls_from_json,
    collection_urls_to_json,
)
from app.ingestion.http_client import DEFAULT_HEADERS
from app.ingestion.images import download_image_to_media
from app.ingestion.normalize import build_dedup_key
from app.ingestion.parsers import PARSERS
from app.ingestion.types import ScrapedGift
from app.core.embeddings import get_yandex_embedding, gift_to_embedding_text
from app.models import Gift, GiftCandidate, GiftEmbedding, GiftSource, IngestionRun
from app.schemas.gift import GiftCreate
from app.services.gifts import create_gift_record

# CSS-селекторы, в которых обычно лежит описание товара
_DESC_SELECTORS = [
    "[itemprop='description']",
    ".product-description", ".product__description",
    ".product-detail__description", ".product-info__description",
    ".product__content", ".product-body__description",
    ".woocommerce-product-details__short-description",
    ".description__text", ".card-item__text",
    "#description", "#product-description",
]

_SYSTEM_PROMPT = """\
Ты копирайтер для магазина подарков SURPRISE. Твоя задача — написать короткое, живое описание товара на основе текста со страницы продавца.

Стиль, которому нужно следовать (реальные примеры из нашего каталога):
— Кольцо ручной работы из эпоксидной смолы, усыпанное стеклянными стразами.
— Ретро джемпер с клубничками. Согреет тебя изнутри и снаружи.
— Керамическая чайная пара в розовом цвете. Объём 400 мл. Можно мыть в посудомоечной машине.
— Игра Пурпур Отношения — «Легальный» способ задать волнующие вопросы, выровнять ожидания и понять друг друга.
— Обложка из льняной ткани с вышивкой. Подходит для книг серий «Эксклюзивная классика», «Азбука классика».
— Мозаичный подстаканник на основе натурального камня. Используется как подставка под украшения, свечи, вазы. Размер: 10×10 см.

Правила:
• 2–3 предложения
• Включи: из чего сделан, ключевые особенности, для чего или для кого подходит
• Исключи: цены, доставку, скидки, призывы купить, название магазина
• Только обычный текст — никаких маркеров, HTML, символов, кавычек в начале/конце
• Язык: русский\
"""


def _extract_product_content(html: str, name: str) -> str:
    """
    Умный экстрактор описания товара.
    Приоритеты: JSON-LD → целевые CSS-селекторы → мета-тег → общий текст.
    """
    soup = BeautifulSoup(html, "html.parser")

    parts: list[str] = []

    # 1. JSON-LD структурированные данные (самый надёжный источник)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "Product":
                    for field in ("description", "abstract"):
                        val = item.get(field, "")
                        if val:
                            parts.append(re.sub(r"\s+", " ", str(val).strip())[:800])
                    for field in ("material", "color", "size", "weight"):
                        val = item.get(field, "")
                        if val:
                            parts.append(f"{field}: {val}")
        except Exception:
            continue

    if parts:
        return " ".join(parts)[:2000]

    # 2. CSS-селекторы описания товара
    for selector in _DESC_SELECTORS:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text)
            if len(text) > 30:
                return text[:2000]

    # 3. Meta description
    meta = soup.find("meta", attrs={"name": "description"}) or \
           soup.find("meta", attrs={"property": "og:description"})
    if meta and meta.get("content", ""):  # type: ignore[union-attr]
        return str(meta["content"]).strip()[:500]  # type: ignore[index]

    # 4. Общий текст страницы (последний resort)
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text)[:2000]


async def _generate_gift_description(
    name: str,
    store_url: str,
    yandex_api_key: str,
    yandex_folder_id: str,
) -> Optional[str]:
    """
    Загружает страницу продавца, умно извлекает текст описания
    и генерирует описание через YandexGPT.
    """
    # Загружаем страницу
    page_content = ""
    try:
        async with httpx.AsyncClient(
            headers=DEFAULT_HEADERS, follow_redirects=True, timeout=20.0
        ) as client:
            resp = await client.get(store_url)
            resp.raise_for_status()
            page_content = _extract_product_content(resp.text, name)
    except Exception:
        pass

    user_prompt = (
        f"Товар: «{name}»\n\n"
        f"Текст со страницы продавца:\n{page_content}\n\n"
        "Напиши описание товара в нашем стиле, опираясь на текст выше."
    )

    body = {
        "modelUri": f"gpt://{yandex_folder_id}/yandexgpt/latest",
        "completionOptions": {"stream": False, "temperature": 0.4, "maxTokens": "250"},
        "messages": [
            {"role": "system", "text": _SYSTEM_PROMPT},
            {"role": "user", "text": user_prompt},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
                headers={
                    "Authorization": f"Api-Key {yandex_api_key}",
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

    # AI загружает страницу продавца и пишет описание
    description = scraped.description
    if settings and settings.yandex_api_key and settings.yandex_folder_id:
        description = await _generate_gift_description(
            name=scraped.name,
            store_url=scraped.store_url,
            yandex_api_key=settings.yandex_api_key,
            yandex_folder_id=settings.yandex_folder_id,
        ) or scraped.description

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

    # Генерируем эмбеддинг для семантического поиска (fire-and-forget, не блокируем ответ)
    try:
        emb_settings = get_settings()
        if emb_settings.yandex_api_key and emb_settings.yandex_folder_id:
            cat_names = [c.name for c in gift.categories]
            text = gift_to_embedding_text(gift.name, gift.description or "", cat_names)
            embedding = await get_yandex_embedding(
                text, "text-search-doc", emb_settings.yandex_api_key, emb_settings.yandex_folder_id
            )
            if embedding:
                ge = await session.get(GiftEmbedding, gift.id)
                if ge is None:
                    ge = GiftEmbedding(gift_id=gift.id, embedding_json=json.dumps(embedding))
                    session.add(ge)
                else:
                    ge.embedding_json = json.dumps(embedding)
                    ge.updated_at = datetime.now(timezone.utc)
                await session.commit()
    except Exception:
        pass

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
