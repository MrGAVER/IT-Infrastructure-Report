from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import Building, Department, DeviceCategory, DeviceType, InterfaceSpeed, InterfaceType, ConnectionType, OperatingSystemCategory, OperatingSystem, EmbeddedOperatingSystem, Manufacturer, SupportOrganization, ProtocolPortCatalog

DEFAULT_NAMES = {
    InterfaceSpeed: ['10 Mbps','100 Mbps','1 Gbps','2.5 Gbps','5 Gbps','10 Gbps','25 Gbps','40 Gbps','50 Gbps','100 Gbps','200 Gbps','400 Gbps','Auto'],
    InterfaceType: ['Ethernet','SFP','SFP+','SFP28','QSFP','QSFP28','Management','Console','Fiber','Virtual','Loopback','Wi-Fi','Другое'],
    ConnectionType: ['Витая пара','Оптическое волокно','Медный патч-корд','Оптический патч-корд','Прямая связь','Агрегированный канал','Другое'],
    OperatingSystemCategory: ['Гипервизор','Серверная ОС','Клиентская ОС','Сетевая ОС','ОС средства защиты','Мобильная ОС','Другое'],
}
# Стандартные записи, для которых при ПЕРВОМ создании (см. _seed_name_only_catalogs) нужно
# проставить не только имя, но и явный булев признак бизнес-правила (код-ревью п.4). Не
# применяется к уже существующим записям — эти поля дальше редактируются администратором
# как обычные через generic CRUD, и повторный запуск seed_defaults() не должен их затирать.
HYPERVISOR_CATEGORY_NAMES = {'Гипервизор'}
VM_HOST_DEVICE_TYPE_NAMES = {'Сервер', 'Система хранения данных'}

# Иерархия категорий устройств для диаграммы топологии сети (ТЗ, раздел 4.1) — заводится один раз
# при первом запуске (_seed_device_categories), дальше администратор может добавлять подкатегории
# обычным CRUD. Порядок важен: родители перечислены раньше своих подкатегорий, чтобы parent_id
# можно было разрешить по имени за один проход. diagram_shape/diagram_color пустые у подкатегорий,
# которым не нужен собственный визуальный стиль — они наследуются от ближайшего предка (см.
# services/diagram_icons.resolve_style). 'Другое оборудование' — не часть ТЗ: технический fallback
# для типов устройств, добавленных администратором вручную и не покрытых стандартной картой
# DEVICE_TYPE_CATEGORY (см. _seed_device_types) — без него бэкенд не знал бы, какую категорию
# проставить произвольному кастомному типу устройства при обязательном (NOT NULL) category_id.
DEVICE_CATEGORY_HIERARCHY = [
    # (name, parent_name, description, diagram_shape, diagram_color)
    ('Серверы и СХД', None, 'Серверы и системы хранения данных', 'server', '#4f7cff'),
    ('Сетевая инфраструктура', None, 'Активное сетевое оборудование', 'generic', '#2fa86a'),
    ('Коммутаторы', 'Сетевая инфраструктура', 'Коммутаторы уровня доступа/ядра', 'switch', None),
    # Раньше 'Коммутатор L2' и 'Коммутатор L3' указывали на ОДНУ и ту же категорию
    # 'Коммутаторы' — на диаграмме получали одинаковый значок, различить уровень коммутации на
    # глаз было нельзя. 'Маршрутизатор' же указывал прямо на родителя 'Сетевая инфраструктура'
    # (shape='generic') вместе с точками Wi-Fi/GSM-модемами/радиомостами — без своего значка
    # вообще. Три новые подкатегории ниже дают каждому свой diagram_shape (см.
    # services/diagram_icons.py:resolve_category_style — поднимается по иерархии до ближайшего
    # предка с непустым shape), color не задаём — наследуется от 'Сетевая инфраструктура'
    # (зелёный), различие только в форме значка, как и просили. Родитель 'Коммутаторы' остаётся
    # с shape='switch' как запасной вариант для типа устройства, заведённого администратором
    # напрямую в эту категорию, без более точного L2/L3.
    ('Коммутаторы L2', 'Коммутаторы', 'Коммутаторы уровня доступа (L2)', 'switch_l2', None),
    ('Коммутаторы L3', 'Коммутаторы', 'Коммутаторы с маршрутизацией (L3)', 'switch_l3', None),
    ('Маршрутизаторы', 'Сетевая инфраструктура', 'Маршрутизаторы', 'router', None),
    ('Средства защиты информации', None, 'Межсетевые экраны и программно-аппаратные комплексы защиты', 'firewall', '#d9534f'),
    ('Рабочие места', None, 'Рабочие станции и администраторские ПК', 'workstation', '#8a8f98'),
    ('Администраторские рабочие места', 'Рабочие места', 'Рабочие ПК системного/сетевого администратора и администратора безопасности', None, None),
    ('Периферия и вспомогательное оборудование', None, 'IP-телефоны, ИБП, принтеры/МФУ', 'peripheral', '#b08b3a'),
    ('Другое оборудование', None, 'Технический fallback для типов устройств без сопоставленной категории', 'generic', None),
]
FALLBACK_DEVICE_CATEGORY_NAME = 'Другое оборудование'

