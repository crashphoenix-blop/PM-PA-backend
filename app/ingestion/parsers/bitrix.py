from __future__ import annotations

import re
from typing import Iterable, List
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.ingestion.http_client import fetch_html
from app.ingestion.normalize import parse_price_rub
from app.ingestion.types import ScrapedGift


class BitrixParser:
    """Парсер каталога Bitrix (Kutezh)."""

    PRODUCT_PATH_RE = re.compile(r"^/catalog/[^/?#]+/[^/?#]+/?$")

    def __init__(self, base_url: str, store_name: str, collection_urls: Iterable[str]) -> None:
        self.base_url = base_url.rstrip("/")
        self.store_name = store_name
        self.collection_urls = list(collection_urls)

    def collect(self, limit: int) -> List[ScrapedGift]:
        product_urls: list[str] = []
        seen: set[str] = set()

        for collection_url in self.collection_urls:
            html_text = fetch_html(collection_url)
            for match in re.finditer(r'href="(/catalog/[^"?#]+)"', html_text):
                path = match.group(1)
                if not self.PRODUCT_PATH_RE.match(path):
                    continue
                absolute = urljoin(f"{self.base_url}/", path)
                if absolute in seen:
                    continue
                seen.add(absolute)
                product_urls.append(absolute)
                if len(product_urls) >= limit:
                    break
            if len(product_urls) >= limit:
                break

        results: List[ScrapedGift] = []
        for product_url in product_urls[:limit]:
            try:
                scraped = self._parse_product_page(product_url)
            except Exception:
                continue
            if scraped:
                results.append(scraped)
        return results

    def _parse_product_page(self, product_url: str):
        html_text = fetch_html(product_url)
        soup = BeautifulSoup(html_text, "html.parser")

        title_tag = soup.select_one("h1.product-card__title, h1.page-card__title")
        if not title_tag:
            og_title = soup.find("meta", property="og:title")
            name = og_title["content"].strip() if og_title and og_title.get("content") else ""
        else:
            name = title_tag.get_text(strip=True)
        if not name:
            return None

        price = 0
        price_tag = soup.select_one(".product-card__price:not(.product-card__price-old)")
        if price_tag:
            price = parse_price_rub(price_tag.get_text())
        if price <= 0:
            meta_price = soup.find("meta", itemprop="price")
            if meta_price and meta_price.get("content"):
                price = parse_price_rub(meta_price["content"])

        image_url = ""
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            image_url = og_image["content"].strip()
        if not image_url:
            img = soup.select_one(".product-card__gallery img, .page-card__image img")
            if img:
                image_url = img.get("data-src") or img.get("src") or ""

        if price <= 0 or not image_url:
            return None

        path = urlparse(product_url).path
        return ScrapedGift(
            name=name,
            price=price,
            image_url=image_url,
            store_url=product_url,
            store_name=self.store_name,
            raw_payload={"path": path},
        )
