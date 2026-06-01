"""add gift ingestion tables

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gift_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("collection_urls", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index(op.f("ix_gift_sources_id"), "gift_sources", ["id"], unique=False)

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("triggered_by", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("found_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ingestion_runs_id"), "ingestion_runs", ["id"], unique=False)

    op.create_table(
        "gift_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("dedup_key", sa.String(length=1024), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("image_url", sa.String(length=2048), nullable=False),
        sa.Column("store_name", sa.String(length=255), nullable=False),
        sa.Column("store_url", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("duplicate_reason", sa.String(length=255), nullable=True),
        sa.Column("published_gift_id", sa.Integer(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["ingestion_runs.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["gift_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_gift_candidates_id"), "gift_candidates", ["id"], unique=False)
    op.create_index("ix_gift_candidates_dedup_key", "gift_candidates", ["dedup_key"], unique=False)
    op.create_index(op.f("ix_gift_candidates_status"), "gift_candidates", ["status"], unique=False)
    op.create_index(op.f("ix_gift_candidates_source_id"), "gift_candidates", ["source_id"], unique=False)
    op.create_index(op.f("ix_gift_candidates_run_id"), "gift_candidates", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_gift_candidates_run_id"), table_name="gift_candidates")
    op.drop_index(op.f("ix_gift_candidates_source_id"), table_name="gift_candidates")
    op.drop_index(op.f("ix_gift_candidates_status"), table_name="gift_candidates")
    op.drop_index(op.f("ix_gift_candidates_dedup_key"), table_name="gift_candidates")
    op.drop_index(op.f("ix_gift_candidates_id"), table_name="gift_candidates")
    op.drop_table("gift_candidates")
    op.drop_index(op.f("ix_ingestion_runs_id"), table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    op.drop_index(op.f("ix_gift_sources_id"), table_name="gift_sources")
    op.drop_table("gift_sources")
