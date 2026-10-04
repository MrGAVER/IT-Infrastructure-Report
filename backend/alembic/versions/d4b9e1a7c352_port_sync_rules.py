"""Правила автоматического согласования данных порта: таблица port_sync_rules

Правило — шаблон над парой «целевой порт ← порт-источник» (роль, режим, состояние VLAN обоих портов,
отношение между ними, действие auto / manual / ignore и что целевой порт берёт у источника), см.
services/port_sync_rules.py. Таблица создаётся пустой: стандартные правила добавляет стартовое
заполнение приложения (services/port_sync_store.ensure_default_rules) — идемпотентно, по
устойчивому коду правила, поэтому правила, появившиеся в новых версиях, подхватываются без новой
миграции, а изменённые администратором стандартные правила не перезаписываются.

Данные существующих таблиц не меняются. downgrade() удаляет таблицу вместе с правилами.

Revision ID: d4b9e1a7c352
Revises: c2f8a6d4e917
Create Date: 2026-10-03 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4b9e1a7c352"
down_revision = "c2f8a6d4e917"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "port_sync_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(64), nullable=True, unique=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("action", sa.String(10), nullable=False, server_default="auto"),
        sa.Column("target_role", sa.String(20), nullable=False, server_default="any"),
        sa.Column("target_mode", sa.String(10), nullable=False, server_default="any"),
        sa.Column("target_vlans", sa.String(10), nullable=False, server_default="any"),
        sa.Column("source_role", sa.String(20), nullable=False, server_default="any"),
        sa.Column("source_mode", sa.String(10), nullable=False, server_default="any"),
        sa.Column("source_vlans", sa.String(10), nullable=False, server_default="any"),
        sa.Column("rel_role", sa.String(10), nullable=False, server_default="any"),
        sa.Column("rel_mode", sa.String(10), nullable=False, server_default="any"),
        sa.Column("rel_vlans", sa.String(10), nullable=False, server_default="any"),
        sa.Column("apply_role", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("apply_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("vlan_policy", sa.String(10), nullable=False, server_default="keep"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_port_sync_rules_priority", "port_sync_rules", ["priority"])


def downgrade() -> None:
    op.drop_index("ix_port_sync_rules_priority", table_name="port_sync_rules")
    op.drop_table("port_sync_rules")
