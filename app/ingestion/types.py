from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ScrapedGift:
    name: str
    price: int
    image_url: str
    store_url: str
    store_name: str
    description: Optional[str] = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
