from functools import lru_cache

from pydantic import AnyUrl
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Централизованные настройки backend-приложения.

    Значения читаются из переменных окружения с префиксом SURPRISE_*
    и, опционально, из файла .env в корне backend-папки.
    """

    database_url: AnyUrl = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/surprise"
    )

    jwt_secret_key: str = "dev_secret_key"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

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
