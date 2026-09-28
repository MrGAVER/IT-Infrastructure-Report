from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class SupportOrganization(TimestampMixin, Base):
    __tablename__ = "support_organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(500), unique=True)
    short_name: Mapped[Optional[str]] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)

class CryptoProtectionMeans(TimestampMixin, Base):
    __tablename__ = "crypto_protection_means"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(500), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # Средство криптографической защиты — это конкретный экземпляр в реестре оборудования
    # (аппаратный крипто-модуль, сервер с установленным СКЗИ и т.п.), а не только абстрактное
    # название. Nullable: справочник может содержать записи, ещё не привязанные к конкретному
    # устройству (или устройство ещё не заведено в инвентаризации), и уже существующие записи
    # каталога при накатывании миграции этой FK не имеют.
    physical_device_id: Mapped[Optional[str]] = mapped_column(ForeignKey("physical_devices.id"), index=True)

class SupportMethod(TimestampMixin, Base):
    __tablename__ = "support_methods"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # Способ оказания техподдержки может быть привязан к конкретной организации техподдержки
    # (одна организация — свой набор способов), либо оставаться универсальным (NULL — подходит
    # любой организации). Nullable по той же причине, что и CryptoProtectionMeans.physical_device_id
    # выше: не ломает уже заведённые записи каталога. Согласованность пары "организация ИС ↔
    # способ" при сохранении ИС проверяется в services/validation.validate_support_method_organization.
    support_organization_id: Mapped[Optional[str]] = mapped_column(ForeignKey("support_organizations.id"), index=True)

class PlacementAsset(TimestampMixin, Base):
    """Catalog of equipment / software / interfaces an information system can be hosted on,
    used where a specific physical device, VM or container source is not applicable."""
    __tablename__ = "placement_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(500), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)

class ISPlacementAsset(TimestampMixin, Base):
    __tablename__ = "is_placement_assets"
    __table_args__ = (UniqueConstraint("information_system_id", "placement_asset_id", name="uq_is_placement_asset"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    information_system_id: Mapped[str] = mapped_column(ForeignKey("information_systems.id"), index=True)
    placement_asset_id: Mapped[str] = mapped_column(ForeignKey("placement_assets.id"), index=True)

class Department(TimestampMixin, Base):
    __tablename__ = "departments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(500), unique=True)
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("departments.id"))

class StructuralUnit(TimestampMixin, Base):
    """Организационная структурная единица (филиал/площадка/подразделение и т.п.), к которой
    привязывается адрес размещения физического оборудования (см. Building.structural_unit_id).
    Иерархия через parent_id — тот же паттерн, что и у Department, — позволяет выбрать при
    генерации отчёта родительскую единицу и автоматически захватить все вложенные (см.
    reporting.py: _expand_structural_unit_ids)."""
    __tablename__ = "structural_units"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(500), unique=True)
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("structural_units.id"), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)

class Building(TimestampMixin, Base):
    __tablename__ = "buildings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[Optional[str]] = mapped_column(String(500))
    structural_unit_id: Mapped[Optional[str]] = mapped_column(ForeignKey("structural_units.id"), index=True)

class Room(TimestampMixin, Base):
    __tablename__ = "rooms"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))

class Rack(TimestampMixin, Base):
    __tablename__ = "racks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    height_u: Mapped[Optional[int]] = mapped_column(Integer)

class DeviceCategory(TimestampMixin, Base):
    """Иерархическая категория типов устройств (тот же паттерн, что OperatingSystemCategory/
    StructuralUnit: parent_id, подкатегории заводятся администратором обычным CRUD, без изменения
    схемы). diagram_shape/diagram_color — базовый визуальный стиль для автогенерации иконки узла
    на диаграмме топологии сети; оба поля nullable и наследуются от ближайшего предка по parent_id,
    у которого они заданы (см. services/diagram_icons.resolve_style) — так подкатегориям, которым
    не нужен собственный визуальный стиль, не приходится его дублировать."""
    __tablename__ = "device_categories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("device_categories.id"), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    diagram_shape: Mapped[Optional[str]] = mapped_column(String(30))  # server|switch|firewall|workstation|peripheral|generic
    diagram_color: Mapped[Optional[str]] = mapped_column(String(20))  # HEX, напр. '#4f7cff'

