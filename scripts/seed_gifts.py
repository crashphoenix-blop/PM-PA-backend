"""Сидинг каталога подарков из ios-app/.../gifts.json.

Идемпотентный: повторный прогон не дублирует категории/связи/обложки.
Использует новую нормализованную схему:
- Category для имён категорий
- gift_categories для M2M
- gift_images для обложек (одна строка с is_primary=true на gift)

Запуск:
  cd backend && .venv/bin/python -m scripts.seed_gifts
"""
import asyncio
import json
import os
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import Category, Gift, GiftImage, gift_categories_table

PROJECT_ROOT = Path(__file__).resolve().parents[1]
IOS_GIFTS_JSON = PROJECT_ROOT / "ios-app" / "SurpriseApp" / "Resources" / "gifts.json"
LOCAL_GIFTS_JSON = PROJECT_ROOT / "data" / "gifts.json"


def resolve_seed_file() -> Path | None:
    """
    В прод-окружении (например Amvera) папки ios-app обычно нет,
    поэтому поддерживаем несколько источников seed-файла:
    1) SURPRISE_GIFTS_JSON_PATH (явный путь через env)
    2) data/gifts.json в репозитории backend
    3) исходный путь из монорепы ios-app/.../gifts.json
    """
    env_path = os.getenv("SURPRISE_GIFTS_JSON_PATH", "").strip()
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            return candidate

    if LOCAL_GIFTS_JSON.exists():
        return LOCAL_GIFTS_JSON

    if IOS_GIFTS_JSON.exists():
        return IOS_GIFTS_JSON

    return None


async def upsert_categories(
    session: AsyncSession,
    category_records: list[dict],
) -> dict[int, Category]:
    """
    Прокидывает имена категорий из JSON в таблицу categories.
    Возвращает map: json_category_id -> Category ORM-объект.
    """
    result_map: dict[int, Category] = {}
    for record in category_records:
        json_id = record["id"]
        name = record["name"].strip()

        existing = (
            await session.execute(select(Category).where(Category.name == name))
        ).scalar_one_or_none()

        if existing is None:
            existing = Category(name=name)
            session.add(existing)
            await session.flush()  # чтобы появился id

        result_map[json_id] = existing

    return result_map


async def prune_categories(
    session: AsyncSession,
    category_records: list[dict],
) -> None:
    allowed_names = {record["name"].strip() for record in category_records if record.get("name")}
    if not allowed_names:
        return

    await session.execute(delete(Category).where(~Category.name.in_(allowed_names)))


async def upsert_gift(
    session: AsyncSession,
    item: dict,
    categories_by_json_id: dict[int, Category],
) -> None:
    gift = await session.get(Gift, item["id"])
    if gift is None:
        gift = Gift(id=item["id"])
        session.add(gift)

    gift.name = item["name"]
    gift.description = item.get("description")
    gift.price = item["price"]
    gift.image_url = item["imageURL"]
    gift.store_name = item.get("storeName")
    gift.store_url = item.get("storeURL")

    await session.flush()

    # M2M: пересобираем связи. Удаляем старые, вставляем актуальные.
    await session.execute(
        delete(gift_categories_table).where(gift_categories_table.c.gift_id == gift.id)
    )
    for cat_id in item.get("categoryIds", []):
        category = categories_by_json_id.get(cat_id)
        if category is None:
            # категория есть в gifts.json, но её нет в categories[] — пропустим
            continue
        await session.execute(
            gift_categories_table.insert().values(
                gift_id=gift.id, category_id=category.id
            )
        )

    # Обложка: оставляем одну строку gift_images с is_primary=true.
    # Чистим всё старое для этого gift'а и кладём заново.
    await session.execute(
        delete(GiftImage).where(GiftImage.gift_id == gift.id)
    )
    session.add(
        GiftImage(
            gift_id=gift.id,
            url=item["imageURL"],
            sort_order=0,
            is_primary=True,
        )
    )


async def seed(session: AsyncSession) -> None:
    seed_file = resolve_seed_file()
    if seed_file is None:
        # Не валим деплой: каталог можно заполнить через admin UI.
        return

    with seed_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    gifts_data = data.get("gifts", [])
    categories_data = data.get("categories", [])

    await prune_categories(session, categories_data)
    categories_by_json_id = await upsert_categories(session, categories_data)

    for item in gifts_data:
        await upsert_gift(session, item, categories_by_json_id)

    await session.commit()


async def main() -> None:
    async for session in get_session():
        await seed(session)
        break


if __name__ == "__main__":
    asyncio.run(main())
