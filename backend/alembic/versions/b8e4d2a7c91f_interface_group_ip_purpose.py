"""Назначение общего IP-адреса в группах портов: interface_groups.ip_purpose

Revision ID: b8e4d2a7c91f
Revises: e4c8a1d7b350
Create Date: 2026-10-01 00:00:00.000000

Правка групп портов: группа задаёт общий IP-адрес и префикс, но не «Назначение» — поле рядом с ними
в блоке «IP-адреса интерфейса» (ip_addresses.purpose), которое у портов группы оставалось доступным
для правки. Добавляет interface_groups.ip_purpose: оно — часть общего IP, как и префикс, и при
заданном ip_address безусловно записывается в IP каждого порта группы (services/crud.py:
_apply_group_to_interface; пустое значение очищает назначение), а форма устройства блокирует поле
«Назначение» у портов группы вместе с адресом и префиксом.

Перенос существующих данных. Раньше группа назначения не задавала, и порты одной группы могли иметь
свои. Чтобы при первом же сохранении устройства не затереть то, что уже введено, миграция заполняет
ip_purpose для каждой группы с общим IP, если у IP её портов с этим адресом ровно одно непустое
назначение (порты с пустым назначением получат его). Если назначений несколько разных — однозначно
выбрать нельзя, ip_purpose остаётся NULL, и при следующем сохранении устройства назначение у портов
такой группы очистится: его нужно будет задать в группе (или вывести порты из группы).

Колонка добавляется через batch_alter_table (на SQLite — пересборка таблицы, как в остальных
миграциях проекта). downgrade() работает: снимает колонку; назначения, уже записанные в IP-адреса
портов, остаются на портах — теряется только управление ими со стороны группы.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8e4d2a7c91f"
down_revision = "e4c8a1d7b350"
branch_labels = None
depends_on = None

# Значение constants.OwnerType.DEVICE_INTERFACE; миграция не импортирует код приложения.
_DEVICE_INTERFACE = "device_interface"


def _backfill_ip_purpose(bind: sa.engine.Connection) -> None:
    rows = bind.execute(
        sa.text(
            "SELECT g.id AS group_id, ip.purpose AS purpose "
            "FROM interface_groups g "
            "JOIN device_interfaces i ON i.group_id = g.id "
            "JOIN ip_addresses ip ON ip.owner_type = :owner_type AND ip.owner_id = i.id AND ip.ip_address = g.ip_address "
            "WHERE g.ip_address IS NOT NULL AND ip.purpose IS NOT NULL"
        ),
        {"owner_type": _DEVICE_INTERFACE},
    ).all()
    purposes: dict[str, set[str]] = {}
    for group_id, purpose in rows:
        text = purpose.strip()
        if text:
            purposes.setdefault(group_id, set()).add(text)
    for group_id, values in purposes.items():
        if len(values) == 1:
            bind.execute(
                sa.text("UPDATE interface_groups SET ip_purpose = :purpose WHERE id = :group_id"),
                {"purpose": next(iter(values)), "group_id": group_id},
            )


def upgrade() -> None:
    with op.batch_alter_table("interface_groups") as batch:
        batch.add_column(sa.Column("ip_purpose", sa.String(length=255), nullable=True))
    _backfill_ip_purpose(op.get_bind())


def downgrade() -> None:
    with op.batch_alter_table("interface_groups") as batch:
        batch.drop_column("ip_purpose")