class DeviceType(TimestampMixin, Base):
    __tablename__ = "device_types"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    # Явный признак вместо сравнения строк ('сервер'/'storage' и т.п. в имени, см.
    # services/validation.validate_vm_host) — переименование типа устройства в справочнике
    # больше не ломает молча правило "на чём можно разместить VM". Проставляется при создании
    # стандартных записей (services/catalogs.py) и редактируется как обычное поле через CRUD.
    allows_vm_hosting: Mapped[bool] = mapped_column(Boolean, default=False)
    # Обязательное поле (см. services/catalogs._seed_device_types и миграцию 2 диаграммы топологии
    # сети) — используется для автогенерации иконки узла (форма/цвет наследуются от категории).
    category_id: Mapped[str] = mapped_column(ForeignKey("device_categories.id"), index=True)

class Manufacturer(TimestampMixin, Base):
    __tablename__ = "manufacturers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)

class DiagramIcon(TimestampMixin, Base):
    """Каталог пользовательских иконок для диаграммы топологии сети — только для случаев, когда
    автогенерации по категории (DeviceCategory.diagram_shape/diagram_color) недостаточно (напр.
    нужен фирменный вид конкретной модели). Хранится как SVG-текст (тот же подход, что
    ReportTemplate.config для JSON) — несколько КБ на иконку, не влияет на объём БД."""
    __tablename__ = "diagram_icons"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    svg_markup: Mapped[str] = mapped_column(Text)

