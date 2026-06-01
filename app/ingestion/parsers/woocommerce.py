from __future__ import annotations

import re
from typing import Iterable, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.ingestion.http_client import fetch_html
from app.ingestion.normalize import parse_price_rub
from app.ingestion.types import ScrapedGift


class WooCommerceParser:
    """Парсер WooCommerce (Darkrain)."""

    def __init__(self, base_url: str, store_name: str, collection_urls: Iterable[str]) -> None:
        self.base_url = base_url.rstrip("/")
        self.store_name = store_name
        self.collection_urls = list(collection_urls)

    def collect(self, limit: int) -> List[ScrapedGift]:
        results: List[ScrapedGift] = []
        seen_urls: set[str] = set()

        for collection_url in self.collection_urls:
            page = 1
            while len(results) < limit:
                page_url = collection_url if page == 1 else f"{collection_url.rstrip('/')}/page/{page}/"
                html_text = fetch_html(page_url)
                soup = BeautifulSoup(html_text, "html.parser")
                cards = soup.select("div.card-item[data-name]")
                if not cards:
                    break

                for card in cards:
                    link = card.select_one("a.card-item__main, a[href*='/product/']")
                    if not link or not link.get("href"):
                        continue
                    store_url = urljoin(f"{self.base_url}/", link["href"])
                    if store_url in seen_urls:
                        continue
                    seen_urls.add(store_url)

                    name = (card.get("data-name") or "").strip()
                    if not name:
                        title = card.select_one(".card-item__title")
                        name = title.get_text(strip=True) if title else ""
                    price = parse_price_rub(card.get("data-price"))
                    if price <= 0:
                        price_tag = card.select_one(".card-item__price")
                        price = parse_price_rub(price_tag.get_text() if price_tag else "")

                    image_tag = card.select_one("img.product__image")
                    image_url = ""
                    if image_tag:
                        image_url = image_tag.get("data-src") or image_tag.get("src") or ""
                    if image_url.endswith("load.svg"):
                        image_url = image_tag.get("data-src") or ""

                    subtitle = card.select_one(".card-item__text")
                    description = subtitle.get_text(strip=True) if subtitle else None

                    if not name or price <= 0 or not image_url:
                        continue
                    if "скрыт" in name.lower() or "/product/skrytyj" in store_url:
                        continue

                    results.append(
                        ScrapedGift(
                            name=name,
                            price=price,
                            image_url=image_url,
                            store_url=store_url,
                            store_name=self.store_name,
                            description=description,
                            raw_payload={"woocommerce_id": card.get("data-id")},
                        )
                    )
                    if len(results) >= limit:
                        return results

                next_link = soup.select_one("a.next.page-numbers")
                if not next_link:
                    break
                page += 1

        return results
