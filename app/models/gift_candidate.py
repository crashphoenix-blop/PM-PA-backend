from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class GiftCandidate(Base):
    __tablename__ = "gift_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("gift_sources.id"), nullable=False, index=True
    )
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ingestion_runs.id"), nullable=False, index=True
    )
    dedup_key: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    image_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    store_name: Mapped[str] = mapped_column(String(255), nullable=False)
    store_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    duplicate_reason: Mapped[Optional[str]] = mapped_column(String(255))
    published_gift_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raw_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    source: Mapped["GiftSource"] = relationship("GiftSource", lazy="joined")  # noqa: F821