class DeviceModel(TimestampMixin, Base):
    __tablename__ = "device_models"
    __table_args__ = (UniqueConstraint("manufacturer_id", "device_type_id", "model", name="uq_device_model_manufacturer_type_model"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    manufacturer_id: Mapped[str] = mapped_column(ForeignKey("manufacturers.id"), index=True)
    device_type_id: Mapped[str] = mapped_column(ForeignKey("device_types.id"), index=True)
    model: Mapped[str] = mapped_column(String(255))
    # Ручное переопределение автогенерируемой иконки для ВСЕХ устройств этой модели (раздел 4.3
    # ТЗ диаграммы топологии сети). Приоритет ниже, чем PhysicalDevice.diagram_icon_id.
    diagram_icon_id: Mapped[Optional[str]] = mapped_column(ForeignKey("diagram_icons.id"), index=True)

class EmbeddedOperatingSystem(TimestampMixin, Base):
    __tablename__ = "embedded_operating_systems"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_embedded_os_name_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    version: Mapped[Optional[str]] = mapped_column(String(255))
    vendor: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)

class PhysicalDevice(TimestampMixin, Base):
    __tablename__ = "physical_devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_type_id: Mapped[str] = mapped_column(ForeignKey("device_types.id"), index=True)
    manufacturer_id: Mapped[Optional[str]] = mapped_column(ForeignKey("manufacturers.id"), index=True)
    model_id: Mapped[Optional[str]] = mapped_column(ForeignKey("device_models.id"), index=True)
    serial_number: Mapped[str] = mapped_column(String(255), unique=True)
    system_name: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    operating_system_id: Mapped[Optional[str]] = mapped_column(ForeignKey("operating_systems.id"), index=True)
    embedded_os_id: Mapped[Optional[str]] = mapped_column(ForeignKey("embedded_operating_systems.id"), index=True)
    siem_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    building_id: Mapped[Optional[str]] = mapped_column(ForeignKey("buildings.id"), index=True)
    room_id: Mapped[Optional[str]] = mapped_column(ForeignKey("rooms.id"), index=True)
    rack_id: Mapped[Optional[str]] = mapped_column(ForeignKey("racks.id"), index=True)
    rack_position: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # Ручное переопределение автогенерируемой иконки для ЭТОГО конкретного устройства (раздел 4.3
    # ТЗ диаграммы топологии сети). Приоритет выше, чем DeviceModel.diagram_icon_id.
    diagram_icon_id: Mapped[Optional[str]] = mapped_column(ForeignKey("diagram_icons.id"), index=True)
    # Необязательный блок "Сертификат ОАЦ" — заполняется, если устройство реализует
    # сертифицированное средство криптографической защиты (см. CryptoProtectionMeans.
    # physical_device_id выше). Оба поля nullable и независимы друг от друга: пара
    # "заполнено/не заполнено" не проверяется — карточка устройства не обязана иметь сертификат.
    oac_certificate_number: Mapped[Optional[str]] = mapped_column(String(255))
    oac_certificate_registry_date: Mapped[Optional[date]] = mapped_column(Date)

class DeviceStack(TimestampMixin, Base):
    """Пункт 5 правки "создание физического устройства": стек физических устройств (например,
    стек коммутаторов) — логическая группа, физически соединённая между собой через указанные
    порты. Само межстековое кабелирование НЕ дублируется отдельной моделью — это обычные
    Connection (см. класс ниже) между интерфейсами устройств-участников: "стековые" среди них —
    это просто те, у которых ОБА конца принадлежат участникам ОДНОГО стека (см.
    services/crud.py:stack_detail — вычисляется на лету, а не хранится отдельным флагом, чтобы
    не рассинхронизироваться при добавлении/удалении обычных Connection в обход стека)."""
    __tablename__ = "device_stacks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)


class DeviceStackMember(TimestampMixin, Base):
    """Членство устройства в стеке. UniqueConstraint только на physical_device_id (не на паре
    stack_id+physical_device_id) — намеренно: устройство физически может состоять максимум в
    ОДНОМ стеке одновременно, в отличие от, например, VLANDomainDevice, где участие в НЕСКОЛЬКИХ
    доменов — обычный случай."""
    __tablename__ = "device_stack_members"
    __table_args__ = (UniqueConstraint("physical_device_id", name="uq_device_stack_member_device"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    stack_id: Mapped[str] = mapped_column(ForeignKey("device_stacks.id"), index=True)
    physical_device_id: Mapped[str] = mapped_column(ForeignKey("physical_devices.id"), index=True)
    # Позиция участника в стеке (1, 2, 3...) — соответствует физическому "stack member ID" на
    # реальном оборудовании (напр. `show switch` на Cisco). Не участвует ни в какой валидации
    # уникальности внутри стека: два участника с одинаковой позицией — это на совести того, кто
    # заполняет форму, а не то, что стоит блокировать (иногда позиции временно задваивают при
    # физической замене одного члена стека на другой).
    position: Mapped[int] = mapped_column(Integer, default=1)

class InformationSystem(TimestampMixin, Base):
    __tablename__ = "information_systems"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    number: Mapped[Optional[int]] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(500), unique=True)
    type: Mapped[str] = mapped_column(String(100), default="ИС")
    description: Mapped[Optional[str]] = mapped_column(Text)
    purpose: Mapped[Optional[str]] = mapped_column(Text)
    localization: Mapped[Optional[str]] = mapped_column(Text)
    support_organization_id: Mapped[Optional[str]] = mapped_column(ForeignKey("support_organizations.id"), index=True)
    support_method_id: Mapped[Optional[str]] = mapped_column(ForeignKey("support_methods.id"), index=True)
    process_description: Mapped[Optional[str]] = mapped_column(Text)
    siem_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    crypto_protection_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    crypto_protection_description_id: Mapped[Optional[str]] = mapped_column(ForeignKey("crypto_protection_means.id"), index=True)
    status: Mapped[str] = mapped_column(String(50), default="active")

class ISDepartment(TimestampMixin, Base):
    __tablename__ = "information_system_departments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    information_system_id: Mapped[str] = mapped_column(ForeignKey("information_systems.id"), index=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"))

