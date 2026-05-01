"""initial schema (baseline)

Эта миграция фиксирует текущее состояние БД, которое раньше создавалось
через Base.metadata.create_all. На уже работающих БД её НЕ нужно прогонять
через upgrade — достаточно `alembic stamp head`, чтобы пометить их как
находящиеся на этой ревизии. На пустой БД `alembic upgrade head` создаст
все три таблицы.

Revision ID: 0001
Revises:
Create Date: 2026-04-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_guest", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("avatar_url", sa.String(length=1024), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("phone"),
    )
    op.create_index("ix_users_id", "users", ["id"], unique=False)
    op.create_index("ix_users_email", "users", ["email"], unique=False)
    op.create_index("ix_users_phone", "users", ["phone"], unique=False)

    # gifts
    op.create_table(
        "gifts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("categories", sa.String(length=255), nullable=False),
        sa.Column("image_url", sa.String(length=1024), nullable=False),
        sa.Column("gallery_image_urls", sa.Text(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("store_name", sa.String(length=255), nullable=True),
        sa.Column("store_url", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gifts_id", "gifts", ["id"], unique=False)

    # favorites (M2M users <-> gifts)
    op.create_table(
        "favorites",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("gift_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["gift_id"], ["gifts.id"]),
        sa.PrimaryKeyConstraint("user_id", "gift_id"),
    )


def downgrade() -> None:
    op.drop_table("favorites")
    op.drop_index("ix_gifts_id", table_name="gifts")
    op.drop_table("gifts")
    op.drop_index("ix_users_phone", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
