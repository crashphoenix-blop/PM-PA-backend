"""Gift — основная сущность каталога.

После рефакторинга к нормализованной БД:
- categories — отношение M2M через gift_categories (см. category.py)
- images — список GiftImage с отдельной обложкой (см. gift_image.py)
- liked_by — обратное отношение через favorites (см. favorite.py)

В БД ещё лежат legacy-колонки `categories: VARCHAR`, `gallery_image_urls`,
`tags` — они будут дропнуты в миграции 0005. ORM их сюда не маппит,
SQLAlchemy игнорирует «лишние» колонки в БД.
"""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Gift(Base):
    __tablename__ = "gifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    image_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    store_name: Mapped[Optional[str]] = mapped_column(String(255))
    store_url: Mapped[Optional[str]] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )

    # M2M к Category через gift_categories
    categories: Mapped[List["Category"]] = relationship(  # noqa: F821
        "Category",
        secondary="gift_categories",
        back_populates="gifts",
        lazy="selectin",
    )

    # Галерея картинок (одна из них с is_primary=true — обложка)
    images: Mapped[List["GiftImage"]] = relationship(  # noqa: F821
        "GiftImage",
        back_populates="gift",
        order_by="GiftImage.sort_order",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    # Обратная сторона M2M к User через favorites
    liked_by: Mapped[List["User"]] = relationship(  # noqa: F821
        "User",
        secondary="favorites",
        back_populates="favorites",
        lazy="selectin",
    )
