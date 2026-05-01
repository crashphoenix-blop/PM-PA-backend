"""favorites.created_at + DateTime → TIMESTAMPTZ

Финальный «таймстемп-клинап» перед дропом legacy-колонок:

1. ADD COLUMN favorites.created_at (TIMESTAMPTZ, default now(), NOT NULL).
   Существующие строки получат текущее время в момент миграции — это
   приемлемо, потому что точного «когда лайкнул» мы не сохраняли.

2. Конвертируем users.created_at и gifts.created_at из naive DateTime
   в TIMESTAMPTZ. Старые значения трактуем как UTC (это и подразумевалось
   в коде — datetime.utcnow), что задаёт USING ... AT TIME ZONE 'UTC'.

3. Добавляем server_default=now() на эти колонки. Python-уровневый
   default в моделях останется (datetime.now(timezone.utc)) — он сработает
   первым, server_default — страховка для INSERT'ов в обход ORM.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. favorites.created_at
    op.add_column(
        "favorites",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # 2. users.created_at: naive DateTime → TIMESTAMPTZ (трактуем как UTC)
    op.alter_column(
        "users",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        server_default=sa.text("now()"),
    )

    # 3. gifts.created_at: то же самое
    op.alter_column(
        "gifts",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    # Откатываем типы обратно к naive DateTime.
    # Значения сохраняются (TIMESTAMPTZ -> TIMESTAMP отбрасывает TZ-часть,
    # но сначала приведём к UTC, чтобы не получить локальное время сервера).
    op.alter_column(
        "gifts",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        server_default=None,
    )
    op.alter_column(
        "users",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
        server_default=None,
    )
    op.drop_column("favorites", "created_at")
