from __future__ import annotations

import json
import math
from typing import Optional

import httpx


async def get_yandex_embedding(
    text: str,
    model_type: str,
    api_key: str,
    folder_id: str,
) -> Optional[list[float]]:
    """Получить вектор-эмбеддинг текста через Yandex Foundation Models."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding",
                headers={
                    "Authorization": f"Api-Key {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "modelUri": f"emb://{folder_id}/{model_type}/latest",
                    "text": text,
                },
            )
            resp.raise_for_status()
        return resp.json()["embedding"]
    except Exception:
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def gift_to_embedding_text(name: str, description: str = "", categories: list[str] | None = None) -> str:
    """Собрать текст подарка для индексации: имя + описание + категории."""
    parts = [name]
    if description:
        parts.append(description)
    if categories:
        parts.append(", ".join(categories))
    return " | ".join(parts)


def parse_embedding(json_str: str) -> list[float]:
    return json.loads(json_str)
