import imghdr
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.ingestion.http_client import DEFAULT_HEADERS


def get_uploads_dir() -> Path:
    import os

    configured = os.environ.get("SURPRISE_UPLOADS_DIR", "data/uploads")
    path = Path(configured)
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_image_to_media(source_url: str) -> str:
    """Скачивает картинку в uploads и возвращает путь вида /media/<file>."""
    with httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=60.0) as client:
        response = client.get(source_url)
        response.raise_for_status()
        content = response.content

    suffix = _guess_suffix(source_url, content)
    filename = f"{uuid.uuid4().hex}{suffix}"
    target = get_uploads_dir() / filename
    target.write_bytes(content)
    return f"/media/{filename}"


def _guess_suffix(url: str, content: bytes) -> str:
    kind = imghdr.what(None, content)
    if kind == "jpeg":
        return ".jpg"
    if kind:
        return f".{kind}"
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if path.endswith(ext):
            return ext if ext != ".jpeg" else ".jpg"
    return ".jpg"