class ProtocolPortCatalog(TimestampMixin, Base):
    __tablename__ = "protocol_port_catalogs"
    __table_args__ = (UniqueConstraint("port", "protocol_type", name="uq_protocol_port_catalog_port_type"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    port: Mapped[int] = mapped_column(Integer)
    protocol_type: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)

class ISProtocol(TimestampMixin, Base):
    """Протокол передачи данных ИС (Лист 1, колонка "Протокол передачи данных").

    protocol/port больше не отдельные колонки (правка "справочник — единственный источник
    правды для порта/протокола", по аналогии с OpenPort, см. миграцию
    b7f2c1e5a904_isprotocol_catalog_required): значения ВСЕГДА читаются join'ом к
    protocol_port_catalogs по protocol_catalog_id (обязателен, NOT NULL) — правка справочника
    сразу отражается на уже сохранённых строках, без их отдельного пересохранения. description —
    отдельное, СВОЁ поле записи (a не справочника): произвольный комментарий пользователя к
    конкретному использованию протокола в этой ИС (см. ISProtocolsListEditor.vue), не путать с
    ProtocolPortCatalog.description (общее техническое описание самого протокола) — reporting.py
    показывает оба значения вместе, не выбирая одно вместо другого."""
    __tablename__ = "information_system_protocols"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    information_system_id: Mapped[str] = mapped_column(ForeignKey("information_systems.id"), index=True)
    protocol_catalog_id: Mapped[str] = mapped_column(ForeignKey("protocol_port_catalogs.id"), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)

class DeviceInterface(TimestampMixin, Base):
    __tablename__ = "device_interfaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    physical_device_id: Mapped[str] = mapped_column(ForeignKey("physical_devices.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    interface_type_id: Mapped[Optional[str]] = mapped_column(ForeignKey("interface_types.id"), index=True)
    mac_address: Mapped[Optional[str]] = mapped_column(String(64))
    speed_id: Mapped[Optional[str]] = mapped_column(ForeignKey("interface_speeds.id"), index=True)
    is_management: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_data_transfer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # 'access' | 'trunk' — режим порта (п.1.4.3.2 / фикс п.1.3.9). Хранится на самом интерфейсе, а
    # не выводится из InterfaceVLAN.mode: при 0 назначенных VLAN на интерфейсе нет ни одной связи
    # interface_vlans, из которой можно было бы восстановить режим при следующей загрузке — без
    # этого поля access-порт без VLAN после сохранения и перезагрузки формы молча превращался в
    # trunk (см. миграцию 5b5ea0e81d32 для бэкфилла существующих данных).
    vlan_mode: Mapped[str] = mapped_column(String(10), default="trunk", server_default="trunk", nullable=False)


class InterfaceType(TimestampMixin, Base):
    __tablename__ = "interface_types"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)

class InterfaceSpeed(TimestampMixin, Base):
    __tablename__ = "interface_speeds"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)

class IPAddress(TimestampMixin, Base):
    """IP-адрес владельца — интерфейс устройства, ВМ или источник ИС (owner_type/owner_id, тот же
    паттерн, что уже применён к OpenPort/DeployedSoftware). Объединяет прежние отдельные таблицы
    interface_ips/vm_ips и IP-адрес(а) InformationSystemSource (миграция d8e35a1c7f60, вопросы
    1/3/5 отчёта по анализу БД — согласовано с заказчиком): все три случая хранили идентичный по
    смыслу набор данных «IP-адрес + необязательные префикс/назначение/признак IP администрирования
    у конкретного владельца», отличаясь только именем FK-колонки владельца (для interface_ips/
    vm_ips) или тем, что раньше несколько IP одного источника ИС хранились одной строкой через
    запятую в единственном текстовом поле (для information_system_sources.ip_address) — теперь
    каждый IP-адрес источника ИС тоже отдельная строка (owner_type="information_system_source",
    owner_id=<id строки InformationSystemSource>), что вместе с этим и даёт заказчику несколько
    отдельных полей ввода IP вместо одного текстового.

    Container.management_ip НЕ перенесён сюда: подтверждено, что поле не редактировалось ни через
    один UI (см. комментарий в ContainerFormModal.vue "у контейнера нет своего IP на уровне
    отчёта") — мёртвая колонка, удалена той же миграцией, а не активирована задним числом."""
    __tablename__ = "ip_addresses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_type: Mapped[str] = mapped_column(String(50))
    owner_id: Mapped[str] = mapped_column(String(36))
    ip_address: Mapped[str] = mapped_column(String(64), index=True)
    prefix_length: Mapped[Optional[int]] = mapped_column(Integer)
    purpose: Mapped[Optional[str]] = mapped_column(String(255))
    is_management: Mapped[bool] = mapped_column(Boolean, default=False)

class VLANDomain(TimestampMixin, Base):
    __tablename__ = "vlan_domains"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    source_device_id: Mapped[Optional[str]] = mapped_column(ForeignKey("physical_devices.id"), index=True)
    auto_sync: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

