import json
import re
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import get_current_user_optional
from app.core.settings import get_settings
from app.models import Gift, User, favorites_table
from app.schemas.ai import AIQuestionnaireRequest, AIRecommendResponse
from app.schemas.gift import GiftRead

router = APIRouter()

# IDs подарков со срочной доставкой (совпадают с URGENT_IDS на фронтенде)
URGENT_GIFT_IDS = {18, 19, 20, 21, 22, 29, 35, 39, 48, 50, 53, 57, 66, 68, 79}

# Границы бюджета по тексту чипа
_BUDGET_MAP = {
    "до 2 000": (0, 2000),
    "2 000–5 000": (2000, 5000),
    "5 000–10 000": (5000, 10000),
    "10 000–20 000": (10000, 20000),
    "20 000": (20000, None),
}


def _parse_budget(budget: str) -> tuple[int, Optional[int]]:
    for key, bounds in _BUDGET_MAP.items():
        if key in budget:
            return bounds
    return 0, None


def _build_prompt(
    recipient: str,
    occasion: str,
    budget: str,
    style: str,
    gifts: list,
    age_group: str = "",
    interests: str = "",
) -> str:
    lines = [
        f"[{g.id}] \"{g.name}\" — {int(g.price)}₽"
        + (f" — [{', '.join(c.name for c in g.categories)}]" if g.categories else "")
        for g in gifts
    ]
    catalog = "\n".join(lines)

    context = (
        f"Кому: {recipient}\n"
        f"Повод: {occasion}\n"
        f"Бюджет: {budget}\n"
        f"Стиль: {style}"
    )
    if age_group:
        context += f"\nВозраст получателя: {age_group}"
    if interests:
        context += f"\nИнтересы: {interests}"

    return (
        f"Пользователь ищет подарок.\n"
        f"{context}\n\n"
        f"Каталог (ID, название, цена, категории):\n{catalog}\n\n"
        f"Выбери 6–10 подарков, которые лучше всего подходят. "
        f"Верни ТОЛЬКО JSON-массив ID без пояснений, например: [3, 17, 42]"
    )


async def _call_yandex_gpt(prompt: str, api_key: str, folder_id: str) -> str:
    body = {
        "modelUri": f"gpt://{folder_id}/yandexgpt-lite/latest",
        "completionOptions": {"stream": False, "temperature": 0.1, "maxTokens": "300"},
        "messages": [
            {
                "role": "system",
                "text": (
                    "Ты помощник по подбору подарков. "
                    "Из каталога выбирай только те подарки, которые точно подходят под запрос. "
                    "Верни ТОЛЬКО JSON-массив целых чисел — ID подарков, без пояснений."
                ),
            },
            {"role": "user", "text": prompt},
        ],
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            headers={
                "Authorization": f"Api-Key {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
    return resp.json()["result"]["alternatives"][0]["message"]["text"]


def _parse_ids(text: str) -> List[int]:
    match = re.search(r"\[[\d,\s]+\]", text)
    if not match:
        return []
    try:
        return [int(i) for i in json.loads(match.group())]
    except (json.JSONDecodeError, ValueError):
        return []


@router.post("/recommend", response_model=AIRecommendResponse)
async def recommend_gifts(
    payload: AIQuestionnaireRequest,
    session: AsyncSession = Depends(get_session),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> AIRecommendResponse:
    settings = get_settings()
    budget_expanded = False

    if payload.is_urgent:
        # Срочные подарки — фиксированный набор ID, бюджет игнорируется
        result = await session.execute(
            select(Gift).where(Gift.id.in_(URGENT_GIFT_IDS)).order_by(Gift.created_at.desc())
        )
        candidates = list(result.scalars().all())
    else:
        min_price, max_price = _parse_budget(payload.budget)
        conditions = [Gift.price >= min_price]
        if max_price is not None:
            conditions.append(Gift.price <= max_price)

        result = await session.execute(
            select(Gift).where(and_(*conditions)).order_by(Gift.created_at.desc())
        )
        candidates = list(result.scalars().all())

        # Если в выбранном бюджете мало вариантов — расширяем до всего каталога
        if len(candidates) < 6:
            result = await session.execute(
                select(Gift).order_by(Gift.created_at.desc())
            )
            candidates = list(result.scalars().all())
            budget_expanded = True

    selected_ids: List[int] = []

    if settings.yandex_api_key and settings.yandex_folder_id and candidates:
        try:
            prompt = _build_prompt(
                payload.recipient,
                payload.occasion,
                payload.budget,
                payload.style,
                candidates,
                age_group=payload.age_group,
                interests=payload.interests,
            )
            ai_text = await _call_yandex_gpt(
                prompt, settings.yandex_api_key, settings.yandex_folder_id
            )
            selected_ids = _parse_ids(ai_text)
        except Exception:
            pass

    if not selected_ids:
        selected_ids = [g.id for g in candidates[:12]]

    id_to_gift = {g.id: g for g in candidates}
    ordered = [id_to_gift[gid] for gid in selected_ids if gid in id_to_gift]

    fav_ids: set[int] = set()
    if current_user and ordered:
        fav_result = await session.execute(
            select(favorites_table.c.gift_id).where(
                favorites_table.c.user_id == current_user.id,
                favorites_table.c.gift_id.in_([g.id for g in ordered]),
            )
        )
        fav_ids = set(fav_result.scalars().all())

    gifts_read = [
        GiftRead.model_validate(g, from_attributes=True).model_copy(
            update={"is_favorite": g.id in fav_ids}
        )
        for g in ordered
    ]

    return AIRecommendResponse(gifts=gifts_read, budget_expanded=budget_expanded)
