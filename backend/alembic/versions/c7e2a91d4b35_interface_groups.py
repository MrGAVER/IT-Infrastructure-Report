"""Группы портов устройства: interface_groups и связанные таблицы, device_interfaces.group_id

Revision ID: c7e2a91d4b35
Revises: 5b1e7c94a2d8
Create Date: 2026-09-30 00:00:00.000000

Правка формы устройства, п.4: параметры, одинаковые у многих портов (режим порта/VLAN, IP-адрес,
открытые порты), задаются один раз на группе портов и применяются ко всем её портам (см.
models.InterfaceGroup). Миграция только добавляет структуру: существующие порты остаются без
группы (group_id NULL), данные не меняются.

group_id добавляется через batch_alter_table (на SQLite это пересборка таблицы, как в прочих
миграциях проекта, добавляющих FK к существующей таблице); внешний ключ ON DELETE SET NULL.

downgrade() работает: снимает колонку/индекс/FK и удаляет три новые таблицы. Значения, уже
записанные в порты из групп, остаются на портах — теряется только принадлежность к группе и
определение самой группы.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c7e2a91d4b35"
down_revision = "5b1e7c94a2d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interface_groups",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("physical_device_id", sa.String(length=36), sa.ForeignKey("physical_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("vlan_mode", sa.String(length=10), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("prefix_length", sa.Integer(), nullable=True),
        sa.Column("manage_open_ports", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("physical_device_id", "name", name="uq_interface_groups_device_name"),
    )
    op.create_index("ix_interface_groups_physical_device_id", "interface_groups", ["physical_device_id"])

    op.create_table(
        "interface_group_vlans",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("group_id", sa.String(length=36), sa.ForeignKey("interface_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vlan_id", sa.String(length=36), sa.ForeignKey("vlans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("group_id", "vlan_id", name="uq_interface_group_vlans_group_vlan"),
    )
    op.create_index("ix_interface_group_vlans_group_id", "interface_group_vlans", ["group_id"])
    op.create_index("ix_interface_group_vlans_vlan_id", "interface_group_vlans", ["vlan_id"])

    op.create_table(
        "interface_group_open_ports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("group_id", sa.String(length=36), sa.ForeignKey("interface_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("protocol_catalog_id", sa.String(length=36), sa.ForeignKey("protocol_port_catalogs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transport_protocol", sa.String(length=10), nullable=False, server_default="TCP"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_interface_group_open_ports_group_id", "interface_group_open_ports", ["group_id"])
    op.create_index("ix_interface_group_open_ports_protocol_catalog_id", "interface_group_open_ports", ["protocol_catalog_id"])

    with op.batch_alter_table("device_interfaces") as batch:
        batch.add_column(sa.Column("group_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_device_interfaces_group", "interface_groups", ["group_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_device_interfaces_group_id", ["group_id"])


def downgrade() -> None:
    with op.batch_alter_table("device_interfaces") as batch:
        batch.drop_index("ix_device_interfaces_group_id")
        batch.drop_constraint("fk_device_interfaces_group", type_="foreignkey")
        batch.drop_column("group_id")

    op.drop_index("ix_interface_group_open_ports_protocol_catalog_id", table_name="interface_group_open_ports")
    op.drop_index("ix_interface_group_open_ports_group_id", table_name="interface_group_open_ports")
    op.drop_table("interface_group_open_ports")

    op.drop_index("ix_interface_group_vlans_vlan_id", table_name="interface_group_vlans")
    op.drop_index("ix_interface_group_vlans_group_id", table_name="interface_group_vlans")
    op.drop_table("interface_group_vlans")

    op.drop_index("ix_interface_groups_physical_device_id", table_name="interface_groups")
    op.drop_table("interface_groups")
