#!/usr/bin/env python3
"""Локальный запуск парсинга подарков (без HTTP API)."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.db import SessionLocal
from app.ingestion.serialize import build_catalog_list
from app.ingestion.service import run_ingestion
from app.models.gift_candidate import GiftCandidate


async def main() -> None:
    parser = argparse.ArgumentParser(description="Сбор подарков с внешних магазинов")
    parser.add_argument(
        "--status",
        default="pending",
        help="Какие кандидаты вывести списком после прогона (по умолчанию pending)",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Только вывести список из БД, без нового прогона",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="",
        help="Сохранить список в JSON-файл (например data/ingestion_latest.json)",
    )
    args = parser.parse_args()

    async with SessionLocal() as session:
        run = None
        if not args.list_only:
            run = await run_ingestion(session, triggered_by="cli")
            print(
                f"run_id={run.id} status={run.status} "
                f"found={run.found_count} new={run.new_count} "
                f"duplicates={run.duplicate_count} errors={run.error_count}",
                file=sys.stderr,
            )
            if run.error_message:
                print(f"errors: {run.error_message}", file=sys.stderr)

        query = (
            select(GiftCandidate)
            .options(selectinload(GiftCandidate.source))
            .where(GiftCandidate.status == args.status)
            .order_by(GiftCandidate.created_at.desc())
        )
        if run is not None:
            query = query.where(GiftCandidate.run_id == run.id)

        result = await session.execute(query)
        candidates = list(result.scalars().all())
        payload = build_catalog_list(candidates)
        text = json.dumps(payload, ensure_ascii=False, indent=2)

        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text, encoding="utf-8")
            print(f"Сохранено {len(candidates)} подарков в {out_path}", file=sys.stderr)

        print(text)


if __name__ == "__main__":
    asyncio.run(main())