# Итоговый состав типов устройств (ТЗ, раздел 4.2): 10 существовавших ранее + 7 новых, взамен
# удалённых обобщённых 'Сетевое оборудование'/'Средство защиты информации' (см. миграцию
# backend/alembic/versions с добавлением device_categories.category_id). Сопоставление с
# категорией из DEVICE_CATEGORY_HIERARCHY — по таблице раздела 4.1 ТЗ.
DEVICE_TYPE_CATEGORY = {
    'Сервер': 'Серверы и СХД',
    'Система хранения данных': 'Серверы и СХД',
    'Точка доступа Wi-Fi': 'Сетевая инфраструктура',
    'GSM-модем': 'Сетевая инфраструктура',
    'Радиомост': 'Сетевая инфраструктура',
    'Маршрутизатор': 'Маршрутизаторы',
    'Коммутатор L2': 'Коммутаторы L2',
    'Коммутатор L3': 'Коммутаторы L3',
    'Межсетевой экран': 'Средства защиты информации',
    'Программно-аппаратный комплекс': 'Средства защиты информации',
    'Рабочая станция пользователя': 'Рабочие места',
    'Рабочий ПК системного администратора': 'Администраторские рабочие места',
    'Рабочий ПК сетевого администратора': 'Администраторские рабочие места',
    'Рабочий ПК администратора безопасности': 'Администраторские рабочие места',
    'IP-телефон': 'Периферия и вспомогательное оборудование',
    'ИБП': 'Периферия и вспомогательное оборудование',
    'Принтер/МФУ': 'Периферия и вспомогательное оборудование',
}
DEVICE_TYPE_NAMES = list(DEVICE_TYPE_CATEGORY.keys())
PROTOCOL_DEFAULTS = [(22,'SSH','Secure Shell'),(53,'DNS','Domain Name System'),(80,'HTTP','Web HTTP'),(123,'NTP','Network Time Protocol'),(161,'SNMP','Simple Network Management Protocol'),(389,'LDAP','Lightweight Directory Access Protocol'),(443,'HTTPS','Web HTTPS'),(445,'SMB','Server Message Block'),(636,'LDAPS','LDAP over TLS'),(1433,'MS SQL','Microsoft SQL Server'),(1521,'Oracle','Oracle Database'),(2049,'NFS','Network File System'),(3306,'MySQL','MySQL'),(3389,'RDP','Remote Desktop Protocol'),(5432,'PostgreSQL','PostgreSQL'),(5900,'VNC','Virtual Network Computing'),(8080,'HTTP-alt','Alternative HTTP'),(8443,'HTTPS-alt','Alternative HTTPS')]
EMBEDDED_OS_DEFAULTS = [('Cisco IOS','15','Cisco'),('Cisco IOS XE','17','Cisco'),('Junos OS','21','Juniper'),('RouterOS','7','MikroTik'),('FortiOS','7','Fortinet'),('PAN-OS','11','Palo Alto Networks'),('ArubaOS-CX','10','HPE Aruba'),('Comware','7','HPE'),('Huawei VRP','8','Huawei'),('Dell OS10','10','Dell'),('SONiC','','Community')
]
OS_DEFAULTS = [
 ('Серверная ОС','Windows Server','Microsoft','2016'),('Серверная ОС','Windows Server','Microsoft','2019'),('Серверная ОС','Windows Server','Microsoft','2022'),('Серверная ОС','Windows Server','Microsoft','2025'),
 ('Серверная ОС','Ubuntu Server','Canonical','20.04 LTS'),('Серверная ОС','Ubuntu Server','Canonical','22.04 LTS'),('Серверная ОС','Ubuntu Server','Canonical','24.04 LTS'),('Серверная ОС','Debian','Debian','11'),('Серверная ОС','Debian','Debian','12'),('Серверная ОС','Red Hat Enterprise Linux','Red Hat','8'),('Серверная ОС','Red Hat Enterprise Linux','Red Hat','9'),
 ('Клиентская ОС','Windows 10','Microsoft','22H2'),('Клиентская ОС','Windows 11','Microsoft','23H2'),('Клиентская ОС','Windows 11','Microsoft','24H2'),('Клиентская ОС','Windows 11','Microsoft','25H2'),
 ('Сетевая ОС','Cisco IOS XE','Cisco','17'),('Сетевая ОС','Cisco IOS','Cisco','15'),('Сетевая ОС','RouterOS','MikroTik','7'),('ОС средства защиты','FortiOS','Fortinet','7'),
 ('Гипервизор','VMware ESXi','VMware','7.0'),('Гипервизор','VMware ESXi','VMware','8.0'),('Гипервизор','Microsoft Hyper-V','Microsoft','2022'),('Гипервизор','Microsoft Hyper-V','Microsoft','2025'),('Гипервизор','Proxmox VE','Proxmox','8'),('Гипервизор','Proxmox VE','Proxmox','9')]

