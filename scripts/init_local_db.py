#!/usr/bin/env python3
"""
Создаёт все таблицы в локальной SQLite (surprise.db) по текущим моделям.

Для локальной разработки без PostgreSQL используйте этот скрипт вместо
`alembic upgrade head` (старые миграции написаны под Postgres).
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.db import Base, engine
from app.core.settings import get_settings
from app.models import (  # noqa: F401
    AnalyticsEvent,
    Category,
    Gift,
    GiftCandidate,
    GiftImage,
    GiftSource,
    IngestionRun,
    User,
    favorites_table,
    gift_categories_table,
)


async def main() -> None:
    settings = get_settings()
    if not str(settings.database_url).startswith("sqlite"):
        print(
            "Внимание: SURPRISE_DATABASE_URL не SQLite. "
            "Для Postgres на сервере используйте alembic upgrade head.",
            file=sys.stderr,
        )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print(f"Готово. Таблицы созданы: {settings.database_url}")


if __name__ == "__main__":
    asyncio.run(main())
