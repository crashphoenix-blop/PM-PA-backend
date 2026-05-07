"""add analytics events table

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_name", sa.String(length=64), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("anonymous_id", sa.String(length=64), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("gift_id", sa.Integer(), nullable=True),
        sa.Column("surface", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=True),
        sa.Column("path", sa.String(length=255), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analytics_events_id"), "analytics_events", ["id"], unique=False)
    op.create_index(op.f("ix_analytics_events_event_name"), "analytics_events", ["event_name"], unique=False)
    op.create_index(op.f("ix_analytics_events_event_time"), "analytics_events", ["event_time"], unique=False)
    op.create_index(op.f("ix_analytics_events_user_id"), "analytics_events", ["user_id"], unique=False)
    op.create_index(op.f("ix_analytics_events_anonymous_id"), "analytics_events", ["anonymous_id"], unique=False)
    op.create_index(op.f("ix_analytics_events_session_id"), "analytics_events", ["session_id"], unique=False)
    op.create_index(op.f("ix_analytics_events_gift_id"), "analytics_events", ["gift_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_analytics_events_gift_id"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_session_id"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_anonymous_id"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_user_id"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_event_time"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_event_name"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_id"), table_name="analytics_events")
    op.drop_table("analytics_events")
