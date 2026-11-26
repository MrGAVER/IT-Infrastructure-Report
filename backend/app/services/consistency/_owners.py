"""Определение владельца IP-адреса: за какой объект реестра (устройство, ВМ, источник ИС) он числится.

IPAddress ссылается на владельца парой owner_type/owner_id без настоящего FK, поэтому имена приходится собирать отдельными
запросами. Для проверки повторов важен ключ `key`: два порта одного устройства или два устройства одного стека — один и тот же
узел, и общий адрес у них — норма, а не повтор.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...constants import OwnerType
from ...models import DeviceInterface, DeviceSubinterface, InformationSystem, InformationSystemSource, VirtualMachine
from ._support import chunked, device_labels, stack_by_device

INFORMATION_SYSTEM = "information_system"


@dataclass(frozen=True, slots=True)
class Holder:
    """Владелец адреса: `key` — узел для сравнения, `entity_*` — объект, к которому ведёт ссылка, `place` — порт или подинтерфейс."""

    key: str
    entity_type: str
    entity_id: str
    name: str
    place: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"entity_type": self.entity_type, "entity_id": self.entity_id, "name": self.name, "place": self.place}


def resolve_ip_owners(session: Session, owners: Collection[tuple[str, str]]) -> dict[tuple[str, str], Holder]:
    """Для каждой пары (owner_type, owner_id) возвращает владельца. Несуществующий владелец или неизвестный тип получают
    Holder с id вместо имени — такие записи отдельно ловит диагностика висячих ссылок."""
    ids_by_type: dict[str, set[str]] = {}
    for owner_type, owner_id in owners:
        ids_by_type.setdefault(owner_type, set()).add(owner_id)

    port_rows = _ports(session, ids_by_type.get(OwnerType.DEVICE_INTERFACE, set()))
    sub_rows = _subinterfaces(session, ids_by_type.get(OwnerType.DEVICE_SUBINTERFACE, set()))
    parent_ports = _ports(session, {parent_id for _, parent_id in sub_rows.values()} - port_rows.keys())

    direct_devices = ids_by_type.get(OwnerType.PHYSICAL_DEVICE, set())
    device_ids = direct_devices | {device_id for _, device_id in port_rows.values()} | {device_id for _, device_id in parent_ports.values()}
    labels = device_labels(session, device_ids)
    stacks = stack_by_device(session)
    vm_names = _vm_names(session, ids_by_type.get(OwnerType.VIRTUAL_MACHINE, set()))
    source_names = _source_owners(session, ids_by_type.get(OwnerType.INFORMATION_SYSTEM_SOURCE, set()))

    def device_holder(device_id: str, place: str | None) -> Holder:
        return Holder(stacks.get(device_id, device_id), "physical_device", device_id, labels.get(device_id, device_id), place)

    resolved: dict[tuple[str, str], Holder] = {}
    for owner_type, owner_id in owners:
        if owner_type == OwnerType.PHYSICAL_DEVICE:
            holder = device_holder(owner_id, None)
        elif owner_type == OwnerType.DEVICE_INTERFACE and owner_id in port_rows:
            name, device_id = port_rows[owner_id]
            holder = device_holder(device_id, name)
        elif owner_type == OwnerType.DEVICE_SUBINTERFACE and owner_id in sub_rows:
            name, parent_id = sub_rows[owner_id]
            device_id = (port_rows.get(parent_id) or parent_ports.get(parent_id, ("", owner_id)))[1]
            holder = device_holder(device_id, name)
        elif owner_type == OwnerType.VIRTUAL_MACHINE:
            holder = Holder(owner_id, "virtual_machine", owner_id, vm_names.get(owner_id, owner_id))
        elif owner_type == OwnerType.INFORMATION_SYSTEM_SOURCE and owner_id in source_names:
            system_id, system_name = source_names[owner_id]
            holder = Holder(f"is:{system_id}", INFORMATION_SYSTEM, system_id, system_name, "источник")
        else:
            holder = Holder(f"{owner_type}:{owner_id}", owner_type, owner_id, owner_id)
        resolved[(owner_type, owner_id)] = holder
    return resolved


def _ports(session: Session, port_ids: Collection[str]) -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    for batch in chunked(port_ids):
        for row in session.execute(
            select(DeviceInterface.id, DeviceInterface.name, DeviceInterface.physical_device_id).where(DeviceInterface.id.in_(batch))
        ):
            rows[row.id] = (row.name, row.physical_device_id)
    return rows


def _subinterfaces(session: Session, sub_ids: Collection[str]) -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    for batch in chunked(sub_ids):
        for row in session.execute(
            select(DeviceSubinterface.id, DeviceSubinterface.name, DeviceSubinterface.parent_interface_id).where(
                DeviceSubinterface.id.in_(batch)
            )
        ):
            rows[row.id] = (row.name, row.parent_interface_id)
    return rows


def _vm_names(session: Session, vm_ids: Collection[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for batch in chunked(vm_ids):
        names.update(
            {
                row.id: row.name
                for row in session.execute(select(VirtualMachine.id, VirtualMachine.name).where(VirtualMachine.id.in_(batch)))
            }
        )
    return names


def _source_owners(session: Session, source_ids: Collection[str]) -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    for batch in chunked(source_ids):
        for row in session.execute(
            select(InformationSystemSource.id, InformationSystem.id.label("system_id"), InformationSystem.name)
            .join(InformationSystem, InformationSystem.id == InformationSystemSource.information_system_id)
            .where(InformationSystemSource.id.in_(batch))
        ):
            rows[row.id] = (row.system_id, row.name)
    return rows
