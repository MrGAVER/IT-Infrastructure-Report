"""
Именованные константы для значений, которые раньше были магическими строками, разбросанными по
местам использования backend/app/services/crud.py. Коды ошибок и типы действий аудита пересекают
границу backend/frontend (frontend сверяется с этими же строками при разборе ответа API), поэтому
разделяемой Python/JS-константы тут нет и быть не может — но именование на каждой стороне снижает
риск опечатки на месте использования и документирует набор допустимых значений в одном месте.
"""
from __future__ import annotations


class ErrorCode:
    """Коды в detail.code структурированных ошибок API (см. parseApiError() во фронтенде)."""
    DUPLICATE_SYSTEM_NAME = "DUPLICATE_SYSTEM_NAME"
    RACK_POSITION_OCCUPIED = "RACK_POSITION_OCCUPIED"
    REFERENCED_BY_OTHER_RECORDS = "REFERENCED_BY_OTHER_RECORDS"


class AuditAction:
    """Значения поля action в audit_log (см. actionLabels во фронтенде для их русских подписей)."""
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    SYNC = "SYNC"


class SourceType:
    """Допустимые значения InformationSystemSource.source_type."""
    MANUAL = "manual"
    DEVICE = "device"
    VM = "vm"
    CONTAINER = "container"

    ALL = {MANUAL, DEVICE, VM, CONTAINER}


class OwnerType:
    """Допустимые значения OpenPort.owner_type (полиморфная связь без FK на уровне БД)."""
    PHYSICAL_DEVICE = "physical_device"
    VIRTUAL_MACHINE = "virtual_machine"
