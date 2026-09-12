"""Reassign unambiguous device-level open ports to their single interface (п.1.4, батч4)

"Открытые порты" на форме устройства (DeviceFormModal.vue) переехали с уровня всего устройства
на уровень конкретного интерфейса/порта (см. backend/app/services/crud.py:
_sync_interface_open_ports и backend/app/constants.py:OwnerType.DEVICE_INTERFACE) — это не
только UI-удобство (возможность скопировать набор портов с одного интерфейса на другой), но и
исправление самого отчёта: колонка "Перечень открытых портов" на Листе 3 относится к КОНКРЕТНОМУ
физическому/логическому порту, а раньше туда подставлялся один и тот же список для всех портов
устройства разом (см. reporting.py:_port_open_info до этого фикса).

Существующие записи OpenPort с owner_type='physical_device' переносятся на owner_type=
'device_interface' автоматически ТОЛЬКО для устройств РОВНО с одним интерфейсом — только в этом
случае перенос однозначен. Для устройств без интерфейсов или с несколькими интерфейсами
однозначного получателя нет (мы бы гадали, какому порту принадлежит запись) — такие строки
намеренно остаются как есть (owner_type='physical_device'): данные не теряются физически, но
перестают быть видны в новом UI/отчёте, пока администратор не перенесёт их вручную на нужный
интерфейс через DeviceFormModal.vue.

Revision ID: 1475ab03debc
Revises: e519c184f3ae
Create Date: 2026-09-11 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "1475ab03debc"
down_revision = "e519c184f3ae"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE open_ports
        SET owner_type = 'device_interface',
            owner_id = (
                SELECT di.id FROM device_interfaces di
                WHERE di.physical_device_id = open_ports.owner_id
            )
        WHERE owner_type = 'physical_device'
          AND (
                SELECT COUNT(*) FROM device_interfaces di2
                WHERE di2.physical_device_id = open_ports.owner_id
              ) = 1
        """
    )


def downgrade() -> None:
    # Necessarily lossy in the general case: any open-port row created directly at the interface
    # level AFTER this migration ran (through the new per-interface UI) would be indistinguishable
    # from one that this migration itself reassigned, so a downgrade could incorrectly pull
    # brand-new interface-level data back down to device level. Same category as
    # c4e8a7d91b20_os_catalog_and_duplicate_system_names.py — see its downgrade() for precedent.
    raise RuntimeError(
        "Downgrade of ports-per-interface migration is intentionally unsupported: reassigned "
        "rows cannot be distinguished from open ports created directly at interface level after "
        "this migration ran."
    )
