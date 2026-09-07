from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import Building, Department, DeviceType, InterfaceSpeed, InterfaceType, ConnectionType, OperatingSystemCategory, OperatingSystem, EmbeddedOperatingSystem, Manufacturer, SupportOrganization, ProtocolPortCatalog

DEFAULT_NAMES = {
    DeviceType: ['Сервер','Сетевое оборудование','Средство защиты информации','Рабочий ПК системного администратора','Рабочий ПК сетевого администратора','Рабочий ПК администратора безопасности','Рабочая станция пользователя','Система хранения данных','Точка доступа Wi-Fi','IP-телефон','ИБП','Принтер/МФУ'],
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
    if model is DeviceType and name in VM_HOST_DEVICE_TYPE_NAMES:
        return {'allows_vm_hosting': True}
    return {}


def _seed_name_only_catalogs(session: Session) -> None:
    for model, names in DEFAULT_NAMES.items():
        existing = {x.name for x in session.scalars(select(model)).all()}
        for name in names:
            if name not in existing: session.add(model(name=name, **_default_catalog_flags(model, name)))


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
    _seed_operating_systems(session)
    session.flush()
    _seed_protocols(session)
    session.flush()
    _seed_manufacturers(session)
    _seed_singleton_records(session)
    session.commit()
