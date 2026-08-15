from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(500), unique=True)
    short_name: Mapped[Optional[str]] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)

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

class SupportMethod(TimestampMixin, Base):
    __tablename__ = "support_methods"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)

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

class Building(TimestampMixin, Base):
    __tablename__ = "buildings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[Optional[str]] = mapped_column(String(500))

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

class DeviceType(TimestampMixin, Base):
    __tablename__ = "device_types"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)

class Manufacturer(TimestampMixin, Base):
    __tablename__ = "manufacturers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)

class DeviceModel(TimestampMixin, Base):
    __tablename__ = "device_models"
    __table_args__ = (UniqueConstraint("manufacturer_id", "device_type_id", "model", name="uq_device_model_manufacturer_type_model"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    manufacturer_id: Mapped[str] = mapped_column(ForeignKey("manufacturers.id"), index=True)
    device_type_id: Mapped[str] = mapped_column(ForeignKey("device_types.id"), index=True)
    model: Mapped[str] = mapped_column(String(255))

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

class ISIP(TimestampMixin, Base):
    __tablename__ = "information_system_ips"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    information_system_id: Mapped[str] = mapped_column(ForeignKey("information_systems.id"), index=True)
    ip_address: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[Optional[str]] = mapped_column(String(500))
    protocol: Mapped[Optional[str]] = mapped_column(String(100))
    external_interaction: Mapped[bool] = mapped_column(Boolean, default=False)
    physical_device_id: Mapped[Optional[str]] = mapped_column(ForeignKey("physical_devices.id"), index=True)
    virtual_machine_id: Mapped[Optional[str]] = mapped_column(ForeignKey("virtual_machines.id"), index=True)

class ProtocolPortCatalog(TimestampMixin, Base):
    __tablename__ = "protocol_port_catalogs"
    __table_args__ = (UniqueConstraint("port", "protocol_type", name="uq_protocol_port_catalog_port_type"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    port: Mapped[int] = mapped_column(Integer)
    protocol_type: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)

class ISProtocol(TimestampMixin, Base):
    __tablename__ = "information_system_protocols"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    information_system_id: Mapped[str] = mapped_column(ForeignKey("information_systems.id"), index=True)
    protocol: Mapped[str] = mapped_column(String(200))
    port: Mapped[Optional[int]] = mapped_column(Integer)
    protocol_catalog_id: Mapped[Optional[str]] = mapped_column(ForeignKey("protocol_port_catalogs.id"), index=True)
    version: Mapped[Optional[str]] = mapped_column(String(100))  # legacy, no longer shown in UI
    direction: Mapped[Optional[str]] = mapped_column(String(50))  # legacy, no longer shown in UI
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

class InterfaceIP(TimestampMixin, Base):
    __tablename__ = "interface_ips"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    interface_id: Mapped[str] = mapped_column(ForeignKey("device_interfaces.id"), index=True)
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

class VMIP(TimestampMixin, Base):
    __tablename__ = "vm_ips"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    virtual_machine_id: Mapped[str] = mapped_column(ForeignKey("virtual_machines.id"), index=True)
    ip_address: Mapped[str] = mapped_column(String(64), index=True)
    prefix_length: Mapped[Optional[int]] = mapped_column(Integer)
    purpose: Mapped[Optional[str]] = mapped_column(String(255))
    is_management: Mapped[bool] = mapped_column(Boolean, default=False)

class Container(TimestampMixin, Base):
    __tablename__ = "containers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    virtual_machine_id: Mapped[Optional[str]] = mapped_column(ForeignKey("virtual_machines.id"), index=True)
    physical_device_id: Mapped[Optional[str]] = mapped_column(ForeignKey("physical_devices.id"), index=True)
    runtime: Mapped[Optional[str]] = mapped_column(String(100))
    runtime_version: Mapped[Optional[str]] = mapped_column(String(100))
    purpose: Mapped[Optional[str]] = mapped_column(Text)
    management_ip: Mapped[Optional[str]] = mapped_column(String(64))

class SoftwareAsset(TimestampMixin, Base):
    __tablename__ = "software_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    vendor: Mapped[Optional[str]] = mapped_column(String(255))
    version: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)

class DeviceSoftware(TimestampMixin, Base):
    __tablename__ = "device_software"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    physical_device_id: Mapped[str] = mapped_column(ForeignKey("physical_devices.id"), index=True)
    software_asset_id: Mapped[str] = mapped_column(ForeignKey("software_assets.id"))
    version: Mapped[Optional[str]] = mapped_column(String(100))

class VMSoftware(TimestampMixin, Base):
    __tablename__ = "vm_software"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    virtual_machine_id: Mapped[str] = mapped_column(ForeignKey("virtual_machines.id"), index=True)
    software_asset_id: Mapped[str] = mapped_column(ForeignKey("software_assets.id"))
    version: Mapped[Optional[str]] = mapped_column(String(100))

class InformationSystemSource(TimestampMixin, Base):
    __tablename__ = "information_system_sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    information_system_id: Mapped[str] = mapped_column(ForeignKey("information_systems.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(30))  # manual, device, vm, container
    physical_device_id: Mapped[Optional[str]] = mapped_column(ForeignKey("physical_devices.id"), index=True)
    virtual_machine_id: Mapped[Optional[str]] = mapped_column(ForeignKey("virtual_machines.id"), index=True)
    container_id: Mapped[Optional[str]] = mapped_column(ForeignKey("containers.id"), index=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    purpose: Mapped[Optional[str]] = mapped_column(String(500))
    role: Mapped[Optional[str]] = mapped_column(String(255))
    external_interaction: Mapped[bool] = mapped_column(Boolean, default=False)

class ISDevice(TimestampMixin, Base):
    __tablename__ = "information_system_devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    information_system_id: Mapped[str] = mapped_column(ForeignKey("information_systems.id"), index=True)
    physical_device_id: Mapped[str] = mapped_column(ForeignKey("physical_devices.id"), index=True)
    role: Mapped[Optional[str]] = mapped_column(String(255))

class ISVM(TimestampMixin, Base):
    __tablename__ = "information_system_vms"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    information_system_id: Mapped[str] = mapped_column(ForeignKey("information_systems.id"), index=True)
    virtual_machine_id: Mapped[str] = mapped_column(ForeignKey("virtual_machines.id"), index=True)
    role: Mapped[Optional[str]] = mapped_column(String(255))

class ISContainer(TimestampMixin, Base):
    __tablename__ = "information_system_containers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    information_system_id: Mapped[str] = mapped_column(ForeignKey("information_systems.id"), index=True)
    container_id: Mapped[str] = mapped_column(ForeignKey("containers.id"))
    role: Mapped[Optional[str]] = mapped_column(String(255))

class OpenPort(TimestampMixin, Base):
    __tablename__ = "open_ports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_type: Mapped[str] = mapped_column(String(50))
    owner_id: Mapped[str] = mapped_column(String(36))
    transport_protocol: Mapped[str] = mapped_column(String(10), default="TCP", server_default="TCP")
    port: Mapped[int] = mapped_column(Integer)
    protocol: Mapped[Optional[str]] = mapped_column(String(100))
    protocol_catalog_id: Mapped[Optional[str]] = mapped_column(ForeignKey("protocol_port_catalogs.id"), index=True)
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

