from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class GiftEmbedding(Base):
    __tablename__ = "gift_embeddings"

    gift_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("gifts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    embedding_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
