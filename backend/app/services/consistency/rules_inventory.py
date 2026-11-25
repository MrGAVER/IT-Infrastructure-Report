"""Правила инвентаризации физических устройств (лист 2 отчёта): размещение, паспорт устройства, адрес управления."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...constants import OwnerType
from ...models import Building, DeviceInterface, DeviceSubinterface, IPAddress, PhysicalDevice, Rack, Room
from ..device_label import device_label
from ._support import is_blank, stack_by_device
from .engine import RuleSpec, rule
from .model import Category, Finding, Severity


def _devices(session: Session) -> list:
    return list(
        session.execute(
            select(
                PhysicalDevice.id,
                PhysicalDevice.system_name,
                PhysicalDevice.serial_number,
                PhysicalDevice.building_id,
                PhysicalDevice.room_id,
                PhysicalDevice.rack_id,
                PhysicalDevice.manufacturer_id,
                PhysicalDevice.model_id,
                PhysicalDevice.operating_system_id,
                PhysicalDevice.embedded_os_id,
            )
        )
    )


def _name(row) -> str:
    return device_label(row, fallback=row.id)


@rule("device_location_mismatch", "Здание, помещение и стойка устройства не согласуются", Severity.ERROR, Category.CONSISTENCY, sheet=2)
def check_location_mismatch(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    """Помещение устройства лежит в другом здании, чем указано, или его стойка стоит в другом помещении, чем указано."""
    rooms = {row.id: row for row in session.execute(select(Room.id, Room.name, Room.building_id))}
    racks = {row.id: row for row in session.execute(select(Rack.id, Rack.name, Rack.room_id))}
    buildings = {row.id: row.name for row in session.execute(select(Building.id, Building.name))}
    for device in _devices(session):
        problems: list[str] = []
        room = rooms.get(device.room_id) if device.room_id else None
        rack = racks.get(device.rack_id) if device.rack_id else None
        if room and device.building_id and room.building_id != device.building_id:
            actual, stated = buildings.get(room.building_id, "—"), buildings.get(device.building_id, "—")
            problems.append(f"помещение «{room.name}» находится в здании «{actual}», а у устройства указано «{stated}»")
        if rack and room and rack.room_id != room.id:
            rack_room = rooms.get(rack.room_id)
            problems.append(
                f"стойка «{rack.name}» стоит в помещении «{rack_room.name if rack_room else '—'}», а у устройства указано «{room.name}»"
            )
        if problems:
            yield spec.finding("physical_device", device.id, _name(device), f"{_name(device)}: {'; '.join(problems)}.", problems=problems)


@rule("device_location_incomplete", "У устройства не указано здание или помещение", Severity.WARNING, Category.COMPLETENESS, sheet=2)
def check_location_incomplete(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    """Здание и помещение берутся у самого устройства, а если там пусто — из стойки (стойка → помещение → здание)."""
    rooms = {row.id: row.building_id for row in session.execute(select(Room.id, Room.building_id))}
    racks = {row.id: row.room_id for row in session.execute(select(Rack.id, Rack.room_id))}
    for device in _devices(session):
        room_id = device.room_id or racks.get(device.rack_id)
        building_id = device.building_id or rooms.get(room_id)
        missing = [label for label, value in (("здание", building_id), ("помещение", room_id)) if is_blank(value)]
        if missing:
            yield spec.finding(
                "physical_device", device.id, _name(device), f"{_name(device)}: не указано {' и '.join(missing)}.", missing=missing
            )


@rule("device_identity_incomplete", "В паспорте устройства не хватает данных", Severity.WARNING, Category.COMPLETENESS, sheet=2)
def check_identity_incomplete(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    """Производитель, модель и операционная система — обязательные столбцы листа 2. ОС устройства лист 2 (и лист 3) берёт только из
    поля «Встроенная ОС» (embedded_os_id): его же редактирует форма устройства, а обычная `operating_system_id` в отчёт не попадает —
    устройство, у которого заполнено только оно, выйдет в отчёте с пустой ОС."""
    for device in _devices(session):
        missing = [
            label
            for label, filled in (
                ("производитель", device.manufacturer_id),
                ("модель", device.model_id),
                ("операционная система", device.embedded_os_id),
            )
            if is_blank(filled)
        ]
        if missing:
            yield spec.finding(
                "physical_device", device.id, _name(device), f"{_name(device)}: не указано — {', '.join(missing)}.", missing=missing
            )


def _devices_with_management_address(session: Session) -> set[str]:
    """Устройства, у которых есть адрес управления: IP с признаком управления либо любой IP на порту/подинтерфейсе, помеченном
    как управляющий, либо IP, записанный на само устройство."""
    found: set[str] = set(session.scalars(select(IPAddress.owner_id).where(IPAddress.owner_type == OwnerType.PHYSICAL_DEVICE)))
    found.update(
        session.scalars(
            select(DeviceInterface.physical_device_id)
            .join(IPAddress, (IPAddress.owner_type == OwnerType.DEVICE_INTERFACE) & (IPAddress.owner_id == DeviceInterface.id))
            .where(or_(IPAddress.is_management, DeviceInterface.is_management))
        )
    )
    found.update(
        session.scalars(
            select(DeviceInterface.physical_device_id)
            .join(DeviceSubinterface, DeviceSubinterface.parent_interface_id == DeviceInterface.id)
            .join(IPAddress, (IPAddress.owner_type == OwnerType.DEVICE_SUBINTERFACE) & (IPAddress.owner_id == DeviceSubinterface.id))
            .where(or_(IPAddress.is_management, DeviceSubinterface.is_management))
        )
    )
    return found


@rule(
    "managed_device_without_mgmt_ip", "У управляемого устройства нет IP-адреса управления", Severity.WARNING, Category.COMPLETENESS, sheet=2
)
def check_managed_device_address(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    """Управляемым считается устройство с системным именем (так определён столбец листа 2). Стек управляется через один адрес,
    поэтому участник без своего адреса не нарушение, если адрес есть у любого участника того же стека."""
    stacks = stack_by_device(session)
    addressed = _devices_with_management_address(session)
    addressed_stacks = {stacks[device_id] for device_id in addressed if device_id in stacks}
    for device in _devices(session):
        if is_blank(device.system_name) or device.id in addressed or stacks.get(device.id) in addressed_stacks:
            continue
        yield spec.finding(
            "physical_device", device.id, _name(device), f"{_name(device)}: есть системное имя, но не указан IP-адрес управления."
        )
