from __future__ import annotations

import html
import json
import re
from typing import Iterable, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.ingestion.http_client import fetch_html
from app.ingestion.normalize import parse_price_rub, strip_html
from app.ingestion.types import ScrapedGift


class InsalesParser:
    """Парсер магазинов на Insales (Gridmir)."""

    def __init__(self, base_url: str, store_name: str, collection_urls: Iterable[str]) -> None:
        self.base_url = base_url.rstrip("/")
        self.store_name = store_name
        self.collection_urls = list(collection_urls)

    def collect(self, limit: int) -> List[ScrapedGift]:
        product_paths: list[str] = []
        seen_paths: set[str] = set()

        for collection_url in self.collection_urls:
            page_html = fetch_html(collection_url)
            for match in re.finditer(r'href="(/product/[^"?#]+)"', page_html):
                path = match.group(1)
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                product_paths.append(path)
                if len(product_paths) >= limit:
                    break
            if len(product_paths) >= limit:
                break

        results: List[ScrapedGift] = []
        for path in product_paths[:limit]:
            product_url = urljoin(f"{self.base_url}/", path)
            try:
                scraped = self._parse_product_page(product_url)
            except Exception:
                continue
            if scraped:
                results.append(scraped)
        return results

    def _parse_product_page(self, product_url: str) -> ScrapedGift | None:
        page_html = fetch_html(product_url)
        payload = self._extract_product_json(page_html)
        if payload:
            return self._from_product_json(payload, product_url)

        soup = BeautifulSoup(page_html, "html.parser")
        title_tag = soup.find("meta", property="og:title")
        image_tag = soup.find("meta", property="og:image")
        if not title_tag or not title_tag.get("content"):
            return None
        name = title_tag["content"].strip()
        image_url = image_tag["content"].strip() if image_tag and image_tag.get("content") else ""
        price = 0
        for script in soup.find_all("script"):
            text = script.string or ""
            price_match = re.search(r'"price":\s*([0-9.]+)', text)
            if price_match:
                price = parse_price_rub(price_match.group(1))
                break
        if not image_url or not price:
            return None
        return ScrapedGift(
            name=name,
            price=price,
            image_url=image_url,
            store_url=product_url,
            store_name=self.store_name,
        )

    def _extract_product_json(self, page_html: str):
        match = re.search(r'data-product-json="([^"]+)"', page_html)
        if not match:
            return None
        decoded = html.unescape(match.group(1))
        return json.loads(decoded)

    def _from_product_json(self, payload: dict, product_url: str):
        title = (payload.get("title") or "").strip()
        if not title:
            return None
        price = parse_price_rub(payload.get("price_min") or payload.get("price_max") or 0)
        if price <= 0 and payload.get("variants"):
            prices = [
                parse_price_rub(variant.get("price"))
                for variant in payload["variants"]
                if variant.get("price")
            ]
            price = min(prices) if prices else 0
        if price <= 0:
            return None

        image_url = ""
        first_image = payload.get("first_image") or {}
        if isinstance(first_image, dict):
            image_url = first_image.get("original_url") or first_image.get("large_url") or ""
        if not image_url and payload.get("images"):
            image_url = payload["images"][0].get("original_url") or ""

        description = strip_html(payload.get("short_description") or "")
        return ScrapedGift(
            name=title,
            price=price,
            image_url=image_url,
            store_url=product_url,
            store_name=self.store_name,
            description=description or None,
            raw_payload={"insales_product_id": payload.get("id")},
        )
