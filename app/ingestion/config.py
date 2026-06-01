import json

DEFAULT_SOURCES: list[dict[str, object]] = [
    {
        "key": "gridmir",
        "name": "GRIDMIR",
        "base_url": "https://gridmir.com",
        "collection_urls": [
            "https://gridmir.com/collection/plakaty",
            "https://gridmir.com/collection/hudi",
        ],
    },
    {
        "key": "darkrain",
        "name": "Darkrain",
        "base_url": "https://darkrain.store",
        "collection_urls": ["https://darkrain.store/catalog/"],
    },
    {
        "key": "kutezh",
        "name": "Kutezh",
        "base_url": "https://kutezh.net",
        "collection_urls": ["https://kutezh.net/catalog/"],
    },
]


def collection_urls_to_json(urls: list[str]) -> str:
    return json.dumps(urls, ensure_ascii=False)


def collection_urls_from_json(raw: str) -> list[str]:
    data = json.loads(raw)
    if not isinstance(data, list):
        return []
    return [str(item) for item in data]