def _default_catalog_flags(model, name: str) -> dict[str, bool]:
    """Дополнительные булевы поля для стандартных записей DEFAULT_NAMES, выставляемые только
    при создании — существующие записи (в т.ч. переименованные администратором) не трогаются."""
    if model is OperatingSystemCategory and name in HYPERVISOR_CATEGORY_NAMES:
        return {'is_hypervisor': True}
    return {}


def _seed_name_only_catalogs(session: Session) -> None:
    for model, names in DEFAULT_NAMES.items():
        existing = {x.name for x in session.scalars(select(model)).all()}
        for name in names:
            if name not in existing: session.add(model(name=name, **_default_catalog_flags(model, name)))


def _seed_device_categories(session: Session) -> None:
    """Иерархия категорий устройств для диаграммы топологии сети (см. DEVICE_CATEGORY_HIERARCHY).
    Не влезает в generic _seed_name_only_catalogs() выше — нужен parent_id по имени родителя и
    два дополнительных поля стиля, а не один плоский список имён. Флашится построчно (каталог
    заведомо маленький, ~8 записей), чтобы id родителя был доступен сразу для дочерней записи в
    том же проходе, без отдельного двухфазного алгоритма."""
    by_name = {x.name: x for x in session.scalars(select(DeviceCategory)).all()}
    for name, parent_name, description, shape, color in DEVICE_CATEGORY_HIERARCHY:
        if name in by_name:
            continue
        parent = by_name.get(parent_name) if parent_name else None
        obj = DeviceCategory(name=name, parent_id=parent.id if parent else None, description=description, diagram_shape=shape, diagram_color=color)
        session.add(obj); session.flush()
        by_name[name] = obj


