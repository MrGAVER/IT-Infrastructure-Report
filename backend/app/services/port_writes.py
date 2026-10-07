"""Запись конфигурации ОДНОГО порта (роль, режим и VLAN) — общая для всех операций, которые меняют порт
точечно, в обход синхронизации устройства целиком (PUT /devices/{id}/interfaces):

  * согласование по правилам (services/port_sync_reconcile.py);
  * правка порта на дашборде «Подключения» (services/port_edit.py);
  * смена роли порта (services/connection_review.set_port_role).

Здесь только запись: проверки (допустимые VLAN, «в access не более одного VLAN», группа портов,
которая задаёт режим и VLAN) делает вызывающий — у каждой операции своё сообщение об ошибке и свой
способ её показать. Функции не делают commit и не пишут аудит — это тоже на вызывающем: операция
может менять несколько портов одной транзакцией.
"""
from __future__ import annotations

from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..constants import OwnerType
from ..models import DeviceInterface, IPAddress, InterfaceVLAN
from .port_config import PortRole
from .port_sync_rules import flags_from_role


def write_port_role(port: DeviceInterface, role: PortRole, session: Session) -> None:
    """Роль порта (управление / передача данных) вместе с признаком на его IP-адресах.

    IP-адреса порта зеркалируют его is_management — тот же инвариант, что у sync_interfaces."""
    is_management, is_data = flags_from_role(role)
    port.is_management, port.is_data_transfer = is_management, is_data
    session.execute(update(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id == port.id).values(is_management=is_management))


def write_port_vlans(port: DeviceInterface, mode: str, vlan_ids: Sequence[str], session: Session) -> None:
    """Режим порта и ровно этот набор VLAN (id записей справочника): лишние связи удаляются, недостающие
    добавляются, у остающихся выставляется режим. Дубликаты в `vlan_ids` игнорируются."""
    port.vlan_mode = mode
    session.flush()
    keep = list(dict.fromkeys(vlan_ids))
    kept: set[str] = set()
    for link in session.scalars(select(InterfaceVLAN).where(InterfaceVLAN.interface_id == port.id)).all():
        if link.vlan_id in keep and link.vlan_id not in kept:
            link.mode = mode
            kept.add(link.vlan_id)
        else:
            session.delete(link)
    for vlan_id in keep:
        if vlan_id not in kept:
            session.add(InterfaceVLAN(interface_id=port.id, vlan_id=vlan_id, mode=mode))
