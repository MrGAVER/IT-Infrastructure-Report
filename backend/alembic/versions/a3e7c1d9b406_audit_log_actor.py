"""Автор действия в журнале аудита: actor_id, actor_username, actor_ip

Журнал фиксировал, что и когда изменилось, но не кто это сделал: при включённой
аутентификации нельзя было ответить на вопрос «кто удалил запись». Колонки nullable — существующие
записи остаются как есть (автор неизвестен), а записи действий без аутентификации получают только адрес
клиента. Внешнего ключа на users нет намеренно: запись журнала должна пережить удаление учётной записи,
поэтому имя пользователя сохраняется рядом с id.

downgrade() удаляет колонки вместе с их содержимым.

Revision ID: a3e7c1d9b406
Revises: d4b9e1a7c352
Create Date: 2026-10-05 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a3e7c1d9b406"
down_revision = "d4b9e1a7c352"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Обычный add_column, а не batch: журнал только растёт, и на SQLite пересоздавать его таблицу ради
    # трёх nullable-колонок незачем (ADD COLUMN выполняется мгновенно и на SQLite, и на PostgreSQL).
    op.add_column("audit_log", sa.Column("actor_id", sa.String(36), nullable=True))
    op.add_column("audit_log", sa.Column("actor_username", sa.String(150), nullable=True))
    op.add_column("audit_log", sa.Column("actor_ip", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("audit_log") as batch:
        batch.drop_column("actor_ip")
        batch.drop_column("actor_username")
        batch.drop_column("actor_id")
