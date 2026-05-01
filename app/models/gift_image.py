"""Галерея картинок подарка.

Одна обложка (is_primary=true) + опциональные дополнительные кадры.
Уникальность обложки на подарок гарантируется partial unique index'ом
ux_gift_images_primary, см. миграцию 0003.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class GiftImage(Base):
    __tablename__ = "gift_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gift_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("gifts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )

    gift: Mapped["Gift"] = relationship(  # noqa: F821
        "Gift",
        back_populates="images",
    )
