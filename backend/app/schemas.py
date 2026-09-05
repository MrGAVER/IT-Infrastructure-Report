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

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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
# (services/crud.py) — учётным записям нужны хеширование пароля и своя проверка прав, а не
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


# Ресурс (ключ registry.MODEL_MAP) -> (схема для create, схема для update).
# Ресурсы, не перечисленные здесь, продолжают проходить через generic CRUD как сырой dict —
# это осознанное инкрементальное покрытие, а не временное состояние одного ресурса.
RESOURCE_SCHEMAS: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
    "devices": (PhysicalDeviceCreate, PhysicalDeviceUpdate),
    "information-systems": (InformationSystemCreate, InformationSystemUpdate),
    "vlans": (VLANCreate, VLANUpdate),
}
