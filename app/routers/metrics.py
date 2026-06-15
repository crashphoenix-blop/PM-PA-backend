"""Admin endpoints for the MVP metrics backfill and verification.

POST /admin/metrics/backfill  — rebuild historical users/favorites/events
GET  /admin/metrics/summary   — recompute per-cycle metrics from the DB
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from fastapi import APIRouter, Depends, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import get_current_admin_user
from app.models import AnalyticsEvent, User, favorites_table
from app.seed.backfill_metrics import run_backfill
from app.seed.daily_metrics_data import DAILY

router = APIRouter()


def _cycle_ranges() -> Dict[str, tuple]:
    """Derive (start, end) UTC datetimes for each testing cycle from the sheet."""
    by_cycle: Dict[str, List] = {}
    for d in DAILY:
        by_cycle.setdefault(d["cycle"], []).append(d["date"])
    ranges = {}
    for cycle, dates in by_cycle.items():
        lo, hi = min(dates), max(dates)
        ranges[cycle] = (
            datetime(lo.year, lo.month, lo.day, 0, 0, 0, tzinfo=timezone.utc),
            datetime(hi.year, hi.month, hi.day, 23, 59, 59, tzinfo=timezone.utc),
        )
    return ranges


@router.post("/backfill", status_code=status.HTTP_201_CREATED)
async def backfill_metrics(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_admin_user),
) -> dict:
    """Wipe non-admin users / favorites / analytics events and rebuild the
    48-user synthetic history that matches presentation slides 12-17."""
    summary = await run_backfill(session, wipe=True)
    return summary


@router.get("/summary")
async def metrics_summary(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_admin_user),
) -> dict:
    """Recompute the deck metrics straight from the database, per cycle."""
    ranges = _cycle_ranges()

    async def distinct_users(event: str, lo: datetime, hi: datetime) -> int:
        return int(
            (
                await session.execute(
                    select(func.count(func.distinct(AnalyticsEvent.user_id))).where(
                        and_(
                            AnalyticsEvent.event_name == event,
                            AnalyticsEvent.event_time >= lo,
                            AnalyticsEvent.event_time <= hi,
                        )
                    )
                )
            ).scalar_one()
        )

    async def event_count(event: str, lo: datetime, hi: datetime) -> int:
        return int(
            (
                await session.execute(
                    select(func.count()).where(
                        and_(
                            AnalyticsEvent.event_name == event,
                            AnalyticsEvent.event_time >= lo,
                            AnalyticsEvent.event_time <= hi,
                        )
                    )
                )
            ).scalar_one()
        )

    cycles_out = []
    for cycle in ["Internal", "C1", "C2", "C3", "C4", "C5", "C6", "Follow-up"]:
        if cycle not in ranges:
            continue
        lo, hi = ranges[cycle]
        respondents = await distinct_users("csat_submit", lo, hi)
        saved = await distinct_users("favorite_click", lo, hi)
        seller = await distinct_users("purchase_click", lo, hi)
        price = await distinct_users("price_filter_apply", lo, hi)
        ai = await distinct_users("ai_helper_open", lo, hi)
        ai_save = await distinct_users("ai_recommendation_save", lo, hi)
        final = await distinct_users("final_gift_selected", lo, hi)
        fav_events = await event_count("favorite_click", lo, hi)

        # CSAT average
        csat_rows = (
            await session.execute(
                select(AnalyticsEvent.payload).where(
                    and_(
                        AnalyticsEvent.event_name == "csat_submit",
                        AnalyticsEvent.event_time >= lo,
                        AnalyticsEvent.event_time <= hi,
                    )
                )
            )
        ).scalars().all()
        scores = [r["score"] for r in csat_rows if r and "score" in r]
        csat = round(sum(scores) / len(scores), 2) if scores else None

        # avg session duration (minutes)
        durs = (
            await session.execute(
                select(AnalyticsEvent.duration_seconds).where(
                    and_(
                        AnalyticsEvent.event_name == "session_end",
                        AnalyticsEvent.event_time >= lo,
                        AnalyticsEvent.event_time <= hi,
                        AnalyticsEvent.duration_seconds.isnot(None),
                    )
                )
            )
        ).scalars().all()
        avg_time = round(sum(durs) / len(durs) / 60, 2) if durs else None

        # D3 retention (only present for C6)
        ret_rows = (
            await session.execute(
                select(AnalyticsEvent.payload).where(
                    and_(
                        AnalyticsEvent.event_name == "retention_cohort",
                        AnalyticsEvent.event_time >= lo,
                        AnalyticsEvent.event_time <= hi,
                    )
                )
            )
        ).scalars().all()
        d3_flags = [1 if (r and r.get("returned_d3")) else 0 for r in ret_rows]
        d3 = round(sum(d3_flags) / len(d3_flags), 2) if d3_flags else None

        # cumulative unique users by cycle end
        cum_users = int(
            (
                await session.execute(
                    select(func.count(User.id)).where(
                        and_(User.is_admin.is_(False), User.created_at <= hi)
                    )
                )
            ).scalar_one()
        )

        cycles_out.append(
            {
                "cycle": cycle,
                "respondents": respondents,
                "saved_users": saved,
                "save_rate": round(saved / respondents, 3) if respondents else None,
                "seller_users": seller,
                "ctr_to_seller": round(seller / respondents, 3) if respondents else None,
                "price_filter_users": price,
                "ai_users": ai,
                "ai_save_users": ai_save,
                "final_gift_selected": final,
                "csat": csat,
                "avg_time_min": avg_time,
                "avg_saved_per_user": round(fav_events / saved, 2) if saved else None,
                "d3_retention": d3,
                "cumulative_unique_users": cum_users,
            }
        )

    total_users = int(
        (
            await session.execute(
                select(func.count(User.id)).where(User.is_admin.is_(False))
            )
        ).scalar_one()
    )
    total_favorites = int(
        (await session.execute(select(func.count()).select_from(favorites_table))).scalar_one()
    )
    total_events = int(
        (await session.execute(select(func.count(AnalyticsEvent.id)))).scalar_one()
    )
    return {
        "unique_users": total_users,
        "favorites": total_favorites,
        "analytics_events": total_events,
        "cycles": cycles_out,
    }
