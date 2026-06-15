"""Admin endpoints for the MVP metrics backfill and verification.

POST /admin/metrics/backfill  — rebuild historical users/favorites/events
GET  /admin/metrics/summary   — recompute per-cycle metrics from the DB
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List

from fastapi import APIRouter, Depends, status
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import get_current_admin_user
from app.models import AnalyticsEvent, User, favorites_table
from app.seed.backfill_metrics import run_backfill
from app.seed.daily_metrics_data import DAILY

router = APIRouter()

# Single query reproducing the Excel "Cycle summary" sheet straight from the
# raw tables. Exposed verbatim via /admin/metrics/cycle-summary-sql so it can be
# copy-pasted into pgAdmin.
CYCLE_SUMMARY_SQL = """
WITH cycles (ord, cycle, period, d_start, d_end) AS (
    VALUES
        (1, 'Internal',  '01.05-02.05', TIMESTAMPTZ '2026-05-01 00:00:00+00', TIMESTAMPTZ '2026-05-02 23:59:59+00'),
        (2, 'C1',        '03.05-08.05', TIMESTAMPTZ '2026-05-03 00:00:00+00', TIMESTAMPTZ '2026-05-08 23:59:59+00'),
        (3, 'C2',        '09.05-15.05', TIMESTAMPTZ '2026-05-09 00:00:00+00', TIMESTAMPTZ '2026-05-15 23:59:59+00'),
        (4, 'C3',        '16.05-22.05', TIMESTAMPTZ '2026-05-16 00:00:00+00', TIMESTAMPTZ '2026-05-22 23:59:59+00'),
        (5, 'C4',        '23.05-29.05', TIMESTAMPTZ '2026-05-23 00:00:00+00', TIMESTAMPTZ '2026-05-29 23:59:59+00'),
        (6, 'C5',        '30.05-05.06', TIMESTAMPTZ '2026-05-30 00:00:00+00', TIMESTAMPTZ '2026-06-05 23:59:59+00'),
        (7, 'C6',        '06.06-10.06', TIMESTAMPTZ '2026-06-06 00:00:00+00', TIMESTAMPTZ '2026-06-10 23:59:59+00'),
        (8, 'Follow-up', '11.06-15.06', TIMESTAMPTZ '2026-06-11 00:00:00+00', TIMESTAMPTZ '2026-06-15 23:59:59+00')
),
ev AS (
    SELECT
        c.ord,
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name = 'csat_submit')            AS respondents,
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name = 'favorite_click')         AS saved_users,
        COUNT(*)                  FILTER (WHERE e.event_name = 'favorite_click')         AS favorite_events,
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name = 'purchase_click')         AS seller_users,
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name = 'price_filter_apply')     AS price_filter_users,
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name = 'ai_helper_open')         AS ai_users,
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name = 'ai_recommendation_save') AS ai_saved_users,
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name = 'final_gift_selected')    AS final_gift_selected,
        AVG((e.payload->>'score')::numeric) FILTER (WHERE e.event_name = 'csat_submit')  AS csat,
        AVG(e.duration_seconds) FILTER (WHERE e.event_name = 'session_end')              AS avg_time_sec,
        AVG(CASE WHEN e.payload->>'returned_d3' = 'true' THEN 1.0 ELSE 0 END)
            FILTER (WHERE e.event_name = 'retention_cohort')                             AS d3_retention
    FROM cycles c
    LEFT JOIN analytics_events e
        ON e.event_time BETWEEN c.d_start AND c.d_end
    GROUP BY c.ord
)
SELECT
    c.cycle                                                            AS "cycle",
    c.period                                                           AS "period",
    (SELECT COUNT(*) FROM users u
        WHERE u.is_admin = false AND u.created_at BETWEEN c.d_start AND c.d_end) AS "new users",
    ev.respondents                                                     AS "respondents",
    ev.saved_users                                                     AS "saved users",
    ROUND(ev.saved_users::numeric / NULLIF(ev.respondents, 0), 3)      AS "save rate",
    ev.seller_users                                                    AS "seller click users",
    ROUND(ev.seller_users::numeric / NULLIF(ev.respondents, 0), 3)     AS "CTR to seller",
    ev.price_filter_users                                              AS "price filter users",
    ev.ai_users                                                        AS "AI users",
    ROUND(ev.ai_users::numeric / NULLIF(ev.respondents, 0), 3)         AS "AI use rate",
    ev.ai_saved_users                                                  AS "AI saved users",
    ev.final_gift_selected                                             AS "final gift selected",
    ROUND(ev.csat, 2)                                                  AS "CSAT",
    ROUND((ev.avg_time_sec / 60.0)::numeric, 2)                        AS "avg time, min",
    ROUND(ev.favorite_events::numeric / NULLIF(ev.saved_users, 0), 2)  AS "avg saved gifts/user",
    ROUND(ev.d3_retention::numeric, 2)                                 AS "D3 retention",
    (SELECT COUNT(*) FROM users u
        WHERE u.is_admin = false AND u.created_at <= c.d_end)          AS "cumulative uniques at end"
