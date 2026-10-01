"""Сверка ролей портов-соседей подключения (управление / передача данных).

Роль порта хранится на самом интерфейсе (DeviceInterface.is_management / is_data_transfer) — это
единственный источник данных, из которого отчёты и схема сети берут «назначение линии связи».
Подключение соединяет два порта, и их роли могут не совпадать: например, порт сервера — порт
управления, а порт коммутатора, куда он включён, — порт передачи данных. Иногда это ошибка ввода,
иногда — осознанная конфигурация, поэтому расхождение не «чинится» молча, а получает статус:

    ok        — роли совпадают (или подключение неактивно и не участвует в проверке);
    mismatch  — роли различаются, решение пользователя ещё не принято;
    approved  — роли различаются, но пользователь одобрил именно эту пару ролей.

Модуль намеренно чистый (без обращения к БД и без импорта serialization/crud): его использует
и enrich_connections(), и операции одобрения (services/connection_review.py).

Пример:
    evaluate_port_config(server_port, switch_port, conn.port_config_approved_signature)
    # -> PortConfigStatus.MISMATCH, пока пара «management>data» не одобрена
"""
from __future__ import annotations

from enum import Enum
from typing import Protocol


class PortRole(str, Enum):
    NONE = "none"
    MANAGEMENT = "management"
    DATA = "data"
    MANAGEMENT_DATA = "management_data"


class PortConfigStatus(str, Enum):
    OK = "ok"
    MISMATCH = "mismatch"
    APPROVED = "approved"


class HasPortRoleFlags(Protocol):
    is_management: bool
    is_data_transfer: bool


PORT_ROLE_LABELS: dict[PortRole, str] = {
    PortRole.NONE: "не задано",
    PortRole.MANAGEMENT: "Управление активами",
    PortRole.DATA: "Передача данных",
    PortRole.MANAGEMENT_DATA: "Передача данных и управление активами",
}


def role_from_flags(is_management: bool, is_data_transfer: bool) -> PortRole:
    if is_management and is_data_transfer:
        return PortRole.MANAGEMENT_DATA
    if is_management:
        return PortRole.MANAGEMENT
    if is_data_transfer:
        return PortRole.DATA
    return PortRole.NONE


def port_role(iface: HasPortRoleFlags) -> PortRole:
    return role_from_flags(bool(iface.is_management), bool(iface.is_data_transfer))


def approval_signature(source: HasPortRoleFlags, destination: HasPortRoleFlags) -> str:
    """Подпись пары ролей «источник>назначение». Порядок важен: пара «управление>данные» и
    «данные>управление» — разные расхождения, одобрение одного не распространяется на другое."""
    return f"{port_role(source).value}>{port_role(destination).value}"


def evaluate_port_config(
    source: HasPortRoleFlags,
    destination: HasPortRoleFlags,
    approved_signature: str | None,
    *,
    is_active: bool = True,
) -> PortConfigStatus:
    """Статус подключения. Неактивное подключение не несёт трафика — его порты могут быть в
    процессе перенастройки, поэтому оно не считается расхождением."""
    if not is_active:
        return PortConfigStatus.OK
    if port_role(source) == port_role(destination):
        return PortConfigStatus.OK
    if approved_signature and approved_signature == approval_signature(source, destination):
        return PortConfigStatus.APPROVED
    return PortConfigStatus.MISMATCH
