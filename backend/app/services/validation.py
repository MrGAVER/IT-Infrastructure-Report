from __future__ import annotations
import ipaddress
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from ..models import (
    DeviceModel, DeviceType, OperatingSystem, OperatingSystemCategory, PhysicalDevice,
    Rack, Room, DeviceInterface, Connection, EmbeddedOperatingSystem, SupportMethod,
    DeviceStackMember,
)

# Код-ревью п.3.4: формат IPv4/длина префикса проверялись только на клиенте
# (frontend-vue/src/utils/ipValidation.ts) — прямой запрос к API мимо формы (или старый
# кэшированный фронтенд-бандл) мог записать в InterfaceIP/VMIP/ISIP.ip_address произвольную
# строку. Семантика зеркальна ipValidation.ts: пустая строка/None считаются валидными — это не
# проверка на обязательность поля, а на "если что-то введено, это должно быть похоже на IP/
# префикс".

def validate_ipv4_field(value: Any, field_label: str) -> None:
    """Бросает HTTPException(422), если value непустое и не является корректным IPv4-адресом.
    ipaddress.IPv4Address сама отклоняет ведущие нули (например, "01.0.0.1") начиная с
    Python 3.9.5 (CVE-2021-29921) — то же правило, что и в isValidIPv4 на фронтенде.

    Пример вызова:
        validate_ipv4_field("10.0.0.1", "IP-адрес интерфейса")  # не бросает
        validate_ipv4_field("не-ip", "IP-адрес интерфейса")     # HTTPException(422)
        validate_ipv4_field("", "IP-адрес интерфейса")          # не бросает (пусто — валидно)
    """
    if value is None or value == '':
        return
    if not isinstance(value, str):
        raise HTTPException(422, f'{field_label}: некорректный IPv4-адрес')
    try:
        ipaddress.IPv4Address(value)
    except ValueError as exc:
        raise HTTPException(422, f'{field_label}: некорректный IPv4-адрес') from exc


def validate_prefix_length_field(value: Any, field_label: str) -> None:
    """Бросает HTTPException(422), если value непустое и не является целым числом 0-32 (длина
    префикса маски подсети IPv4). Принимает и int, и строку — prefix_length в JSON-теле запроса
    может прийти любым из двух видов в зависимости от клиента."""
    if value is None or value == '':
        return
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, f'{field_label}: длина префикса должна быть целым числом от 0 до 32') from exc
    if not (0 <= n <= 32):
        raise HTTPException(422, f'{field_label}: длина префикса должна быть целым числом от 0 до 32')


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
    duplicate = session.scalar(stmt)
    if duplicate is None or not current_id:
        return duplicate
    # Пункт 3 правки "инвентаризация физических устройств": стекируемое оборудование (например,
    # стек коммутаторов Cisco) штатно показывает ОДИН и тот же системный hostname для всех
    # участников стека — это норма для такого железа, а не ошибка заполнения формы, поэтому
    # предупреждение не нужно, если совпадение найдено внутри ОДНОГО И ТОГО ЖЕ стека
    # (DeviceStackMember.physical_device_id уникален — участник состоит максимум в одном стеке,
    # см. models.py). На создании (current_id ещё нет — устройство только заводится, оно
    # физически не может уже состоять в стеке) эта ветка не участвует — предупреждение всё равно
    # сработает как раньше, а к стеку устройство добавляют отдельным шагом после создания.
    current_stack_id = session.scalar(select(DeviceStackMember.stack_id).where(DeviceStackMember.physical_device_id == current_id))
    if current_stack_id is None:
        return duplicate
    duplicate_stack_id = session.scalar(select(DeviceStackMember.stack_id).where(DeviceStackMember.physical_device_id == duplicate.id))
    if duplicate_stack_id == current_stack_id:
        return None
    return duplicate

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

def validate_support_method_organization(data: dict[str, Any], session: Session) -> None:
    """Способ оказания техподдержки, привязанный к конкретной организации
    (SupportMethod.support_organization_id), можно сохранить у ИС только вместе с ЭТОЙ ЖЕ
    организацией техподдержки — иначе в данных ИС оказалась бы пара "организация А" + "способ,
    принадлежащий организации Б", которая не может быть верной одновременно. Способ без
    организации (support_organization_id IS NULL) считается универсальным и подходит любой
    организации, в том числе не указанной вовсе. Тот же принцип согласованности пары полей, что
    и validate_device_location_hierarchy (помещение должно принадлежать зданию) выше — только
    здесь оба поля лежат на самой ИС, а не разнесены по разным таблицам.

    Пример вызова:
        validate_support_method_organization(
            {"support_method_id": "m1", "support_organization_id": "o1"}, session,
        )  # не бросает, если SupportMethod("m1").support_organization_id in (None, "o1")
    """
    method_id = data.get('support_method_id')
    if not method_id:
        return
    method = session.get(SupportMethod, method_id)
    if not method:
        raise HTTPException(422, 'Выбранный способ оказания техподдержки не найден')
    if method.support_organization_id and method.support_organization_id != data.get('support_organization_id'):
        raise HTTPException(422, 'Выбранный способ оказания техподдержки принадлежит другой организации технической поддержки')


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
