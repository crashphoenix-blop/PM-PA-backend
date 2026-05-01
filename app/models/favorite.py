"""Association table users <-> gifts c метаданными.

Сейчас держим favorites как plain Table, а не Association Object —
этого достаточно для текущих потребностей: нам нужен created_at для
сортировки в /favorites и для возможного использования iOS-стороной
(там в Core Data есть FavoriteEntity.createdAt).

Если позже понадобится обращаться к favorites через relationship
с доступом к created_at (например, user.favorites_with_meta), можно
переехать на Association Object — это будет аддитивный рефакторинг.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Table, func

from app.core.db import Base


favorites_table = Table(
    "favorites",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("gift_id", Integer, ForeignKey("gifts.id"), primary_key=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
)
