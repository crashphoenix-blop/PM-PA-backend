from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Централизованные настройки backend-приложения.

    Значения читаются из переменных окружения с префиксом SURPRISE_*
    и, опционально, из файла .env в корне backend-папки.

    Локально без PostgreSQL: sqlite+aiosqlite:///./surprise.db (см. .env.example).
    Прод: postgresql+asyncpg://...
    """

    database_url: str = "sqlite+aiosqlite:///./surprise.db"

    jwt_secret_key: str = "dev_secret_key"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    yandex_api_key: str = ""
    yandex_folder_id: str = ""

    class Config:
        env_prefix = "SURPRISE_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    """
    Используем lru_cache, чтобы не пересоздавать настройки на каждый запрос.
    """

    return Settings()
