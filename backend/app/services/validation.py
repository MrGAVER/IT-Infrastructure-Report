from __future__ import annotations
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from ..models import (
    DeviceModel, DeviceType, OperatingSystem, OperatingSystemCategory, PhysicalDevice,
    Rack, Room, DeviceInterface, Connection, EmbeddedOperatingSystem,
)

def validate_device_model_relation(data: dict[str, Any], session: Session, current_device_id: str | None = None) -> None:
    manufacturer_id = data.get('manufacturer_id')
    device_type_id = data.get('device_type_id')
    if current_device_id:
        current = session.get(PhysicalDevice, current_device_id)
        if current:
            manufacturer_id = manufacturer_id or current.manufacturer_id
            device_type_id = device_type_id or current.device_type_id
    if data.get('model_id'):
        model = session.get(DeviceModel, data['model_id'])
        if not model:
            raise HTTPException(422, 'Выбранная модель устройства не найдена')
        if manufacturer_id and model.manufacturer_id != manufacturer_id:
            raise HTTPException(422, 'Выбранная модель не принадлежит указанному производителю')
        if device_type_id and model.device_type_id != device_type_id:
            raise HTTPException(422, 'Выбранная модель не соответствует выбранному типу устройства')

def validate_embedded_os(data: dict[str, Any], session: Session) -> None:
    os_id = data.get('embedded_os_id')
    if os_id and not session.get(EmbeddedOperatingSystem, os_id):
        raise HTTPException(422, 'Выбранная встроенная ОС не найдена')


def validate_operating_system(data: dict[str, Any], session: Session) -> None:
    os_id = data.get('operating_system_id')
    if os_id and not session.get(OperatingSystem, os_id):
        raise HTTPException(422, 'Выбранная ОС не найдена')

def validate_vm_host(data: dict[str, Any], session: Session) -> None:
    host_id = data.get('physical_device_id')
    if not host_id:
        return
    host = session.get(PhysicalDevice, host_id)
    if not host:
        raise HTTPException(422, 'Выбранное физическое устройство не найдено')
    device_type = session.get(DeviceType, host.device_type_id)
    if not device_type or not device_type.allows_vm_hosting:
        raise HTTPException(422, 'Для размещения виртуальной машины можно выбрать только сервер или систему хранения')

def validate_hypervisor(data: dict[str, Any], session: Session) -> None:
    hypervisor_id = data.get('hypervisor_os_id')
    if not hypervisor_id:
        return
    hypervisor = session.get(OperatingSystem, hypervisor_id)
    if not hypervisor:
        raise HTTPException(422, 'Выбранный гипервизор не найден')
    category = session.get(OperatingSystemCategory, hypervisor.category_id)
    if not category or not category.is_hypervisor:
        raise HTTPException(422, 'В поле гипервизора можно выбрать только ОС из категории «Гипервизор»')

def duplicate_system_name(session: Session, value: str | None, current_id: str | None = None):
    if not value or not value.strip():
        return None
    stmt = select(PhysicalDevice).where(func.lower(PhysicalDevice.system_name) == value.strip().lower())
    if current_id:
        stmt = stmt.where(PhysicalDevice.id != current_id)
    return session.scalar(stmt)

def validate_device_location_hierarchy(data: dict[str, Any], session: Session) -> None:
    building_id, room_id, rack_id = data.get('building_id'), data.get('room_id'), data.get('rack_id')
    room = session.get(Room, room_id) if room_id else None
    rack = session.get(Rack, rack_id) if rack_id else None
    if room_id and not room:
        raise HTTPException(422, 'Выбранное помещение не найдено')
    if rack_id and not rack:
        raise HTTPException(422, 'Выбранная стойка не найдена')
    if room and building_id and room.building_id != building_id:
        raise HTTPException(422, 'Выбранное помещение не принадлежит выбранному зданию')
    if rack and not room_id:
        raise HTTPException(422, 'Для выбора стойки необходимо сначала выбрать помещение')
    if rack and rack.room_id != room_id:
        raise HTTPException(422, 'Выбранная стойка не принадлежит выбранному помещению')

def validate_connection(data: dict[str, Any], session: Session, current_connection_id: str | None = None) -> None:
    source_id, destination_id = data.get('source_interface_id'), data.get('destination_interface_id')
    if not source_id:
        raise HTTPException(422, 'Необходимо выбрать исходное устройство и его порт')
    if not destination_id:
        raise HTTPException(422, 'Необходимо выбрать конечное устройство и его порт')
    source = session.get(DeviceInterface, source_id)
    destination = session.get(DeviceInterface, destination_id)
    if not source or not destination:
        raise HTTPException(422, 'Выбранный интерфейс не найден')
    if source_id == destination_id:
        raise HTTPException(422, 'Исходный и конечный интерфейсы не могут совпадать')
    if not data.get('connection_type_id'):
        raise HTTPException(422, 'Необходимо выбрать тип подключения')
    # One physical/logical interface can participate in only one active connection.
    # During editing, the current connection itself is ignored.
    stmt = select(Connection).where(
        Connection.is_active.is_not(False),
        (
            (Connection.source_interface_id == source_id) |
            (Connection.destination_interface_id == source_id) |
            (Connection.source_interface_id == destination_id) |
            (Connection.destination_interface_id == destination_id)
        )
    )
    if current_connection_id:
        stmt = stmt.where(Connection.id != current_connection_id)
    occupied = session.scalar(stmt)
    if occupied:
        raise HTTPException(409, 'Один из выбранных портов уже участвует в другом активном подключении. Выберите свободный порт.')