class VLANDomainDevice(TimestampMixin, Base):
    __tablename__ = "vlan_domain_devices"
    __table_args__ = (UniqueConstraint("domain_id", "physical_device_id", name="uq_vlan_domain_device"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    domain_id: Mapped[str] = mapped_column(ForeignKey("vlan_domains.id"), index=True)
    physical_device_id: Mapped[str] = mapped_column(ForeignKey("physical_devices.id"), index=True)

class VLAN(TimestampMixin, Base):
    __tablename__ = "vlans"
    __table_args__ = (UniqueConstraint("domain_id", "vlan_id", name="uq_vlan_domain_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    vlan_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    domain_id: Mapped[Optional[str]] = mapped_column(ForeignKey("vlan_domains.id"), index=True)

class DeviceTypeVLAN(TimestampMixin, Base):
    __tablename__ = "device_type_vlans"
    __table_args__ = (UniqueConstraint("device_type_id", "vlan_id", name="uq_device_type_vlan"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_type_id: Mapped[str] = mapped_column(ForeignKey("device_types.id"), index=True)
    vlan_id: Mapped[str] = mapped_column(ForeignKey("vlans.id"), index=True)

class PhysicalDeviceVLAN(TimestampMixin, Base):
    __tablename__ = "physical_device_vlans"
    __table_args__ = (UniqueConstraint("physical_device_id", "vlan_id", name="uq_physical_device_vlan"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    physical_device_id: Mapped[str] = mapped_column(ForeignKey("physical_devices.id"), index=True)
    vlan_id: Mapped[str] = mapped_column(ForeignKey("vlans.id"), index=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    prefix_length: Mapped[Optional[int]] = mapped_column(Integer)
    is_management: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

class InterfaceVLAN(TimestampMixin, Base):
    __tablename__ = "interface_vlans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    interface_id: Mapped[str] = mapped_column(ForeignKey("device_interfaces.id"), index=True)
    vlan_id: Mapped[str] = mapped_column(ForeignKey("vlans.id"), index=True)
    mode: Mapped[Optional[str]] = mapped_column(String(30))

class Connection(TimestampMixin, Base):
    __tablename__ = "connections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_interface_id: Mapped[str] = mapped_column(ForeignKey("device_interfaces.id"), index=True)
    destination_interface_id: Mapped[str] = mapped_column(ForeignKey("device_interfaces.id"), index=True)
    connection_type_id: Mapped[str] = mapped_column(ForeignKey("connection_types.id"))
    purpose: Mapped[Optional[str]] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(Text)


class ConnectionType(TimestampMixin, Base):
    __tablename__ = "connection_types"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)

class OperatingSystemCategory(TimestampMixin, Base):
    __tablename__ = "operating_system_categories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # Явный признак вместо сравнения category.name.casefold() == 'гипервизор' (см.
    # services/validation.validate_hypervisor) — та же мотивация, что у DeviceType.allows_vm_hosting.
    is_hypervisor: Mapped[bool] = mapped_column(Boolean, default=False)

class OperatingSystem(TimestampMixin, Base):
    __tablename__ = "operating_systems"
    __table_args__ = (UniqueConstraint("category_id", "name", "version", name="uq_operating_system_category_name_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    category_id: Mapped[str] = mapped_column(ForeignKey("operating_system_categories.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    version: Mapped[Optional[str]] = mapped_column(String(255))
    vendor: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)

class VirtualMachine(TimestampMixin, Base):
    __tablename__ = "virtual_machines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    operating_system_id: Mapped[Optional[str]] = mapped_column(ForeignKey("operating_systems.id"), index=True)
    physical_device_id: Mapped[Optional[str]] = mapped_column(ForeignKey("physical_devices.id"), index=True)
    hypervisor_os_id: Mapped[Optional[str]] = mapped_column(ForeignKey("operating_systems.id"), index=True)
    purpose: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="active")
    description: Mapped[Optional[str]] = mapped_column(Text)

class Container(TimestampMixin, Base):
    __tablename__ = "containers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    virtual_machine_id: Mapped[Optional[str]] = mapped_column(ForeignKey("virtual_machines.id"), index=True)
    physical_device_id: Mapped[Optional[str]] = mapped_column(ForeignKey("physical_devices.id"), index=True)
    runtime: Mapped[Optional[str]] = mapped_column(String(100))
    runtime_version: Mapped[Optional[str]] = mapped_column(String(100))
    purpose: Mapped[Optional[str]] = mapped_column(Text)

class SoftwareAsset(TimestampMixin, Base):
    __tablename__ = "software_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    vendor: Mapped[Optional[str]] = mapped_column(String(255))
    version: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)

class DeployedSoftware(TimestampMixin, Base):
    """Развёрнутый программный актив на устройстве/ВМ (1С, веб-сервер, файловый сервер, AD и т.п.
    — Лист 4 отчёта, столбец «Какие программные активы развёрнуты»). owner_type/owner_id вместо
    прежних отдельных таблиц device_software/vm_software (миграция c4a91e6f2b83, объединены по той
    же причине и тем же паттерном, что уже применён к OpenPort: логически идентичные данные —
    связь «владелец (устройство или ВМ) ↔ запись каталога software_assets + версия» — вводились в
    двух разных формах и хранились в двух отдельных таблицах, отличавшихся только именем FK-
    колонки владельца."""
    __tablename__ = "deployed_software"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_type: Mapped[str] = mapped_column(String(50))
    owner_id: Mapped[str] = mapped_column(String(36))
    software_asset_id: Mapped[str] = mapped_column(ForeignKey("software_assets.id"))
    version: Mapped[Optional[str]] = mapped_column(String(100))

class InformationSystemSource(TimestampMixin, Base):
    """Связь ИС с оборудованием/ВМ/контейнером или произвольный IP-источник (source_type: manual,
    device, vm, container) — Лист 1, столбцы "Оборудование..." и "IP-адрес...". Единственная и
    обязательная модель этой связи: четыре прежние отдельные таблицы-связки (information_system_
    devices/vms/containers/ips) удалены (миграция b7f2c1e5a904_isprotocol_catalog_required) вместе
    со всем их поддерживающим кодом — до этого они существовали параллельно как исторический
    fallback для записей ИС, ни разу не пересохранённых через актуальную форму.

    ip_address (раньше — своя колонка, несколько адресов через запятую в одной строке) удалена
    миграцией d8e35a1c7f60: IP-адреса источника (актуально только для source_type="manual" — для
    остальных типов IP берётся из связанного оборудования/ВМ) теперь отдельные строки IPAddress
    с owner_type="information_system_source", owner_id=<id этой записи> — по одному адресу на
    строку, а не через запятую (вопрос 3/5 отчёта по анализу БД, согласовано с заказчиком: "можно
    добавлять несколько полей IP вместо одного текстового поля").

    owner_id (миграция 944bd490d967, п.5 отчёта по анализу БД) заменяет три прежние nullable FK-
    колонки (physical_device_id/virtual_machine_id/container_id — у любой строки была заполнена от
    силы одна, конкретно какая — определялась уже существующим source_type). Тот же приём, что и у
    OpenPort/DeployedSoftware/IPAddress (owner_type/owner_id), только здесь роль owner_type играет
    само поле source_type — заводить для него отдельную колонку было бы чистым дублированием, само
    значение и так однозначно: 'device' → PhysicalDevice, 'vm' → VirtualMachine,
    'container' → Container, 'manual' → owner_id всегда NULL.

    ВАЖНО — семантика владения здесь ОБРАТНАЯ по отношению к тем трём моделям: там владелец
    (устройство/ВМ) владеет дочерней записью и её осиротение при удалении владельца желательно
    (см. _POLYMORPHIC_OWNER_CLEANUP в services/crud.py). Здесь ИС лишь ССЫЛАЕТСЯ на оборудование
    как на место размещения — удаление устройства/ВМ/контейнера, на который ссылается хотя бы одна
    строка source, должно быть ЗАБЛОКИРОВАНО (иначе регуляторный отчёт будет описывать размещение
    ИС на уже не существующем оборудовании). Раньше это обеспечивал сам FK на уровне БД; owner_id
    настоящим FK не является (ссылается на одну из трёх разных таблиц в зависимости от source_type
    — единая FK-колонка не может ссылаться на разные таблицы), поэтому защита воссоздана вручную в
    services/crud.py:assert_deletable() (вызывается из delete_resource; плюс before_delete и триггеры БД, см. services/integrity.py) — решение
    заказчика по итогам рассмотрения архитектурной развилки (убрать защиту было неприемлемо для
    точности отчёта)."""
    __tablename__ = "information_system_sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    information_system_id: Mapped[str] = mapped_column(ForeignKey("information_systems.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(30))  # manual, device, vm, container — также играет роль owner_type
    owner_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)  # id устройства/ВМ/контейнера по source_type; NULL при source_type='manual'. Не настоящий FK — см. докстринг класса
    purpose: Mapped[Optional[str]] = mapped_column(String(500))
    role: Mapped[Optional[str]] = mapped_column(String(255))
    external_interaction: Mapped[bool] = mapped_column(Boolean, default=False)

class OpenPort(TimestampMixin, Base):
    """Открытый порт/протокол владельца (ВМ или интерфейс физ. устройства, см. owner_type/owner_id).

    port/protocol НЕ принимаются от клиента напрямую (правка "убрать текстовые поля Порт/Протокол,
    эта информация уже есть в справочнике портов") — единственный вход для них — protocol_catalog_id.
    port/protocol больше не отдельные колонки (правка "справочник — единственный источник правды
    для порта/протокола", см. миграцию b7f2c1e5a904_isprotocol_catalog_required): значения ВСЕГДА
    читаются join'ом к protocol_port_catalogs по protocol_catalog_id при каждом чтении (см.
    services/serialization.py:enrich_open_port(s), reporting.py:_open_port_label) — правка записи
    справочника сразу отражается на уже созданных портах, без их отдельного пересохранения (то,
    чего не было до этой правки — старая версия хранила снимок port/protocol на самой записи и
    актуализировала его только при пересохранении именно этой записи порта). protocol_catalog_id
    обязателен (NOT NULL, миграция a1b7c9d3e502)."""
    __tablename__ = "open_ports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_type: Mapped[str] = mapped_column(String(50))
    owner_id: Mapped[str] = mapped_column(String(36))
    transport_protocol: Mapped[str] = mapped_column(String(10), default="TCP", server_default="TCP")
    protocol_catalog_id: Mapped[str] = mapped_column(ForeignKey("protocol_port_catalogs.id"), index=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(Text)

class ReportTemplate(TimestampMixin, Base):
    """Пользовательский шаблон произвольного отчёта (конструктор отчётов).

    Вся структура отчёта (листы/блоки, колонки, фильтры, параметры) хранится одним JSON-документом
    в config, а не отдельными таблицами: набор допустимых полей и связей выводится динамически из
    MODEL_MAP (см. services/report_meta.py), поэтому жёсткая реляционная схема под конструктор
    неизбежно дублировала бы её и требовала бы миграции при каждом новом типе колонки. Формат JSON
    описан в services/report_engine.py.
    """
    __tablename__ = "report_templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(10), default="xlsx")  # xlsx | docx
    config: Mapped[str] = mapped_column(Text)  # JSON: sheets/blocks, колонки, фильтры, параметры

class ReportTemplateVersion(TimestampMixin, Base):
    """Снимок состояния ReportTemplate, сохранённый непосредственно перед тем, как оно было
    заменено (обновление шаблона или восстановление другой версии). Раньше PUT
    /report-templates/{id} просто перезаписывал config — случайное сохранение стирало предыдущую
    версию без возможности отката."""
    __tablename__ = "report_template_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    report_template_id: Mapped[str] = mapped_column(ForeignKey("report_templates.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(10))
    config: Mapped[str] = mapped_column(Text)

class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(50))
    details: Mapped[Optional[str]] = mapped_column(Text)

class User(TimestampMixin, Base):
    """Учётная запись приложения. Существует независимо от AuthSettings.enabled — учётные записи
    можно завести заранее, пока переключатель ещё выключен (см. services/auth.py), а не только
    после включения аутентификации. password_hash — самоописывающийся формат
    'pbkdf2_sha256$<итерации>$<соль-b64>$<хеш-b64>' (см. services/auth.hash_password), это
    позволяет поднять число итераций в будущем, не инвалидируя уже существующие пароли (старые
    хеши перевычисляются на следующий успешный вход — services/auth.authenticate).

    failed_attempts/locked_until — защита от подбора пароля (см. services/auth.MAX_FAILED_ATTEMPTS):
    после серии неудачных попыток учётная запись временно блокируется независимо от того, был ли
    следующий пароль верным."""
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

class AuthSession(Base):
    """Активная сессия входа. Хранится ХЕШ токена (sha256), а не сам токен — токен виден клиенту
    только один раз, в ответе на /api/v1/auth/login, и не восстановим из БД (в т.ч. из стухшей
    infra_registry.db в репозитории, см. память проекта про этот файл). user_agent/ip_address —
    только для отображения администратору списка активных входов (см. GET /auth/sessions), не
    участвуют в проверке подлинности запроса."""
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255))
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))

