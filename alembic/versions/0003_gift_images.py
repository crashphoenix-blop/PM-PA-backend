"""gift_images: отдельная таблица под галерею

Создаём:
- gift_images(id, gift_id FK CASCADE, url, sort_order, is_primary, created_at)
- ix_gift_images_gift_id   — обычный индекс под лукапы по gift_id
- ux_gift_images_primary   — partial unique index, гарантирующий что у
  каждого подарка не больше одной обложки (is_primary=true).

Колонка gifts.image_url остаётся как «денормализованная обложка для
быстрых лент». Это сознательное решение, чтобы не ломать iOS-DTO
(см. обсуждение перед стартом этапа 4). Параллельно мы кладём ту же
обложку первой строкой в gift_images с is_primary=true — тогда любой
новый код может ходить только в gift_images и игнорировать legacy-поле.

Дроп gifts.gallery_image_urls и gifts.tags — в 0005, после того как
новые модели/роутеры будут проверены.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gift_images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gift_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["gift_id"], ["gifts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gift_images_gift_id", "gift_images", ["gift_id"], unique=False)

    # Не больше одной обложки на подарок. WHERE is_primary — partial index,
    # обычные галерейные строки в эту проверку не попадают.
    op.execute(
        "CREATE UNIQUE INDEX ux_gift_images_primary "
        "ON gift_images (gift_id) WHERE is_primary IS TRUE"
    )

    # Data migration: для каждой gift'ы создаём строку-обложку.
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO gift_images (gift_id, url, sort_order, is_primary)
            SELECT id, image_url, 0, TRUE
            FROM gifts
            WHERE image_url IS NOT NULL AND image_url <> '';
            """
        )
    )

    # Если в проде когда-то заполнялся gallery_image_urls в каком-то
    # формате — здесь можно было бы парсить. Сейчас seed_gifts.py всегда
    # пишет туда NULL (см. scripts/seed_gifts.py), так что переносить
    # нечего. Если ты находишь у себя непустые значения — кинь, добавим
    # парсер до 0005.


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_gift_images_primary")
    op.drop_index("ix_gift_images_gift_id", table_name="gift_images")
    op.drop_table("gift_images")
