from __future__ import annotations
from .models import (
    AuditLog, Building, Connection, ConnectionType, Container, Department, DeviceCategory, DeviceInterface,
    DeviceModel, DeviceSoftware, DeviceType, DiagramIcon, InterfaceIP, InterfaceSpeed, InterfaceType,
    ISContainer, ISDepartment, ISDevice, ISIP, ISProtocol, ISVM, InformationSystem, InformationSystemSource, InterfaceVLAN, OpenPort, ProtocolPortCatalog,
    Manufacturer, OperatingSystem, OperatingSystemCategory, EmbeddedOperatingSystem, DeviceTypeVLAN, PhysicalDeviceVLAN, SupportOrganization, SupportMethod, CryptoProtectionMeans, PlacementAsset, ISPlacementAsset, PhysicalDevice,
    Rack, Room, SoftwareAsset, StructuralUnit, VLAN, VLANDomain, VLANDomainDevice, VMIP, VMSoftware, VirtualMachine,
)

# Ресурсы, доступные через generic CRUD только для чтения. audit-log должен быть неизменяемым:
# audit() (см. services/crud.py) уже не даёт создать запись audit-log из кода приложения, а
# generic-эндпоинты POST/PUT/DELETE /api/v1/resources/{resource} (services/crud.py:
# create_resource/update_resource/delete_resource) обязаны проверять этот набор — иначе любой
# клиент может подделать или стереть журнал аудита через /api/v1/resources/audit-log.
READONLY_RESOURCES = frozenset({'audit-log'})

MODEL_MAP = {
    # Фикс: справочник 'organizations' удалён целиком (снят из MODEL_MAP/DISPLAY_NAMES здесь, см.
    # миграцию с DROP TABLE organizations) — на него нигде не было ни одной FK-ссылки (в отличие
    # от support-organizations), только автосоздаваемая при пустой БД запись-заглушка
    # "Организация"/"ООО «Организация»" (_seed_singleton_records в services/catalogs.py), которая
    # ничего не значила и ни на что не влияла.
    'support-organizations': SupportOrganization, 'support-methods': SupportMethod, 'crypto-protection-means': CryptoProtectionMeans, 'departments': Department, 'structural-units': StructuralUnit, 'buildings': Building, 'rooms': Room, 'racks': Rack,
    'device-categories': DeviceCategory, 'device-types': DeviceType, 'manufacturers': Manufacturer, 'device-models': DeviceModel, 'diagram-icons': DiagramIcon,
    'os-categories': OperatingSystemCategory, 'operating-systems': OperatingSystem, 'embedded-os': EmbeddedOperatingSystem, 'device-type-vlans': DeviceTypeVLAN, 'device-vlans': PhysicalDeviceVLAN, 'devices': PhysicalDevice,
    'information-systems': InformationSystem, 'is-departments': ISDepartment, 'is-ips': ISIP, 'is-protocols': ISProtocol, 'protocol-port-catalog': ProtocolPortCatalog,
    'placement-assets': PlacementAsset, 'is-placement-assets': ISPlacementAsset,
    'interfaces': DeviceInterface, 'interface-ips': InterfaceIP, 'interface-types': InterfaceType,
    'interface-speeds': InterfaceSpeed, 'vlans': VLAN, 'vlan-domains': VLANDomain, 'vlan-domain-devices': VLANDomainDevice, 'interface-vlans': InterfaceVLAN,
    'connection-types': ConnectionType, 'connections': Connection, 'vms': VirtualMachine, 'vm-ips': VMIP,
    'containers': Container, 'software-assets': SoftwareAsset, 'device-software': DeviceSoftware,
    'vm-software': VMSoftware, 'is-devices': ISDevice, 'is-vms': ISVM, 'is-containers': ISContainer, 'is-sources': InformationSystemSource,
    'open-ports': OpenPort, 'audit-log': AuditLog,
}

DISPLAY_NAMES = {
    'support-organizations':'Организации технической поддержки', 'support-methods':'Способы оказания технической поддержки', 'crypto-protection-means':'Средства криптографической защиты информации (СКЗИ)', 'departments':'Подразделения', 'structural-units':'Структурные единицы', 'buildings':'Здания', 'rooms':'Помещения', 'racks':'Стойки',
    'device-categories':'Категории устройств (диаграмма топологии сети)', 'device-types':'Типы устройств', 'manufacturers':'Производители', 'device-models':'Каталог оборудования (Производитель → Тип → Модель)', 'diagram-icons':'Пользовательские иконки диаграммы', 'diagrams':'Диаграммы топологии сети',
    'os-categories':'Категории ОС', 'operating-systems':'ОС и гипервизоры', 'embedded-os':'Встроенные ОС', 'device-type-vlans':'VLAN типов устройств', 'device-vlans':'VLAN физических устройств', 'devices':'Физические устройства',
    'information-systems':'Информационные системы', 'is-departments':'ИС ↔ подразделения', 'is-ips':'IP ИС (устарело, только чтение истории — актуальные IP считаются из источников/ВМ на лету)', 'is-protocols':'Протоколы ИС', 'protocol-port-catalog':'Справочник протоколов и портов',
    'placement-assets':'Оборудование, ПО, интерфейс на которых размещается ИС', 'is-placement-assets':'ИС ↔ оборудование/ПО/интерфейс размещения',
    'interfaces':'Интерфейсы', 'interface-ips':'IP интерфейсов', 'interface-types':'Типы интерфейсов', 'interface-speeds':'Скорости интерфейсов',
    'vlans':'VLAN', 'vlan-domains':'Домены VLAN', 'vlan-domain-devices':'Устройства в доменах VLAN', 'interface-vlans':'Интерфейсы ↔ VLAN', 'connection-types':'Типы подключений', 'connections':'Подключения',
    'vms':'Виртуальные машины', 'vm-ips':'IP VM', 'containers':'Контейнеры', 'software-assets':'Программные активы',
    'device-software':'ПО физических устройств', 'vm-software':'ПО VM', 'is-devices':'ИС ↔ устройства (устарело, только чтение истории — см. ИС ↔ источники размещения)', 'is-vms':'ИС ↔ VM (устарело, только чтение истории — см. ИС ↔ источники размещения)',
    'is-containers':'ИС ↔ контейнеры (устарело, только чтение истории — см. ИС ↔ источники размещения)', 'is-sources':'ИС ↔ источники размещения', 'open-ports':'Открытые порты', 'audit-log':'Аудит'
}