class AuthSettings(Base):
    """Синглтон (id зафиксирован строкой 'singleton', ровно одна строка в таблице) — глобальный
    тумблер аутентификации. По умолчанию enabled=False: однопользовательский локальный режим,
    все /api/* открыты без токена, поведение идентично состоянию приложения до этой фичи (см.
    services/auth.py:auth_gate_middleware). Отдельная таблица, а не запись в каком-то общем
    key-value справочнике настроек — на момент написания это единственная серверная настройка,
    заводить ради неё общий механизм преждевременно."""
    __tablename__ = "auth_settings"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="singleton")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class SavedDiagram(TimestampMixin, Base):
    """Независимая сохранённая диаграмма топологии сети (не синглтон — unique(name), может быть
    несколько диаграмм с разными фильтрами охвата, см. ТЗ раздел 6). scope_filter хранится как
    JSON в Text (тот же подход, что ReportTemplate.config) — портируемость SQLite/PostgreSQL."""
    __tablename__ = "saved_diagrams"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    scope_filter: Mapped[str] = mapped_column(Text)  # JSON: фильтр охвата (структурная единица, VLAN, здание...)
    group_by: Mapped[str] = mapped_column(String(30), default="structural_unit")  # structural_unit|vlan|building|device_category
    collapse_threshold: Mapped[int] = mapped_column(Integer, default=20)
    last_export_format: Mapped[Optional[str]] = mapped_column(String(10))  # drawio|vsdx|svg

