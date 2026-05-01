"""Category + association table для M2M с Gift.

gift_categories вынесена сюда, а не в gift.py, чтобы избежать
циклических импортов: Gift импортирует Category, Category знает
о gift_categories, а Gift через secondary='gift_categories'
ссылается на таблицу строкой — без прямого импорта.
"""
from datetime import datetime, timezone
from typing import List

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


gift_categories_table = Table(
    "gift_categories",
    Base.metadata,
    Column("gift_id", Integer, ForeignKey("gifts.id", ondelete="CASCADE"), primary_key=True),
    Column("category_id", Integer, ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True),
)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )

    # Обратная связь — список подарков в данной категории.
    # Не используется напрямую в API, но удобно для отладки и будущих фич.
    gifts: Mapped[List["Gift"]] = relationship(  # noqa: F821
        "Gift",
        secondary="gift_categories",
        back_populates="categories",
        lazy="noload",
    )
