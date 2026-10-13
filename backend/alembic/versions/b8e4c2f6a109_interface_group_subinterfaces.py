"""Подинтерфейсы групп портов: флаг interface_groups.manage_subinterfaces и три таблицы шаблонов

Revision ID: b8e4c2f6a109
Revises: a7d3e9c1f452
Create Date: 2026-10-13 00:00:00.000000

Группа портов может задавать подинтерфейсы всех своих портов (models.InterfaceGroupSubinterface): VLAN, роль, описание,
общие IP-адреса и открытые порты. Значения записываются в каждый порт группы как обычные подинтерфейсы
(models.DeviceSubinterface) — отчёты и схемы читают их у портов.

Миграция только добавляет структуру: существующие группы получают manage_subinterfaces = false и подинтерфейсов своих
портов по-прежнему не трогают. Все связи шаблона — ON DELETE CASCADE (группа → подинтерфейс → его IP и открытые порты);
vlan_id — без каскада: VLAN, на котором есть подинтерфейс группы, удалить нельзя.

downgrade() работает: удаляет таблицы шаблонов и флаг. Подинтерфейсы, уже записанные в порты, остаются обычными данными портов.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8e4c2f6a109"
down_revision = "a7d3e9c1f452"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("interface_groups") as batch:
        batch.add_column(sa.Column("manage_subinterfaces", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "interface_group_subinterfaces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("group_id", sa.String(length=36), nullable=False),
        sa.Column("vlan_id", sa.String(length=36), nullable=False),
        sa.Column("is_management", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_data_transfer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["interface_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vlan_id"], ["vlans.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interface_group_subinterfaces_group_id", "interface_group_subinterfaces", ["group_id"])
    op.create_index("ix_interface_group_subinterfaces_vlan_id", "interface_group_subinterfaces", ["vlan_id"])

    op.create_table(
        "interface_group_subinterface_ips",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subinterface_id", sa.String(length=36), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=False),
        sa.Column("prefix_length", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["subinterface_id"], ["interface_group_subinterfaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interface_group_subinterface_ips_subinterface_id", "interface_group_subinterface_ips", ["subinterface_id"])

    op.create_table(
        "interface_group_subinterface_open_ports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subinterface_id", sa.String(length=36), nullable=False),
        sa.Column("protocol_catalog_id", sa.String(length=36), nullable=False),
        sa.Column("transport_protocol", sa.String(length=10), nullable=False, server_default="TCP"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["subinterface_id"], ["interface_group_subinterfaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["protocol_catalog_id"], ["protocol_port_catalogs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interface_group_subinterface_open_ports_subinterface_id", "interface_group_subinterface_open_ports", ["subinterface_id"])
    op.create_index("ix_interface_group_subinterface_open_ports_protocol_catalog_id", "interface_group_subinterface_open_ports", ["protocol_catalog_id"])


def downgrade() -> None:
    op.drop_index("ix_interface_group_subinterface_open_ports_protocol_catalog_id", table_name="interface_group_subinterface_open_ports")
    op.drop_index("ix_interface_group_subinterface_open_ports_subinterface_id", table_name="interface_group_subinterface_open_ports")
    op.drop_table("interface_group_subinterface_open_ports")
    op.drop_index("ix_interface_group_subinterface_ips_subinterface_id", table_name="interface_group_subinterface_ips")
    op.drop_table("interface_group_subinterface_ips")
    op.drop_index("ix_interface_group_subinterfaces_vlan_id", table_name="interface_group_subinterfaces")
    op.drop_index("ix_interface_group_subinterfaces_group_id", table_name="interface_group_subinterfaces")
    op.drop_table("interface_group_subinterfaces")
    with op.batch_alter_table("interface_groups") as batch:
        batch.drop_column("manage_subinterfaces")