class DiagramLayout(TimestampMixin, Base):
    """Раскладка узлов диаграммы — 1:1 к SavedDiagram. Хранится отдельной таблицей (не колонкой
    SavedDiagram), т.к. это часть контракта "перегенерировать граф, сохранив раскладку"
    (POST /diagrams/{id}/regenerate) — раскладка переживает пересборку графа из реестра."""
    __tablename__ = "diagram_layouts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    saved_diagram_id: Mapped[str] = mapped_column(ForeignKey("saved_diagrams.id", ondelete="CASCADE"), unique=True, index=True)
    node_positions: Mapped[str] = mapped_column(Text)  # JSON: {"<device_id|'group:'+group_key>": {"x":..,"y":..}}
    viewport: Mapped[Optional[str]] = mapped_column(Text)  # JSON: {"zoom":..,"pan_x":..,"pan_y":..}
    auto_layout_algorithm: Mapped[str] = mapped_column(String(30), default="hierarchical")

class DiagramGroupState(TimestampMixin, Base):
    """Явное состояние сворачивания одной группы узлов одной диаграммы (1:N к SavedDiagram) — см.
    ТЗ раздел 8. Отсутствие записи для group_key означает "порог ещё не достигнут"; при достижении
    порога и отсутствии явной записи она создаётся с is_collapsed=True, а дальнейший
    regenerate её не перезаписывает (только device_count)."""
    __tablename__ = "diagram_group_states"
    __table_args__ = (UniqueConstraint("saved_diagram_id", "group_key", name="uq_diagram_group_state"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    saved_diagram_id: Mapped[str] = mapped_column(ForeignKey("saved_diagrams.id", ondelete="CASCADE"), index=True)
    group_key: Mapped[str] = mapped_column(String(255))
    is_collapsed: Mapped[bool] = mapped_column(Boolean, default=True)
    device_count: Mapped[int] = mapped_column(Integer, default=0)
    custom_threshold: Mapped[Optional[int]] = mapped_column(Integer)  # NULL — наследует SavedDiagram.collapse_threshold

