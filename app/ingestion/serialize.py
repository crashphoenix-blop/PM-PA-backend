from datetime import datetime, timezone
from typing import Any

from app.models.gift_candidate import GiftCandidate


def candidate_to_catalog_item(candidate: GiftCandidate) -> dict[str, Any]:
    """Формат как у API /gifts (то, что видит сайт после публикации)."""
    created = candidate.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    image_url = candidate.image_url
    return {
        "id": candidate.id,
        "candidate_id": candidate.id,
        "status": candidate.status,
        "name": candidate.name,
        "description": candidate.description,
        "price": candidate.price,
        "image_url": image_url,
        "store_name": candidate.store_name,
        "store_url": candidate.store_url,
        "created_at": created.isoformat(),
        "categories": [],
        "images": [
            {
                "url": image_url,
                "sort_order": 0,
                "is_primary": True,
            }
        ],
        "is_favorite": False,
        "source_key": candidate.source.key if getattr(candidate, "source", None) else None,
        "source_name": candidate.source.name if getattr(candidate, "source", None) else None,
    }


def build_catalog_list(candidates: list[GiftCandidate]) -> dict[str, Any]:
    return {
        "gifts": [candidate_to_catalog_item(item) for item in candidates],
        "total": len(candidates),
    }
