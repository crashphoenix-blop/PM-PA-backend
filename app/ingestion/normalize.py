from __future__ import annotations

import re
from typing import Optional, Union
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse


def normalize_store_url(url: str, base_url: str = "") -> str:
    absolute = urljoin(base_url, url.strip()) if base_url else url.strip()
    parsed = urlparse(absolute)
    clean_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            urlencode(clean_query),
            "",
        )
    )


def build_dedup_key(store_url: str, base_url: str = "") -> str:
    return normalize_store_url(store_url, base_url)


def strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def parse_price_rub(value: Optional[Union[str, int, float]]) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(round(float(value))))

    normalized = str(value).replace("\xa0", " ").strip()
    match = re.search(r"(\d+(?:[.,]\d+)?)", normalized.replace(" ", ""))
    if match:
        number = match.group(1).replace(",", ".")
        return max(0, int(round(float(number))))
    return 0
