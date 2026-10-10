"""Серверные настройки интерфейса: таблица app_preferences

Revision ID: c4a8f1d6b937
Revises: e3b7d2a9c158
Create Date: 2026-10-10 00:00:00.000000

Тема, название организации, размеры страниц списков и порог сворачивания блока «VLAN устройства» раньше
хранились только в localStorage браузера (см. models.AppPreference). Миграция только добавляет таблицу:
существующие данные не меняются. Значения из localStorage браузер переносит сам при первом открытии
приложения (frontend-vue/src/stores/preferences.ts) — на сервере их взять неоткуда.

downgrade() работает: удаляет таблицу вместе с настройками (после отката интерфейс снова читает localStorage
прежней версии, где значения остаются, если браузер их ещё не стёр).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4a8f1d6b937"
down_revision = "e3b7d2a9c158"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_preferences",
        sa.Column("owner", sa.String(length=50), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("owner", "key"),
    )


def downgrade() -> None:
    op.drop_table("app_preferences")
