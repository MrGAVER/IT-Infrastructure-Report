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
    DUPLICATE_USERNAME = "DUPLICATE_USERNAME"
    WEAK_PASSWORD = "WEAK_PASSWORD"
    LAST_ADMIN_ACCOUNT = "LAST_ADMIN_ACCOUNT"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    AUTH_REQUIRES_ADMIN = "AUTH_REQUIRES_ADMIN"
    SETUP_ACCESS_DENIED = "SETUP_ACCESS_DENIED"
    TOO_MANY_ATTEMPTS = "TOO_MANY_ATTEMPTS"
    INTEGRITY_ERROR = "INTEGRITY_ERROR"


class AuditAction:
    """Значения поля action в audit_log (см. actionLabels во фронтенде для их русских подписей)."""
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    SYNC = "SYNC"
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"


class UserRole:
    """Роли учётных записей (см. models.User.role). Ровно два уровня — этого достаточно для
    разделения «может смотреть реестр» / «может его менять и администрировать учётные записи»;
    более гранулярные права (per-resource) не запрашивались и добавили бы сложность без текущей
    потребности."""
    ADMIN = "admin"
    VIEWER = "viewer"
    ALL = {ADMIN, VIEWER}


class SourceType:
    """Допустимые значения InformationSystemSource.source_type."""
    MANUAL = "manual"
    DEVICE = "device"
    VM = "vm"
    CONTAINER = "container"

    ALL = {MANUAL, DEVICE, VM, CONTAINER}


class OwnerType:
    """Допустимые значения owner_type для полиморфных связей без FK на уровне БД: OpenPort,
    DeployedSoftware, IPAddress (см. их докстринги в models.py) — общий набор владельцев, но не
    каждая модель использует все значения (например, у DeployedSoftware нет DEVICE_INTERFACE —
    ПО разворачивается на устройстве целиком, а не на конкретном порту)."""
    PHYSICAL_DEVICE = "physical_device"
    VIRTUAL_MACHINE = "virtual_machine"
    # п.1.4 (батч4): открытые порты физического устройства переехали с уровня устройства на
    # уровень конкретного интерфейса (порта) — см. services/crud.py:_sync_single_interface и
    # миграцию 20260911_ports_per_interface. PHYSICAL_DEVICE оставлен как есть (не удаляем и не
    # мигрируем принудительно записи устройств с более чем одним интерфейсом — см. докстринг
    # миграции) — новые записи через новый UI создаются уже с DEVICE_INTERFACE.
    DEVICE_INTERFACE = "device_interface"
    # Только для IPAddress (миграция d8e35a1c7f60) — IP-адрес(а) "ручного" источника ИС
    # (InformationSystemSource.source_type == 'manual'), владелец — сама строка source, а не
    # напрямую информационная система (у одной ИС может быть несколько source-строк, у каждой
    # свой независимый список IP).
    INFORMATION_SYSTEM_SOURCE = "information_system_source"
