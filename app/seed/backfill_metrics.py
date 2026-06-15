"""Reconstruct historical user activity in the database to match the MVP
testing presentation (slides 12-17) and the daily-metrics spreadsheet.

The generator is deterministic: it wipes prior non-admin users, favorites and
analytics events, then rebuilds 48 cohort-dated users plus their favorites and
a full analytics-event stream so that aggregate queries in pgAdmin reproduce
the deck figures (save rate, seller CTR, AI usage, CSAT, avg session time,
avg saved gifts, D3 retention, etc.).

Event taxonomy
--------------
Existing product events (same names the frontend emits):
    site_open, session_start, session_end, onboarding_completed,
    favorite_click (action="add"), purchase_click

New events recommended in the spreadsheet "Events to add" sheet, added here so
the metrics that the product does not yet track become measurable:
    price_filter_apply, ai_helper_open, ai_questionnaire_submit,
    ai_recommendation_shown, ai_recommendation_save, final_gift_selected,
    csat_submit, retention_cohort, seller_destination_view, completed_purchase
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnalyticsEvent, Gift, User, favorites_table
from app.seed.daily_metrics_data import DAILY

# Synthetic accounts never authenticate; this is a non-functional placeholder.
PLACEHOLDER_HASH = "$2b$12$backfillSyntheticUserNoLoginAllowedxxxxxxxxxxxxxxxxx"

# First five cohort users (1-2 May) are the internal team.
TEAM_NAMES = [
    "Малафеева Дарья",
    "Горобец Алёна",
    "Конкина Алина",
    "Кокорина Светлана",
    "Серкин Михаил",
]

BUILTIN_AVATARS = [
    "builtin://blue_star",
    "builtin://pink_heart",
    "builtin://green_leaf",
    "builtin://yellow_sun",
    "builtin://purple_moon",
]


def _dt(d: date, hour: int = 10, minute: int = 0, second: int = 0) -> datetime:
    """Timezone-aware UTC datetime inside the given day."""
    minute = minute % 60
    hour = min(hour, 23)
    return datetime(d.year, d.month, d.day, hour, minute, second, tzinfo=timezone.utc)


async def run_backfill(session: AsyncSession, wipe: bool = True) -> Dict[str, object]:
    rng = random.Random(2026)
    summary: Dict[str, object] = {}

    # ── 1. Wipe prior synthetic / real activity (admins + catalog preserved) ──
    if wipe:
        await session.execute(delete(AnalyticsEvent))
        await session.execute(delete(favorites_table))
        del_users = await session.execute(
            delete(User).where(User.is_admin.is_(False))
        )
        summary["deleted_users"] = del_users.rowcount or 0
        await session.commit()

    # ── 2. Gift pool to attach favorites / gift-referencing events to ─────────
    gift_ids: List[int] = list(
        (await session.execute(select(Gift.id).order_by(Gift.id))).scalars().all()
    )
    if not gift_ids:
        raise RuntimeError("no gifts in catalog — cannot attach favorites/events")

    # ── 3. Create all cohort users first (need ids for events/favorites) ──────
    # cohort[i] -> {"user": User, "created": date}
    cohort: List[Dict[str, object]] = []
    global_idx = 0
    for d in DAILY:
        for _ in range(d["new_users"]):
            global_idx += 1
            if global_idx <= len(TEAM_NAMES):
                name = TEAM_NAMES[global_idx - 1]
            else:
                name = f"Респондент {global_idx - len(TEAM_NAMES)}"
            created_at = _dt(d["date"], hour=9, minute=(global_idx * 7) % 60)
            user = User(
                name=name,
                email=f"mvp_user_{global_idx:03d}@surprise.test",
                phone=None,
                password_hash=PLACEHOLDER_HASH,
                is_guest=False,
                is_admin=False,
                created_at=created_at,
                avatar_url=BUILTIN_AVATARS[global_idx % len(BUILTIN_AVATARS)],
            )
            session.add(user)
            cohort.append({"user": user, "created": d["date"]})
    await session.flush()  # assign user ids

    summary["created_users"] = len(cohort)

    # Per-user cursor to keep favorites (user_id, gift_id) pairs unique.
    fav_cursor: Dict[int, int] = {}
    used_favorites: set = set()
    favorite_rows: List[dict] = []
    events: List[AnalyticsEvent] = []

    # Cycle-distinct actor allocation: for each (cycle, action) we hand out
    # distinct users so COUNT(DISTINCT user_id) over the cycle equals the deck
    # figure (the spreadsheet sums daily distinct actors, with no within-cycle
    # double counting). State persists across the cycle's days.
    cycle_state: Dict[tuple, Dict[str, object]] = {}

    def take(cycle: str, action: str, available: List[User], n: int) -> List[User]:
        st = cycle_state.setdefault((cycle, action), {"used": set(), "cursor": 0})
        used: set = st["used"]  # type: ignore[assignment]
        chosen: List[User] = []
        if not available:
            return chosen
        L = len(available)
        tries = 0
        while len(chosen) < n and tries < L * 2:
            u = available[st["cursor"] % L]  # type: ignore[index]
            st["cursor"] = st["cursor"] + 1  # type: ignore[operator]
            tries += 1
            if u.id in used:
                continue
            used.add(u.id)
            chosen.append(u)
        return chosen

    def anon_of(user: User) -> str:
        return f"anon-{user.id}"

    def add_event(name: str, when: datetime, user: User | None, **kw) -> None:
        events.append(
            AnalyticsEvent(
                event_name=name,
                event_time=when,
                user_id=user.id if user else None,
                anonymous_id=kw.get("anonymous_id"),
                session_id=kw.get("session_id"),
                gift_id=kw.get("gift_id"),
                surface=kw.get("surface"),
                action=kw.get("action"),
                path=kw.get("path"),
                duration_seconds=kw.get("duration_seconds"),
                payload=kw.get("payload"),
            )
        )

    def next_gift_for(user: User) -> int:
        """Return a gift id this user has not favorited yet (round-robin)."""
        start = fav_cursor.get(user.id, user.id) % len(gift_ids)
        for step in range(len(gift_ids)):
            gid = gift_ids[(start + step) % len(gift_ids)]
            if (user.id, gid) not in used_favorites:
                fav_cursor[user.id] = (start + step + 1) % len(gift_ids)
                used_favorites.add((user.id, gid))
                return gid
        # all gifts used by this user (won't happen at our volumes)
        return gift_ids[start]

    # ── 4. Simulate activity day by day ──────────────────────────────────────
    created_before: List[Dict[str, object]] = []  # cohort entries from prior days
    cohort_iter_idx = 0
    cycle_session_counter = 0

    for d in DAILY:
        day: date = d["date"]

        # Daily aggregate marker (no user): stores the sheet's respondents_on_day
        # and avg_saved_gifts_per_user so both can be read straight from the DB.
        add_event(
            "daily_summary",
            _dt(day, 23, 0, 0),
            None,
            payload={
                "respondents_on_day": d["respondents_on_day"],
                "avg_saved_gifts_per_user": d["avg_saved_gifts_per_user"],
            },
        )

        # today's new users (slice of cohort created on this day)
        new_today = [c for c in cohort if c["created"] == day]
        pool_before = [c["user"] for c in created_before]
        ret_n = min(d["returning_users"], len(pool_before))
        returning = rng.sample(pool_before, ret_n) if ret_n else []
        active = [c["user"] for c in new_today] + returning
        if not active:
            created_before.extend(new_today)
            continue

        logged_n = min(d["logged_in_users"], len(active))
        logged_set = set(u.id for u in active[:logged_n])

        # Pool of every user that already exists on this day (new + all prior).
        # User-level actions are allocated from here so each cycle's
        # COUNT(DISTINCT user_id) equals the deck figure.
        available = [c["user"] for c in cohort if c["created"] <= day]
        cyc = d["cycle"]

        # 4a. Traffic events: site_open / session_start / session_end
        dur_seconds = (d["avg_time_spent_min"] or 0) * 60.0
        for i in range(d["site_open_events"]):
            u = active[i % len(active)]
            cycle_session_counter += 1
            sid = f"s{u.id}-{day.isoformat()}-{i}"
            if u.id in logged_set:
                add_event("site_open", _dt(day, 10, i % 60, 5), u, session_id=sid, path="/feed")
            else:
                add_event("site_open", _dt(day, 10, i % 60, 5), None,
                          anonymous_id=anon_of(u), session_id=sid, path="/feed")
        for i in range(d["session_start_events"]):
            u = active[i % len(active)]
            sid = f"s{u.id}-{day.isoformat()}-{i}"
            if u.id in logged_set:
                add_event("session_start", _dt(day, 10, i % 60, 10), u, session_id=sid)
            else:
                add_event("session_start", _dt(day, 10, i % 60, 10), None,
                          anonymous_id=anon_of(u), session_id=sid)
        for i in range(d["session_end_events"]):
            u = active[i % len(active)]
            sid = f"s{u.id}-{day.isoformat()}-{i}"
            kw = dict(session_id=sid, duration_seconds=dur_seconds)
            if u.id in logged_set:
                add_event("session_end", _dt(day, 10, 30 + i % 29, 0), u, **kw)
            else:
                add_event("session_end", _dt(day, 10, 30 + i % 29, 0), None,
                          anonymous_id=anon_of(u), **kw)

        # 4b. Onboarding (new users only)
        for i in range(d["onboarding_completed_users"]):
            u = active[i % len(active)] if not new_today else new_today[i % len(new_today)]["user"]
            add_event("onboarding_completed", _dt(day, 9, 30 + i, 0), u, path="/onboarding")

        # 4c. Saves -> favorites table + favorite_click events
        savers = take(cyc, "saved", available, d["users_saved_gift"])
        n_fav = d["favorite_add_events"]
        if savers and n_fav:
            per = [1] * len(savers)
            extra = n_fav - len(savers)
            j = 0
            while extra > 0:
                per[j % len(savers)] += 1
                j += 1
                extra -= 1
            for s_idx, u in enumerate(savers):
                for k in range(per[s_idx]):
                    gid = next_gift_for(u)
                    when = _dt(day, 12, (s_idx * 5 + k) % 60, 0)
                    favorite_rows.append({"user_id": u.id, "gift_id": gid, "created_at": when})
                    add_event("favorite_click", when, u, gift_id=gid,
                              action="add", surface="feed")

        # 4d. Seller clicks (purchase_click) + seller_destination_view
        sellers = take(cyc, "seller", available, d["users_clicked_seller"])
        n_pc = d["purchase_click_events"]
        if sellers and n_pc:
            per = [1] * len(sellers)
            extra = n_pc - len(sellers)
            j = 0
            while extra > 0:
                per[j % len(sellers)] += 1
                j += 1
                extra -= 1
            for s_idx, u in enumerate(sellers):
                for k in range(per[s_idx]):
                    gid = gift_ids[(u.id + k) % len(gift_ids)]
                    when = _dt(day, 13, (s_idx * 4 + k) % 60, 0)
                    add_event("purchase_click", when, u, gift_id=gid, surface="gift_detail")
                    add_event("seller_destination_view", when, u, gift_id=gid,
                              surface="gift_detail")

        # 4e. Completed purchase (rare; estimated)
        for u in take(cyc, "completed", available, d["completed_purchase_users"]):
            gid = gift_ids[u.id % len(gift_ids)]
            add_event("completed_purchase", _dt(day, 14, 0, 0), u, gift_id=gid)

        # 4f. Price filter
        for i, u in enumerate(take(cyc, "price", available, d["price_filter_users"])):
            add_event("price_filter_apply", _dt(day, 11, i % 60, 0), u, surface="feed",
                      payload={"min_price": 0, "max_price": 2000})

        # 4g. AI funnel: open -> questionnaire -> shown -> save ; final selected
        for i, u in enumerate(take(cyc, "ai", available, d["ai_helper_users"])):
            base = _dt(day, 15, i % 60, 0)
            add_event("ai_helper_open", base, u, surface="feed")
            add_event("ai_questionnaire_submit", base + timedelta(seconds=30), u,
                      payload={"recipient": "friend", "occasion": "birthday"})
            add_event("ai_recommendation_shown", base + timedelta(seconds=60), u,
                      gift_id=gift_ids[u.id % len(gift_ids)], payload={"rank": 1})
        for i, u in enumerate(take(cyc, "ai_save", available, d["ai_recommendation_save_users"])):
            gid = gift_ids[(u.id + 1) % len(gift_ids)]
            add_event("ai_recommendation_save", _dt(day, 15, 30 + i % 29, 0), u, gift_id=gid)
        for i, u in enumerate(take(cyc, "final", available, d["final_gift_selected_users"])):
            gid = gift_ids[(u.id + 2) % len(gift_ids)]
            add_event("final_gift_selected", _dt(day, 16, i % 60, 0), u, gift_id=gid, surface="ai")

        # 4h. CSAT: interview respondents submit a score = cycle CSAT.
        # Distinct submitters per cycle == deck "respondents" (10/12/15/16/20/32).
        if d["csat_score"] is not None:
            for i, u in enumerate(take(cyc, "csat", available, d["respondents_on_day"])):
                add_event("csat_submit", _dt(day, 17, i % 60, 0), u,
                          payload={"score": d["csat_score"], "cycle": cyc})

        created_before.extend(new_today)

    # ── 5. D3 retention cohort markers (Cycle 6 = 40%) ───────────────────────
    # Average of returned_d3 over the emitted markers == 0.40 exactly.
    c6_day = date(2026, 6, 10)
    c6_users = [c["user"] for c in cohort if c["created"] <= c6_day][-15:]
    ret_flags = [True, True, True, True] + [False] * 6  # 4/10 = 0.40
    for i, flag in enumerate(ret_flags):
        u = c6_users[i % len(c6_users)]
        events.append(
            AnalyticsEvent(
                event_name="retention_cohort",
                event_time=_dt(c6_day, 20, i, 0),
                user_id=u.id,
                payload={
                    "cohort_date": "2026-06-06",
                    "returned_d1": True,
                    "returned_d3": flag,
                    "returned_d7": False,
                },
            )
        )

    # ── 6. Bulk persist favorites + events ───────────────────────────────────
    if favorite_rows:
        await session.execute(insert(favorites_table), favorite_rows)
    session.add_all(events)
    await session.commit()

    summary["created_favorites"] = len(favorite_rows)
    summary["created_events"] = len(events)

    # Event-name breakdown for transparency
    counts = (
        await session.execute(
            select(AnalyticsEvent.event_name, func.count())
            .group_by(AnalyticsEvent.event_name)
            .order_by(AnalyticsEvent.event_name)
        )
    ).all()
    summary["events_by_name"] = {name: n for name, n in counts}
    summary["total_users_now"] = int(
        (await session.execute(select(func.count(User.id)))).scalar_one()
    )
    summary["non_admin_users"] = int(
        (
            await session.execute(
                select(func.count(User.id)).where(User.is_admin.is_(False))
            )
        ).scalar_one()
    )
    return summary
