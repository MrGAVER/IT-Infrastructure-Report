"""Настройки аудита: таблица audit_settings со сроком хранения журнала

Revision ID: d6c1a8f3e594
Revises: e3b7a15c9d42
Create Date: 2026-11-15 00:00:00.000000

Таблица audit_log только растёт: запись на каждое изменение и неудачный вход, а срока хранения у неё не было. Владелец продукта принял решение:
срок хранения задаёт администратор в форме «Настройки аудита» (кнопка на экране «Журнал аудита» и в «Настройках»). Миграция создаёт для этого
синглтон-таблицу audit_settings:

* retention_days   — срок хранения в днях; 0 — не удалять; NULL — не задан в форме (действует INFRA_REGISTRY_AUDIT_RETENTION_DAYS, по умолчанию 0);
* last_cleanup_at  — когда очистка по сроку последний раз довела дело до конца (от неё считается «не чаще раза в сутки»);
* updated_at       — как у остальных таблиц настроек.

Строку миграция НЕ создаёт: без неё действуют значения по умолчанию, то есть поведение существующих установок не меняется — журнал по-прежнему не очищается.
Её создаёт приложение при первом сохранении настроек. В audit_log миграция ничего не меняет.

Миграция идемпотентна, как и соседние: таблица, которая уже есть (база создана по моделям или ревизия запущена повторно), пропускается.

downgrade() удаляет таблицу audit_settings вместе с заданным сроком; записи журнала остаются как были.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d6c1a8f3e594"
down_revision = "e3b7a15c9d42"
branch_labels = None
depends_on = None

TABLE = "audit_settings"


def _has_table(bind: sa.Connection) -> bool:
    return TABLE in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    if _has_table(op.get_bind()):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=20), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("last_cleanup_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("retention_days IS NULL OR retention_days >= 0", name="ck_audit_settings_retention_days_non_negative"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    if _has_table(op.get_bind()):
        op.drop_table(TABLE)
