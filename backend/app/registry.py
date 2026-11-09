from __future__ import annotations
from .models import (
    AuditLog, Building, Connection, ConnectionType, Container, Department, DeviceCategory, DeviceInterface,
    DeployedSoftware, DeviceModel, DeviceStack, DeviceStackMember, DeviceStackVLAN, DeviceType, DiagramIcon, IPAddress, InterfaceSpeed, InterfaceType,
    ISDepartment, ISProtocol, InformationSystem, InformationSystemSource, InterfaceVLAN, OpenPort, ProtocolPortCatalog,
    Manufacturer, OperatingSystem, OperatingSystemCategory, EmbeddedOperatingSystem, DeviceTypeVLAN, PhysicalDeviceVLAN, SupportOrganization, SupportMethod, CryptoProtectionMeans, PlacementAsset, ISPlacementAsset, PhysicalDevice,
    Rack, Room, SoftwareAsset, StructuralUnit, VLAN, VLANDomain, VLANDomainDevice, VirtualMachine,
)

# Ресурсы, доступные через generic CRUD только для чтения. audit-log должен быть неизменяемым:
# audit() (см. services/crud/) уже не даёт создать запись audit-log из кода приложения, а
# generic-эндпоинты POST/PUT/DELETE /api/v1/resources/{resource} (services/crud/:
# create_resource/update_resource/delete_resource) обязаны проверять этот набор — иначе любой
# клиент может подделать или стереть журнал аудита через /api/v1/resources/audit-log.
READONLY_RESOURCES = frozenset({'audit-log', 'device-stack-vlans'})

MODEL_MAP = {
    # Фикс: справочник 'organizations' удалён целиком (снят из MODEL_MAP/DISPLAY_NAMES здесь, см.
    # миграцию с DROP TABLE organizations) — на него нигде не было ни одной FK-ссылки (в отличие
    # от support-organizations), только автосоздаваемая при пустой БД запись-заглушка
    # "Организация"/"ООО «Организация»" (_seed_singleton_records в services/catalogs.py), которая
    # ничего не значила и ни на что не влияла.
    'support-organizations': SupportOrganization, 'support-methods': SupportMethod, 'crypto-protection-means': CryptoProtectionMeans, 'departments': Department, 'structural-units': StructuralUnit, 'buildings': Building, 'rooms': Room, 'racks': Rack,
    'device-categories': DeviceCategory, 'device-types': DeviceType, 'manufacturers': Manufacturer, 'device-models': DeviceModel, 'diagram-icons': DiagramIcon,
    'os-categories': OperatingSystemCategory, 'operating-systems': OperatingSystem, 'embedded-os': EmbeddedOperatingSystem, 'device-type-vlans': DeviceTypeVLAN, 'device-vlans': PhysicalDeviceVLAN, 'devices': PhysicalDevice,
    'information-systems': InformationSystem, 'is-departments': ISDepartment, 'is-protocols': ISProtocol, 'protocol-port-catalog': ProtocolPortCatalog,
    'placement-assets': PlacementAsset, 'is-placement-assets': ISPlacementAsset,
    'interfaces': DeviceInterface, 'interface-types': InterfaceType,
    'interface-speeds': InterfaceSpeed, 'vlans': VLAN, 'vlan-domains': VLANDomain, 'vlan-domain-devices': VLANDomainDevice, 'interface-vlans': InterfaceVLAN,
    'connection-types': ConnectionType, 'connections': Connection, 'vms': VirtualMachine, 'ip-addresses': IPAddress,
    'containers': Container, 'software-assets': SoftwareAsset, 'deployed-software': DeployedSoftware, 'is-sources': InformationSystemSource,
    'open-ports': OpenPort, 'audit-log': AuditLog,
    'device-stacks': DeviceStack, 'device-stack-members': DeviceStackMember, 'device-stack-vlans': DeviceStackVLAN,
}

DISPLAY_NAMES = {
    'support-organizations':'Организации технической поддержки', 'support-methods':'Способы оказания технической поддержки', 'crypto-protection-means':'Средства криптографической защиты информации (СКЗИ)', 'departments':'Подразделения', 'structural-units':'Структурные единицы', 'buildings':'Здания', 'rooms':'Помещения', 'racks':'Стойки',
    'device-categories':'Категории устройств (диаграмма топологии сети)', 'device-types':'Типы устройств', 'manufacturers':'Производители', 'device-models':'Каталог оборудования (Производитель → Тип → Модель)', 'diagram-icons':'Пользовательские иконки диаграммы', 'diagrams':'Диаграммы топологии сети',  # нет в MODEL_MAP, но это entity_type записей аудита api/diagrams.py — подпись нужна журналу (test_registry_display_names.py)
    'os-categories':'Категории ОС', 'operating-systems':'ОС и гипервизоры', 'embedded-os':'Встроенные ОС', 'device-type-vlans':'VLAN типов устройств', 'device-vlans':'VLAN физических устройств', 'devices':'Физические устройства',
    'information-systems':'Информационные системы', 'is-departments':'ИС ↔ подразделения', 'is-protocols':'Протоколы ИС', 'protocol-port-catalog':'Справочник протоколов и портов',
    'placement-assets':'Оборудование, ПО, интерфейс на которых размещается ИС', 'is-placement-assets':'ИС ↔ оборудование/ПО/интерфейс размещения',
    'interfaces':'Интерфейсы', 'interface-types':'Типы интерфейсов', 'interface-speeds':'Скорости интерфейсов',
    'vlans':'VLAN', 'vlan-domains':'Домены VLAN', 'vlan-domain-devices':'Устройства в доменах VLAN', 'interface-vlans':'Интерфейсы ↔ VLAN', 'connection-types':'Типы подключений', 'connections':'Подключения',
    'vms':'Виртуальные машины', 'ip-addresses':'IP-адреса (интерфейсов устройств, ВМ и источников ИС — owner_type/owner_id, см. models.IPAddress)', 'containers':'Контейнеры', 'software-assets':'Программные активы',
    'deployed-software':'ПО, развёрнутое на устройствах и ВМ (owner_type/owner_id — см. models.DeployedSoftware)',
    'is-sources':'ИС ↔ источники размещения', 'open-ports':'Открытые порты', 'audit-log':'Аудит',
    'device-stacks':'Стеки устройств', 'device-stack-members':'Устройства в стеках', 'device-stack-vlans':'Общие VLAN стеков',
}
