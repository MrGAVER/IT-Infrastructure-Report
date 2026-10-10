"""Pydantic-схемы для инкрементальной валидации generic CRUD (код-ревью п.2, High).

Раньше POST/PUT /api/v1/resources/{resource} принимали `payload: dict` без проверки типов:
например, список вместо строки в PhysicalDevice.rack_position всплывал только на INSERT как
малопонятный IntegrityError из SQLAlchemy, а не как понятный 422 на входе. Полный переход всех
~40 ресурсов на статические Pydantic-модели — большая работа (см. код-ревью), поэтому здесь —
только три самых чувствительных: devices, information-systems, vlans (SCHEMAS в конце файла).
Для остальных ресурсов generic CRUD продолжает работать как раньше, через сырой dict.

Схемы валидируют И приводят типы (например, "10" -> 10 для vlan_id), но не заменяют
доменную валидацию в services/validation.py (FK-существование, конфликты позиций в стойке,
бизнес-правила гипервизора и т.п.) — та по-прежнему выполняется после этого слоя.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PhysicalDeviceCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    device_type_id: str = Field(min_length=1)
    serial_number: str = Field(min_length=1, max_length=255)
    manufacturer_id: Optional[str] = None
    model_id: Optional[str] = None
    system_name: Optional[str] = None
    operating_system_id: Optional[str] = None
    embedded_os_id: Optional[str] = None
    siem_enabled: bool = False
    building_id: Optional[str] = None
    room_id: Optional[str] = None
    rack_id: Optional[str] = None
    rack_position: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None
    # Необязательный блок "Сертификат ОАЦ" (см. models.PhysicalDevice) — валидируются здесь, а
    # не оставляются сырым dict, чтобы некорректный формат даты приходил клиенту понятным 422
    # ("value is not a valid date"), а не падал глубже как IntegrityError/тип, специфичный для
    # конкретной СУБД (Date-колонка в Postgres, в отличие от SQLite, не принимает произвольную
    # строку напрямую).
    oac_certificate_number: Optional[str] = Field(default=None, max_length=255)
    oac_certificate_registry_date: Optional[date] = None


class PhysicalDeviceUpdate(BaseModel):
    """Все поля опциональны — generic update применяет только присланные ключи (частичное
    обновление), см. services/crud.update_resource."""
    model_config = ConfigDict(extra="ignore")

    device_type_id: Optional[str] = Field(default=None, min_length=1)
    serial_number: Optional[str] = Field(default=None, min_length=1, max_length=255)
    manufacturer_id: Optional[str] = None
    model_id: Optional[str] = None
    system_name: Optional[str] = None
    operating_system_id: Optional[str] = None
    embedded_os_id: Optional[str] = None
    siem_enabled: Optional[bool] = None
    building_id: Optional[str] = None
    room_id: Optional[str] = None
    rack_id: Optional[str] = None
    rack_position: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None
    oac_certificate_number: Optional[str] = Field(default=None, max_length=255)
    oac_certificate_registry_date: Optional[date] = None


class InformationSystemCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=500)
    type: str = "ИС"
    description: Optional[str] = None
    purpose: Optional[str] = None
    localization: Optional[str] = None
    support_organization_id: Optional[str] = None
    support_method_id: Optional[str] = None
    process_description: Optional[str] = None
    siem_enabled: bool = False
    crypto_protection_enabled: bool = False
    crypto_protection_description_id: Optional[str] = None
    status: str = "active"


class InformationSystemUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = Field(default=None, min_length=1, max_length=500)
    type: Optional[str] = None
    description: Optional[str] = None
    purpose: Optional[str] = None
    localization: Optional[str] = None
    support_organization_id: Optional[str] = None
    support_method_id: Optional[str] = None
    process_description: Optional[str] = None
    siem_enabled: Optional[bool] = None
    crypto_protection_enabled: Optional[bool] = None
    crypto_protection_description_id: Optional[str] = None
    status: Optional[str] = None


class VLANCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # 1-4094 — стандартный диапазон VLAN ID по IEEE 802.1Q.
    vlan_id: int = Field(ge=1, le=4094)
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    domain_id: Optional[str] = None


class VLANUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vlan_id: Optional[int] = Field(default=None, ge=1, le=4094)
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    domain_id: Optional[str] = None


# --- Аутентификация (api/auth.py) ---------------------------------------------------------
# Не входят в RESOURCE_SCHEMAS ниже: /api/v1/auth/* не проходит через generic CRUD
# (services/crud/) — учётным записям нужны хеширование пароля и своя проверка прав, а не
# сырой dict напрямую в модель.

class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1)


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1)
    role: str = "viewer"


class UserUpdateRequest(BaseModel):
    """Все поля опциональны — PUT применяет только присланные ключи (то же частичное обновление,
    что и в generic CRUD, см. PhysicalDeviceUpdate выше)."""
    model_config = ConfigDict(extra="ignore")
    username: Optional[str] = Field(default=None, min_length=1, max_length=150)
    password: Optional[str] = Field(default=None, min_length=1)
    role: Optional[str] = None
    is_active: Optional[bool] = None


class ChangePasswordRequest(BaseModel):
    """Самостоятельная смена СВОЕГО пароля (PUT /auth/me/password) — в отличие от
    UserUpdateRequest (смена ЧУЖОГО пароля админом), требует подтверждение текущим паролем."""
    model_config = ConfigDict(extra="ignore")
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


class AuthSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool


# --- Настройки интерфейса (services/preferences.py, api/preferences.py) -----------------------------
# extra="forbid": набор ключей фиксирован — опечатка или чужой ключ дают 422, а не молча сохраняются.
# Поле, которого нет в теле запроса, не трогается; поле со значением null сбрасывает настройку к значению
# по умолчанию (запись удаляется) — для этого эндпоинты читают тело через model_dump(exclude_unset=True).
PREFERENCE_NUMBER_MAX = 1000  # порог сворачивания строк и размер страницы списка: от 1 до 1000
PAGE_SIZES_MAX_LISTS = 100  # сколько списков с запомненным размером страницы допускается у одного владельца


class UserPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    color_scheme: Optional[str] = Field(default=None, pattern=r"^[a-z0-9_-]{1,32}$")
    device_vlan_collapse_rows: Optional[int] = Field(default=None, ge=1, le=PREFERENCE_NUMBER_MAX)
    # {идентификатор списка: размер страницы}; значение null убирает запомненный размер этого списка.
    # Словарь СЛИВАЕТСЯ с сохранённым, а не заменяет его: так вкладки/устройства не затирают друг у друга
    # размеры разных списков.
    page_sizes: Optional[dict[str, Optional[int]]] = None

    @field_validator("page_sizes")
    @classmethod
    def _check_page_sizes(cls, value: Optional[dict[str, Optional[int]]]) -> Optional[dict[str, Optional[int]]]:
        if value is None:
            return value
        if len(value) > PAGE_SIZES_MAX_LISTS:
            raise ValueError(f"Не больше {PAGE_SIZES_MAX_LISTS} списков за один запрос.")
        for list_id, size in value.items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", list_id):
                raise ValueError(f"Недопустимый идентификатор списка «{list_id}».")
            if size is not None and not 1 <= size <= PREFERENCE_NUMBER_MAX:
                raise ValueError(f"Размер страницы списка «{list_id}» должен быть от 1 до {PREFERENCE_NUMBER_MAX}.")
        return value


class GlobalPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_name: Optional[str] = Field(default=None, max_length=200)

    @field_validator("organization_name")
    @classmethod
    def _strip_organization_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Название организации не может быть пустым (чтобы вернуть значение по умолчанию, передайте null).")
        return stripped


# --- Тела запросов синхронизации и массовых операций (код-ревью п. 8) -------------------------
# Эти эндпоинты принимали `payload: dict`: опечатка в имени поля («interfases») молча давала пустой
# список и УДАЛЯЛА все записи, а OpenAPI-документация была пустой. Теперь верхний уровень тела — схема
# с extra="forbid": неизвестный ключ и неверный тип поля дают понятный 422 на входе. Элементы списков
# (порты, VLAN, ПО…) остаются словарями: их разбор и доменные правила живут в сервисах (services/crud/,
# services/interface_connections.py), и дублировать их в схемах — значит держать два источника истины.
# Роутеры передают сервисам `model_dump(exclude_unset=True)`: ключ, которого клиент не присылал
# (например, groups у PUT /devices/{id}/interfaces — «группы не трогать»), остаётся отсутствующим, а
# не превращается в значение по умолчанию.

class _StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeviceInterfacesSync(_StrictBody):
    """PUT /devices/{id}/interfaces — полный список портов; groups — полный список групп (без ключа группы не трогаются)."""
    interfaces: list[dict[str, Any]] = []
    groups: Optional[list[dict[str, Any]]] = None


class DeviceVlansSync(_StrictBody):
    """PUT /devices/{id}/vlans — полный список VLAN устройства."""
    vlans: list[dict[str, Any]] = []


class DeployedSoftwareSync(_StrictBody):
    """PUT /devices/{id}/deployed-software и /vms/{id}/deployed-software — полный список ПО."""
    deployed_software: list[dict[str, Any]] = []


class VMOpenPortsSync(_StrictBody):
    """PUT /vms/{id}/open-ports — полный список открытых портов ВМ."""
    open_ports: list[dict[str, Any]] = []


class VMIPAddressesSync(_StrictBody):
    """PUT /vms/{id}/ip-addresses — полный список IP-адресов ВМ."""
    ip_addresses: list[dict[str, Any]] = []


class VlanCopyRequest(_StrictBody):
    """POST /devices/{id}/vlan-copy — откуда копировать VLAN."""
    source_device_id: Optional[str] = None


class BulkVlanAssignRequest(_StrictBody):
    """POST /device-vlans/bulk-assign — один VLAN нескольким устройствам."""
    physical_device_ids: list[str] = []
    vlan_id: Optional[str] = None
    description: Optional[str] = None


class VLANDomainMemberRequest(_StrictBody):
    """POST /vlan-domains/{id}/members — добавить устройство в домен."""
    physical_device_id: Optional[str] = None


class VLANDomainSyncRequest(_StrictBody):
    """POST /vlan-domains/{id}/sync — replace=true убирает у участников VLAN домена, которых нет у источника."""
    replace: bool = False


class DeviceStackMemberRequest(_StrictBody):
    """POST /device-stacks/{id}/members — добавить устройство в стек."""
    physical_device_id: Optional[str] = None
    position: int = Field(default=1, ge=1)


# Ресурс (ключ registry.MODEL_MAP) -> (схема для create, схема для update).
# Ресурсы, не перечисленные здесь, продолжают проходить через generic CRUD как сырой dict —
# это осознанное инкрементальное покрытие, а не временное состояние одного ресурса.
RESOURCE_SCHEMAS: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
    "devices": (PhysicalDeviceCreate, PhysicalDeviceUpdate),
    "information-systems": (InformationSystemCreate, InformationSystemUpdate),
    "vlans": (VLANCreate, VLANUpdate),
}
