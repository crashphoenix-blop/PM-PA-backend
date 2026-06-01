import httpx

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SurpriseGiftIngestion/1.0; +https://surprise.local/bot)"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}


def fetch_html(url: str, timeout: float = 30.0) -> str:
    with httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text
