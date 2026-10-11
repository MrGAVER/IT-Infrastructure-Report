"""Галочка «Все VLAN» как сохраняемый признак: device_interfaces.all_vlans и interface_groups.all_vlans

Revision ID: f1a6c3d8e279
Revises: c4a8f1d6b937
Create Date: 2026-10-10 00:00:00.000000

Правка формы физического устройства: «Все VLAN» у порта (и у группы портов) больше не вычисляется из
числа выбранных VLAN, а хранится в БД отдельным признаком (models.DeviceInterface.all_vlans,
models.InterfaceGroup.all_vlans). Порт с признаком несёт ВСЕ VLAN, доступные его устройству, — в том
числе добавленные позже; связи interface_vlans / interface_group_vlans по-прежнему материализованы.

Хранение (по правке заказчика: оптимизация). Порт и группа с «Все VLAN» хранят ТОЛЬКО признак: связей
interface_vlans / interface_group_vlans у них нет, а набор VLAN вычисляется при чтении как «все VLAN
устройства» — VLAN типа ∪ VLAN самого устройства (services/port_vlans.py). VLAN, добавленный устройству
позже, у такого порта появляется сам.

Перенос существующих данных. Раньше «Все VLAN» была состоянием: порт в режиме trunk, у которого назначены
все VLAN, доступные устройству (VLAN типа устройства ∪ VLAN самого устройства), при непустом наборе
доступных. Миграция проставляет all_vlans именно по этому правилу — для портов и для групп портов (режим
trunk, назначены все доступные VLAN устройства группы) — и удаляет связи таких портов и групп: их набор теперь
вычисляется. Порты, у которых все VLAN выбраны вручную, получат галочку тоже (прежнее поведение формы было
таким же); дальше признак меняется только действием пользователя.

Колонки добавляются через batch_alter_table (на SQLite — пересборка таблицы, как в остальных миграциях
проекта). downgrade() работает: для портов и групп с признаком восстанавливает связи со ВСЕМИ VLAN устройства
(прежняя форма и отчёты читают именно связи и выводят «Все VLAN» из набора), затем снимает обе колонки.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable

import sqlalchemy as sa
from alembic import op

revision = "f1a6c3d8e279"
down_revision = "c4a8f1d6b937"
branch_labels = None
depends_on = None

_CHUNK = 400  # число id в одном IN-запросе (у SQLite/psycopg число параметров ограничено)

_MODE_TRUNK = "trunk"


def _chunks(values: list[str]) -> Iterable[list[str]]:
    for start in range(0, len(values), _CHUNK):
        yield values[start:start + _CHUNK]


def _allowed_by_device(bind: sa.engine.Connection) -> dict[str, set[str]]:
    """id устройства -> id записей справочника VLAN, доступных ему: VLAN его типа ∪ VLAN самого устройства."""
    type_vlans: dict[str, set[str]] = {}
    for type_id, vlan_id in bind.execute(sa.text("SELECT device_type_id, vlan_id FROM device_type_vlans")).all():
        type_vlans.setdefault(type_id, set()).add(vlan_id)
    device_vlans: dict[str, set[str]] = {}
    for device_id, vlan_id in bind.execute(sa.text("SELECT physical_device_id, vlan_id FROM physical_device_vlans")).all():
        device_vlans.setdefault(device_id, set()).add(vlan_id)
    allowed_by_device: dict[str, set[str]] = {}
    for device_id, type_id in bind.execute(sa.text("SELECT id, device_type_id FROM physical_devices")).all():
        allowed_by_device[device_id] = type_vlans.get(type_id, set()) | device_vlans.get(device_id, set())
    return allowed_by_device


def _backfill(bind: sa.engine.Connection) -> None:
    """Признак «Все VLAN» по прежнему правилу формы: trunk и назначены все доступные устройству VLAN; связи таких
    портов и групп удаляются (набор вычисляется из VLAN устройства)."""
    allowed_by_device = _allowed_by_device(bind)

    assigned: dict[str, set[str]] = {}
    for interface_id, vlan_id in bind.execute(sa.text("SELECT interface_id, vlan_id FROM interface_vlans")).all():
        assigned.setdefault(interface_id, set()).add(vlan_id)
    port_ids = [
        port_id
        for port_id, device_id, mode in bind.execute(sa.text("SELECT id, physical_device_id, vlan_mode FROM device_interfaces")).all()
        if mode == _MODE_TRUNK and allowed_by_device.get(device_id) and allowed_by_device[device_id] <= assigned.get(port_id, set())
    ]
    for chunk in _chunks(port_ids):
        stmt = sa.text("UPDATE device_interfaces SET all_vlans = :on WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True))
        bind.execute(stmt, {"on": True, "ids": chunk})
        # Набор порта с «Все VLAN» вычисляется из VLAN устройства — материализованные связи больше не нужны.
        bind.execute(sa.text("DELETE FROM interface_vlans WHERE interface_id IN :ids").bindparams(sa.bindparam("ids", expanding=True)), {"ids": chunk})

    group_assigned: dict[str, set[str]] = {}
    for group_id, vlan_id in bind.execute(sa.text("SELECT group_id, vlan_id FROM interface_group_vlans")).all():
        group_assigned.setdefault(group_id, set()).add(vlan_id)
    group_ids = [
        group_id
        for group_id, device_id, mode in bind.execute(sa.text("SELECT id, physical_device_id, vlan_mode FROM interface_groups")).all()
        if mode == _MODE_TRUNK and allowed_by_device.get(device_id) and allowed_by_device[device_id] <= group_assigned.get(group_id, set())
    ]
    for chunk in _chunks(group_ids):
        stmt = sa.text("UPDATE interface_groups SET all_vlans = :on WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True))
        bind.execute(stmt, {"on": True, "ids": chunk})
        bind.execute(sa.text("DELETE FROM interface_group_vlans WHERE group_id IN :ids").bindparams(sa.bindparam("ids", expanding=True)), {"ids": chunk})


def upgrade() -> None:
    with op.batch_alter_table("device_interfaces") as batch:
        batch.add_column(sa.Column("all_vlans", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("interface_groups") as batch:
        batch.add_column(sa.Column("all_vlans", sa.Boolean(), nullable=False, server_default=sa.false()))
    _backfill(op.get_bind())


def _materialize_links(bind: sa.engine.Connection) -> None:
    """Откат: порту и группе с признаком возвращаются связи со всеми VLAN их устройства — прежний код читает именно связи."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    allowed_by_device = _allowed_by_device(bind)
    port_rows = bind.execute(sa.text("SELECT id, physical_device_id FROM device_interfaces WHERE all_vlans = :on AND vlan_mode = :mode"), {"on": True, "mode": _MODE_TRUNK}).all()
    links = [
        {"id": str(uuid.uuid4()), "interface_id": port_id, "vlan_id": vlan_id, "mode": _MODE_TRUNK, "created_at": now, "updated_at": now}
        for port_id, device_id in port_rows
        for vlan_id in sorted(allowed_by_device.get(device_id, ()))
    ]
    if links:
        bind.execute(
            sa.text("INSERT INTO interface_vlans (id, interface_id, vlan_id, mode, created_at, updated_at) VALUES (:id, :interface_id, :vlan_id, :mode, :created_at, :updated_at)"),
            links,
        )
    group_rows = bind.execute(sa.text("SELECT id, physical_device_id FROM interface_groups WHERE all_vlans = :on AND vlan_mode = :mode"), {"on": True, "mode": _MODE_TRUNK}).all()
    group_links = [
        {"id": str(uuid.uuid4()), "group_id": group_id, "vlan_id": vlan_id, "created_at": now, "updated_at": now}
        for group_id, device_id in group_rows
        for vlan_id in sorted(allowed_by_device.get(device_id, ()))
    ]
    if group_links:
        bind.execute(
            sa.text("INSERT INTO interface_group_vlans (id, group_id, vlan_id, created_at, updated_at) VALUES (:id, :group_id, :vlan_id, :created_at, :updated_at)"),
            group_links,
        )


def downgrade() -> None:
    _materialize_links(op.get_bind())
    with op.batch_alter_table("interface_groups") as batch:
        batch.drop_column("all_vlans")
    with op.batch_alter_table("device_interfaces") as batch:
        batch.drop_column("all_vlans")
