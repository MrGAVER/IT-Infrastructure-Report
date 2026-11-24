"""Одобрение проблем проверки данных: таблица consistency_approvals

Revision ID: c9e4a71b3d58
Revises: 4e8b2d6f9a13
Create Date: 2026-11-23 00:00:00.000000

Человек может признать находку проверки данных допустимой (общий адрес VRRP, намеренный повтор имени). Одобрение привязано к отпечатку находки
(services/consistency/model.py: Finding.fingerprint), а не к строке реестра: у большинства находок «своей» записи нет. Поэтому — отдельная таблица
с уникальным отпечатком; снимок имени и текста хранится на случай, когда объекта уже нет, а одобрение осталось.

Миграция идемпотентна, как и соседние: если таблица уже есть (база создана по моделям или ревизия запущена повторно), она пропускается.

downgrade() удаляет таблицу вместе с одобрениями: после него все находки снова требуют внимания.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c9e4a71b3d58"
down_revision = "4e8b2d6f9a13"
branch_labels = None
depends_on = None

TABLE = "consistency_approvals"
INDEX = "ix_consistency_approvals_fingerprint"


def _has_table(bind: sa.Connection) -> bool:
    return TABLE in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    if _has_table(op.get_bind()):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("rule", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("entity_name", sa.String(length=500), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("approved_by", sa.String(length=150), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(INDEX, TABLE, ["fingerprint"], unique=True)


def downgrade() -> None:
    if _has_table(op.get_bind()):
        op.drop_index(INDEX, table_name=TABLE)
        op.drop_table(TABLE)
