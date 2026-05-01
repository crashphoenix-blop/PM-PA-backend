"""normalize categories: dedicated table + M2M

Создаём:
- categories(id, name UNIQUE, created_at)
- gift_categories(gift_id, category_id) с composite PK и FK on delete cascade

Затем парсим строку gifts.categories ('Игрушки, Декор') и наполняем
обе таблицы. После этого делаем gifts.categories nullable, чтобы новый
ORM-код, который больше не пишет в эту колонку, не падал на NOT NULL.

Сама колонка gifts.categories в этой миграции НЕ дропается — это будет
сделано в 0005, после того как новые модели/роутеры будут проверены.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. categories
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_categories_id", "categories", ["id"], unique=False)

    # 2. gift_categories (M2M)
    op.create_table(
        "gift_categories",
        sa.Column("gift_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["gift_id"], ["gifts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("gift_id", "category_id"),
    )
    op.create_index(
        "ix_gift_categories_category_id",
        "gift_categories",
        ["category_id"],
        unique=False,
    )

    # 3. data migration: распарсить старую строковую колонку
    connection = op.get_bind()

    # 3a. наполнить categories уникальными именами
    connection.execute(
        sa.text(
            """
            INSERT INTO categories (name)
            SELECT DISTINCT trim(cat_name)
            FROM gifts, unnest(string_to_array(categories, ',')) AS cat_name
            WHERE categories IS NOT NULL
              AND categories <> ''
              AND trim(cat_name) <> ''
            ON CONFLICT (name) DO NOTHING;
            """
        )
    )

    # 3b. наполнить связь gift_categories
    connection.execute(
        sa.text(
            """
            INSERT INTO gift_categories (gift_id, category_id)
            SELECT DISTINCT g.id, c.id
            FROM gifts g, unnest(string_to_array(g.categories, ',')) AS cat_name
            JOIN categories c ON c.name = trim(cat_name)
            WHERE g.categories IS NOT NULL
              AND g.categories <> ''
              AND trim(cat_name) <> ''
            ON CONFLICT DO NOTHING;
            """
        )
    )

    # 4. ослабляем NOT NULL у legacy-колонки, чтобы новые ORM-инсерты
    # не были обязаны её заполнять. Дроп будет в 0005.
    op.alter_column("gifts", "categories", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    # Возвращаем NOT NULL только если все строки имеют значение —
    # иначе ALTER упадёт. На локальных данных всё непустое, на проде
    # тоже (этот столбец заполнял create_all + seed). Если что-то
    # вставили пустое после 0002 — придётся почистить руками.
    op.alter_column("gifts", "categories", existing_type=sa.String(length=255), nullable=False)
    op.drop_index("ix_gift_categories_category_id", table_name="gift_categories")
    op.drop_table("gift_categories")
    op.drop_index("ix_categories_id", table_name="categories")
    op.drop_table("categories")
