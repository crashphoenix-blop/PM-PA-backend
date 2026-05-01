"""fix schema drift: гарантировать наличие users.avatar_url

В части БД (включая локальную dev-инстанцию и, вероятно, прод) колонка
users.avatar_url отсутствует, потому что эти базы изначально создавались
через Base.metadata.create_all в момент, когда avatar_url ещё не было
в модели User. После добавления avatar_url в модель никакой миграции,
которая бы её донакатила, не существовало — отсюда дрифт.

Эта миграция приводит схему в соответствие с моделью идемпотентно:
- если колонка уже есть (свежие деплои, где 0001 реально запускался),
  ALTER ... IF NOT EXISTS — это no-op;
- если колонки нет (стампленные базы), она будет добавлена.

Downgrade сознательно ничего не делает: мы не знаем, существовала ли
колонка до 0005 или нет, и не хотим случайно удалить данные.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-27
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(1024);"
    )


def downgrade() -> None:
    # Намеренно no-op: см. docstring модуля.
    pass