def _seed_device_types(session: Session) -> None:
    """Типы устройств (см. DEVICE_TYPE_NAMES/DEVICE_TYPE_CATEGORY) — вынесено из
    _seed_name_only_catalogs(), т.к. DeviceType.category_id обязателен (NOT NULL) и требует
    предварительно засеянных DeviceCategory (см. _seed_device_categories, вызывается раньше в
    seed_defaults()). Категория произвольного типа устройства, добавленного администратором вручную
    и потому отсутствующего в DEVICE_TYPE_CATEGORY, при появлении здесь (переименование по внешней
    причине не ожидается) не проставляется — это делает форма/CRUD на обычных правах, а не сид."""
    categories = {x.name: x for x in session.scalars(select(DeviceCategory)).all()}
    fallback = categories.get(FALLBACK_DEVICE_CATEGORY_NAME)
    existing = {x.name for x in session.scalars(select(DeviceType)).all()}
    for name in DEVICE_TYPE_NAMES:
        if name in existing:
            continue
        category = categories.get(DEVICE_TYPE_CATEGORY.get(name)) or fallback
        flags = {'allows_vm_hosting': True} if name in VM_HOST_DEVICE_TYPE_NAMES else {}
        session.add(DeviceType(name=name, category_id=category.id, **flags))


def _seed_operating_systems(session: Session) -> None:
    categories = {x.name: x for x in session.scalars(select(OperatingSystemCategory)).all()}
    existing_os = {(x.category_id, x.name, x.version) for x in session.scalars(select(OperatingSystem)).all()}
    for category, name, vendor, version in OS_DEFAULTS:
        cat = categories[category]; key = (cat.id, name, version)
        if key not in existing_os: session.add(OperatingSystem(category_id=cat.id, name=name, vendor=vendor, version=version))
    existing_embedded = {(x.name, x.version) for x in session.scalars(select(EmbeddedOperatingSystem)).all()}
    for name, version, vendor in EMBEDDED_OS_DEFAULTS:
        if (name, version) not in existing_embedded: session.add(EmbeddedOperatingSystem(name=name, version=version or None, vendor=vendor))


def _seed_protocols(session: Session) -> None:
    existing_protocols = {(x.port, x.protocol_type) for x in session.scalars(select(ProtocolPortCatalog)).all()}
    for port, protocol_type, description in PROTOCOL_DEFAULTS:
        if (port, protocol_type) not in existing_protocols:
            session.add(ProtocolPortCatalog(port=port, protocol_type=protocol_type, description=description))


def _seed_manufacturers(session: Session) -> None:
    manufacturer_names = ['Cisco','Dell','HPE','Huawei','VMware','Microsoft','Proxmox','MikroTik','Fortinet','Lenovo','Supermicro']
    existing = {x.name for x in session.scalars(select(Manufacturer)).all()}
    for name in manufacturer_names:
        if name not in existing: session.add(Manufacturer(name=name))


def _seed_singleton_records(session: Session) -> None:
    """Ровно одна запись каждого вида по умолчанию — только если справочник пуст."""
    if not session.scalar(select(Building).limit(1)): session.add(Building(name='Главный офис', address='Адрес организации'))
    if not session.scalar(select(SupportOrganization).limit(1)): session.add(SupportOrganization(name='Организация технической поддержки', short_name='Техподдержка'))
    if not session.scalar(select(Department).limit(1)): session.add(Department(name='ИТ'))


def seed_defaults(session: Session) -> None:
    """Оркестратор: наполняет справочники значениями по умолчанию, идемпотентно (не дублирует
    уже существующие записи). Вынесено в отдельные функции по виду справочника — была одной
    функцией сложности 17, логика по каждому блоку не изменена."""
    _seed_name_only_catalogs(session)
    session.flush()
    _seed_device_categories(session)
    session.flush()
    _seed_device_types(session)
    session.flush()
    _seed_operating_systems(session)
    session.flush()
    _seed_protocols(session)
    session.flush()
    _seed_manufacturers(session)
    _seed_singleton_records(session)
    session.commit()
