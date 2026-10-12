"""Общие настройки VLAN стека (кластера): таблица device_stack_vlans

Revision ID: a7d3e9c1f452
Revises: f1a6c3d8e279
Create Date: 2026-10-12 00:00:00.000000

Один IP-адрес, префикс и признак «Управление» на VLAN для всех устройств стека (models.DeviceStackVLAN). Строка
означает, что настройка для пары «стек — VLAN» задана: значения записаны участникам стека (physical_device_vlans)
и у участников не редактируются по отдельности.

Миграция только добавляет таблицу: существующие данные не меняются, переносить нечего (раньше общих настроек стека
не было). stack_id — ON DELETE CASCADE (настройка принадлежит стеку), vlan_id — без каскада: VLAN, заданный
стеку, нельзя удалить, пока настройка не снята.

downgrade() работает: удаляет таблицу. Значения, уже записанные участникам стека в physical_device_vlans,
остаются на устройствах — после отката они просто становятся обычными редактируемыми данными.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7d3e9c1f452"
down_revision = "f1a6c3d8e279"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_stack_vlans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("stack_id", sa.String(length=36), nullable=False),
        sa.Column("vlan_id", sa.String(length=36), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("prefix_length", sa.Integer(), nullable=True),
        sa.Column("is_management", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["stack_id"], ["device_stacks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vlan_id"], ["vlans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stack_id", "vlan_id", name="uq_device_stack_vlan"),
    )
    op.create_index("ix_device_stack_vlans_stack_id", "device_stack_vlans", ["stack_id"])
    op.create_index("ix_device_stack_vlans_vlan_id", "device_stack_vlans", ["vlan_id"])


def downgrade() -> None:
    op.drop_index("ix_device_stack_vlans_vlan_id", table_name="device_stack_vlans")
    op.drop_index("ix_device_stack_vlans_stack_id", table_name="device_stack_vlans")
    op.drop_table("device_stack_vlans")
