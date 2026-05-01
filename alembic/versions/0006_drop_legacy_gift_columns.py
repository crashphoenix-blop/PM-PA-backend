"""drop legacy gift columns: categories (string), gallery_image_urls, tags

Финальная зачистка после того, как:
- 0002 перенесла gifts.categories (строка через запятую) в нормализованную
  пару categories + gift_categories;
- 0003 перенесла gifts.image_url в первую обложку gift_images;
- новый код (модели/роутеры/seed) больше не читает и не пишет в эти колонки
  (проверено в этапе 4г).

После этой миграции таблица gifts становится «чистой»:
id, name, description, price, image_url (cover), store_name, store_url, created_at.

Downgrade пересоздаёт удалённые колонки и реконструирует gifts.categories
из gift_categories + categories через string_agg. gallery_image_urls и tags
просто появятся пустыми (NULL) — данных для восстановления у нас нет
(gallery_image_urls всегда был NULL в исходном датасете, tags не использовался).

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("gifts", "categories")
    op.drop_column("gifts", "gallery_image_urls")
    op.drop_column("gifts", "tags")


def downgrade() -> None:
    # Возвращаем колонки в том виде, в каком они были перед дропом
    # (после миграций 0001..0005): categories — nullable VARCHAR(255),
    # остальные — nullable TEXT.
    op.add_column(
        "gifts",
        sa.Column("categories", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "gifts",
        sa.Column("gallery_image_urls", sa.Text(), nullable=True),
    )
    op.add_column(
        "gifts",
        sa.Column("tags", sa.Text(), nullable=True),
    )

    # Реконструируем строку gifts.categories из M2M.
    # Порядок имён фиксируем по алфавиту, чтобы downgrade был детерминированный.
    op.execute(
        sa.text(
            """
            UPDATE gifts g
            SET categories = sub.joined
            FROM (
                SELECT gc.gift_id,
                       string_agg(c.name, ', ' ORDER BY c.name) AS joined
                FROM gift_categories gc
                JOIN categories c ON c.id = gc.category_id
                GROUP BY gc.gift_id
            ) AS sub
            WHERE g.id = sub.gift_id;
            """
        )
    )