FROM cycles c
JOIN ev ON ev.ord = c.ord
ORDER BY c.ord
"""

# Per-day metrics (no cycle columns). One row per calendar day of MVP testing.
DAILY_METRICS_SQL = """
WITH days AS (
    SELECT generate_series(DATE '2026-05-01', DATE '2026-06-15', INTERVAL '1 day')::date AS d
),
agg AS (
    SELECT
        days.d AS day,
        COUNT(DISTINCT COALESCE('u' || e.user_id::text, e.anonymous_id))
            FILTER (WHERE e.event_name = 'session_start')                       AS dau,
        COUNT(DISTINCT e.user_id)
            FILTER (WHERE e.event_name = 'session_start' AND e.user_id IS NOT NULL) AS logged_in_users,
        COUNT(DISTINCT e.anonymous_id)
            FILTER (WHERE e.event_name = 'session_start' AND e.user_id IS NULL)  AS anonymous_users,
        COUNT(*) FILTER (WHERE e.event_name = 'site_open')                       AS site_open_events,
        COUNT(*) FILTER (WHERE e.event_name = 'session_start')                   AS session_start_events,
        COUNT(*) FILTER (WHERE e.event_name = 'session_end')                     AS session_end_events,
        COUNT(*) FILTER (WHERE e.event_name = 'onboarding_completed')            AS onboarding_completed_users,
        COUNT(*) FILTER (WHERE e.event_name = 'favorite_click')                  AS favorite_add_events,
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name = 'favorite_click') AS users_saved_gift,
        COUNT(*) FILTER (WHERE e.event_name = 'purchase_click')                  AS purchase_click_events,
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name = 'purchase_click') AS users_clicked_seller,
        COUNT(*) FILTER (WHERE e.event_name = 'completed_purchase')              AS completed_purchase_users,
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name = 'price_filter_apply')      AS price_filter_users,
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name = 'ai_helper_open')          AS ai_helper_users,
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name = 'ai_recommendation_save')  AS ai_recommendation_save_users,
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name = 'final_gift_selected')     AS final_gift_selected_users,
        ROUND(AVG((e.payload->>'score')::numeric) FILTER (WHERE e.event_name = 'csat_submit'), 2) AS csat_score,
        ROUND((AVG(e.duration_seconds) FILTER (WHERE e.event_name = 'session_end') / 60.0)::numeric, 2) AS avg_time_spent_min,
        ROUND(AVG(CASE WHEN e.payload->>'returned_d3' = 'true' THEN 1.0 ELSE 0 END)
            FILTER (WHERE e.event_name = 'retention_cohort'), 2)                 AS retention_d3_cohort_rate
    FROM days
    LEFT JOIN analytics_events e
        ON (e.event_time AT TIME ZONE 'UTC')::date = days.d
    GROUP BY days.d
)
SELECT
    a.day AS "date",
    (SELECT COUNT(*) FROM users u
        WHERE u.is_admin = false AND (u.created_at AT TIME ZONE 'UTC')::date = a.day)  AS "new_users",
    a.dau - (SELECT COUNT(*) FROM users u
        WHERE u.is_admin = false AND (u.created_at AT TIME ZONE 'UTC')::date = a.day)  AS "returning_users",
    a.dau                                                                             AS "dau",
    (SELECT COUNT(*) FROM users u
        WHERE u.is_admin = false AND (u.created_at AT TIME ZONE 'UTC')::date <= a.day) AS "cumulative_unique_users",
    a.logged_in_users,
    a.anonymous_users,
    a.site_open_events,
    a.session_start_events,
    a.session_end_events,
    a.onboarding_completed_users,
    a.favorite_add_events,
    a.users_saved_gift,
    a.purchase_click_events,
    a.users_clicked_seller,
    a.completed_purchase_users,
    a.price_filter_users,
    a.ai_helper_users,
    a.ai_recommendation_save_users,
    a.final_gift_selected_users,
    a.csat_score,
    a.avg_time_spent_min,
    a.retention_d3_cohort_rate
FROM agg a
ORDER BY a.day
"""


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


@router.get("/cycle-summary-sql")
async def cycle_summary_sql(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_admin_user),
) -> dict:
    """Run the pgAdmin "Cycle summary" query against the DB and return its rows,
    so the exact SQL can be validated before being copy-pasted into pgAdmin."""
    result = await session.execute(text(CYCLE_SUMMARY_SQL))
    rows = []
    for m in result.mappings().all():
        rows.append({k: (float(v) if isinstance(v, Decimal) else v) for k, v in m.items()})
    return {"sql": CYCLE_SUMMARY_SQL.strip(), "rows": rows}


@router.get("/daily-sql")
async def daily_sql(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_admin_user),
) -> dict:
    """Run the pgAdmin per-day metrics query and return its rows for validation."""
    result = await session.execute(text(DAILY_METRICS_SQL))
    rows = []
    for m in result.mappings().all():
        rows.append(
            {
                k: (float(v) if isinstance(v, Decimal) else (v.isoformat() if hasattr(v, "isoformat") else v))
                for k, v in m.items()
            }
        )
    return {"rows": rows}


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
