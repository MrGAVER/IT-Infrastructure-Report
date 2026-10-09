"""Подинтерфейсы портов устройства: таблица device_subinterfaces

Revision ID: e3b7d2a9c158
Revises: b5d2f8a1c673
Create Date: 2026-10-09 00:00:00.000000

Правка формы устройства: на порту можно создать подинтерфейсы — логические интерфейсы на отдельном
VLAN со своими IP-адресами, открытыми портами и ролью (как у маршрутизаторов и межсетевых экранов,
см. models.DeviceSubinterface). Миграция только добавляет структуру: существующие данные не меняются.

Уникальность имени (в пределах устройства) и VLAN (в пределах порта) проверяет приложение, а не
ограничения БД (см. докстринг models.DeviceSubinterface).

IP-адреса и открытые порты подинтерфейса хранятся в уже существующих полиморфных таблицах
ip_addresses / open_ports с новым owner_type='device_subinterface' (без FK на уровне БД) — схема
этих таблиц не меняется.

downgrade() работает: сначала удаляет полиморфные строки, принадлежащие подинтерфейсам (иначе после
удаления таблицы они остались бы «висячими» ссылками на несуществующего владельца), затем индексы и
саму таблицу. Теряются только подинтерфейсы и их IP/открытые порты; физические порты не затрагиваются.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e3b7d2a9c158"
down_revision = "b5d2f8a1c673"
branch_labels = None
depends_on = None

# Значение constants.OwnerType.DEVICE_SUBINTERFACE; миграция не импортирует код приложения.
_DEVICE_SUBINTERFACE = "device_subinterface"


def upgrade() -> None:
    op.create_table(
        "device_subinterfaces",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("parent_interface_id", sa.String(length=36), sa.ForeignKey("device_interfaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("vlan_id", sa.String(length=36), sa.ForeignKey("vlans.id"), nullable=False),
        sa.Column("is_management", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_data_transfer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_device_subinterfaces_parent_interface_id", "device_subinterfaces", ["parent_interface_id"])
    op.create_index("ix_device_subinterfaces_vlan_id", "device_subinterfaces", ["vlan_id"])


def downgrade() -> None:
    bind = op.get_bind()
    params = {"owner_type": _DEVICE_SUBINTERFACE}
    bind.execute(sa.text("DELETE FROM ip_addresses WHERE owner_type = :owner_type"), params)
    bind.execute(sa.text("DELETE FROM open_ports WHERE owner_type = :owner_type"), params)

    op.drop_index("ix_device_subinterfaces_vlan_id", table_name="device_subinterfaces")
    op.drop_index("ix_device_subinterfaces_parent_interface_id", table_name="device_subinterfaces")
    op.drop_table("device_subinterfaces")
