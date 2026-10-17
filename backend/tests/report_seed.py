"""Детерминированный набор данных для проверки загрузки данных отчёта и листа «Организация подключений»
(app/reporting.py). Id записей — читаемые строки, время создания подключений задано явно, поэтому
порядок строк не зависит от скорости теста. Используется tests/test_report_data_behaviour.py и
tests/test_report_connection_rows_behaviour.py (общий набор нужен, чтобы оба проверяли одну и ту же схему).

Что есть в наборе (по замыслу — по одному случаю на каждую ветку загрузчика и сборщика строк):
  • структурные единицы: «Управление» → «Отдел 1» (родитель/потомок) и «Другое»; здания, помещение;
  • коммутатор SW-1: порт управления с подинтерфейсом управления, порт «Все VLAN» (его собственная связь
    с VLAN игнорируется), порт с двумя подинтерфейсами, неподключённые порты с одинаковой «подписью IP»;
  • устройства без системного имени, без здания и с хостингом ВМ; подключение, помеченное неактивным;
  • IP с владельцами всех видов (включая «physical_device», которого нет ни в одной выборке отчёта);
  • ВМ (с хостом и без), контейнеры (на ВМ, на устройстве, на ВМ без хоста), ИС с источниками всех видов;
  • ПО на ВМ, на устройстве и на контейнере (последнее попадает в «устройства» — особенность загрузчика).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.constants import OwnerType
from app.models import (
    Building, Connection, ConnectionType, Container, CryptoProtectionMeans, DeployedSoftware, Department, DeviceCategory,
    DeviceInterface, DeviceModel, DeviceSubinterface, DeviceType, DeviceTypeVLAN, EmbeddedOperatingSystem, InformationSystem,
    InformationSystemSource, InterfaceType, InterfaceVLAN, IPAddress, ISDepartment, ISPlacementAsset, ISProtocol, Manufacturer,
    OpenPort, OperatingSystem, OperatingSystemCategory, PhysicalDevice, PhysicalDeviceVLAN, PlacementAsset, ProtocolPortCatalog,
    Room, SoftwareAsset, StructuralUnit, SupportMethod, SupportOrganization, VirtualMachine, VLAN,
)

T0 = datetime(2026, 1, 1, 12, 0, 0)


def seed_registry(session: Session) -> None:
    add = session.add_all
    add([DeviceCategory(id="cat1", name="Сетевое оборудование"), OperatingSystemCategory(id="osc1", name="Сетевые ОС")])
    add([StructuralUnit(id="u-root", name="Управление"), StructuralUnit(id="u-other", name="Другое")])
    session.flush()
    add([StructuralUnit(id="u-child", name="Отдел 1", parent_id="u-root")])
    session.flush()
    add([Building(id="b1", name="Корпус 1", address="ул. Первая, 1", structural_unit_id="u-child"), Building(id="b2", name="Корпус 2", address="ул. Вторая, 2", structural_unit_id="u-other"), Building(id="b3", name="Склад")])
    session.flush()
    add([Room(id="rm1", building_id="b1", name="101")])
    add([DeviceType(id="dt-sw", name="Коммутатор", category_id="cat1"), DeviceType(id="dt-rt", name="Маршрутизатор", category_id="cat1"), DeviceType(id="dt-srv", name="Сервер", category_id="cat1")])
    add([Manufacturer(id="m1", name="Cisco")])
    session.flush()
    add([DeviceModel(id="mod1", manufacturer_id="m1", device_type_id="dt-sw", model="C3750X")])
    add([OperatingSystem(id="os1", category_id="osc1", name="Debian", version="12"), EmbeddedOperatingSystem(id="eos1", name="IOS XE")])
    add([InterfaceType(id="it1", name="GigabitEthernet")])
    add([VLAN(id="v10", vlan_id=10, name="Данные"), VLAN(id="v20", vlan_id=20, name="Управление"), VLAN(id="v30", vlan_id=30, name="Гости"), VLAN(id="v40", vlan_id=40, name="Лишний")])
    add([SupportOrganization(id="so1", name="Интегратор"), SupportMethod(id="sm1", name="Удалённо"), CryptoProtectionMeans(id="cp1", name="КриптоПро"), Department(id="dep1", name="Бухгалтерия"), PlacementAsset(id="pa1", name="ЦОД")])
    add([ProtocolPortCatalog(id="cat-22", port=22, protocol_type="SSH"), ProtocolPortCatalog(id="cat-443", port=443, protocol_type="HTTPS"), ProtocolPortCatalog(id="cat-80", port=80, protocol_type="HTTP")])
    add([ConnectionType(id="ct1", name="Витая пара")])
    session.flush()
    add([DeviceTypeVLAN(id="dtv1", device_type_id="dt-sw", vlan_id="v30")])
    add([
        PhysicalDevice(id="srv0", device_type_id="dt-srv", serial_number="SN-AAA", system_name="AAA-first"),
        PhysicalDevice(id="sw1", device_type_id="dt-sw", serial_number="SN-SW1", system_name="SW-1", building_id="b1", room_id="rm1", manufacturer_id="m1", model_id="mod1", embedded_os_id="eos1", siem_enabled=True),
        PhysicalDevice(id="sw2", device_type_id="dt-sw", serial_number="SN-SW2", system_name="SW-2", building_id="b2"),
        PhysicalDevice(id="rt1", device_type_id="dt-rt", serial_number="SN-RT1", building_id="b1"),
        PhysicalDevice(id="srv1", device_type_id="dt-srv", serial_number="SN-SRV1", system_name="SRV-1", building_id="b3", operating_system_id="os1"),
    ])
    session.flush()
    add([PhysicalDeviceVLAN(id="pdv1", physical_device_id="sw1", vlan_id="v10"), PhysicalDeviceVLAN(id="pdv2", physical_device_id="sw1", vlan_id="v20", ip_address="192.168.20.1", prefix_length=24, is_management=True)])
    add([
        DeviceInterface(id="p1", physical_device_id="sw1", name="Gi1/0/1", is_management=True, is_data_transfer=True, vlan_mode="trunk", interface_type_id="it1"),
        DeviceInterface(id="p2", physical_device_id="sw1", name="Gi1/0/2", is_data_transfer=True, vlan_mode="trunk", all_vlans=True, interface_type_id="it1"),
        DeviceInterface(id="p3", physical_device_id="sw1", name="Gi1/0/3", is_data_transfer=True, interface_type_id="it1"),
        DeviceInterface(id="p4", physical_device_id="sw1", name="Gi1/0/4", is_data_transfer=True),
        DeviceInterface(id="p5", physical_device_id="sw1", name="Gi1/0/5", is_data_transfer=True),
        DeviceInterface(id="p6", physical_device_id="sw1", name="Gi1/0/6", is_data_transfer=True),
        DeviceInterface(id="q1", physical_device_id="sw2", name="Gi0/1", is_data_transfer=True, vlan_mode="access"),
        DeviceInterface(id="q2", physical_device_id="sw2", name="Gi0/2", is_data_transfer=True),
        DeviceInterface(id="q3", physical_device_id="sw2", name="Gi0/3", is_data_transfer=True),
        DeviceInterface(id="r1", physical_device_id="rt1", name="Gi0/0", is_data_transfer=True, vlan_mode="trunk"),
        DeviceInterface(id="n1", physical_device_id="srv1", name="eth0", is_management=True),
    ])
    session.flush()
    add([
        DeviceSubinterface(id="s-a", parent_interface_id="p5", name="Gi1/0/5.20", vlan_id="v20", is_data_transfer=True),
        DeviceSubinterface(id="s-b", parent_interface_id="p5", name="Gi1/0/5.10", vlan_id="v10", is_data_transfer=True),
        DeviceSubinterface(id="s-c", parent_interface_id="p1", name="Gi1/0/1.99", vlan_id="v20", is_management=True),
    ])
    add([
        InterfaceVLAN(id="iv1", interface_id="p1", vlan_id="v10", mode="trunk"), InterfaceVLAN(id="iv2", interface_id="p1", vlan_id="v20", mode="trunk"),
        InterfaceVLAN(id="iv3", interface_id="p2", vlan_id="v40", mode="trunk"),  # у порта «Все VLAN» связи игнорируются (VLAN 40 нет у устройства)
        InterfaceVLAN(id="iv4", interface_id="r1", vlan_id="v10", mode="trunk"), InterfaceVLAN(id="iv5", interface_id="q1", vlan_id="v20", mode="access"),
    ])
    add([
        Connection(id="c1", source_interface_id="p1", destination_interface_id="q1", connection_type_id="ct1", created_at=T0),
        Connection(id="c2", source_interface_id="p2", destination_interface_id="r1", connection_type_id="ct1", created_at=T0 + timedelta(minutes=1)),
        Connection(id="c3", source_interface_id="p3", destination_interface_id="n1", connection_type_id="ct1", is_active=False, created_at=T0 + timedelta(minutes=2)),
    ])
    add([
        IPAddress(id="ip1", owner_type=OwnerType.DEVICE_INTERFACE, owner_id="p1", ip_address="192.168.1.2", prefix_length=24, is_management=True),
        IPAddress(id="ip2", owner_type=OwnerType.DEVICE_INTERFACE, owner_id="p1", ip_address="192.168.1.1", prefix_length=24),
        IPAddress(id="ip3", owner_type=OwnerType.DEVICE_INTERFACE, owner_id="q2", ip_address="10.0.0.2", prefix_length=24),
        IPAddress(id="ip4", owner_type=OwnerType.DEVICE_INTERFACE, owner_id="q3", ip_address="10.0.0.2", prefix_length=24),
        IPAddress(id="ip5", owner_type=OwnerType.DEVICE_SUBINTERFACE, owner_id="s-a", ip_address="172.16.0.1", prefix_length=30),
        IPAddress(id="ip6", owner_type=OwnerType.DEVICE_SUBINTERFACE, owner_id="s-c", ip_address="172.16.99.1", prefix_length=24, is_management=True),
        IPAddress(id="ip7", owner_type=OwnerType.VIRTUAL_MACHINE, owner_id="vm1", ip_address="10.1.1.20", prefix_length=24, is_management=True),
        IPAddress(id="ip8", owner_type=OwnerType.VIRTUAL_MACHINE, owner_id="vm1", ip_address="10.1.1.10", prefix_length=24),
        IPAddress(id="ip9", owner_type=OwnerType.INFORMATION_SYSTEM_SOURCE, owner_id="src-vm", ip_address="10.9.9.9"),
        IPAddress(id="ip10", owner_type=OwnerType.PHYSICAL_DEVICE, owner_id="sw1", ip_address="1.1.1.1"),  # в выборки отчёта не входит
    ])
    add([
        OpenPort(id="op1", owner_type="device_interface", owner_id="p1", protocol_catalog_id="cat-22", transport_protocol="TCP"),
        OpenPort(id="op2", owner_type="device_subinterface", owner_id="s-a", protocol_catalog_id="cat-443", transport_protocol="TCP"),
        OpenPort(id="op3", owner_type="virtual_machine", owner_id="vm1", protocol_catalog_id="cat-80", transport_protocol="TCP"),
        OpenPort(id="op4", owner_type="physical_device", owner_id="sw1", protocol_catalog_id="cat-80", transport_protocol="TCP"),  # устаревшая запись: в строки портов не попадает
    ])
    add([
        VirtualMachine(id="vm1", name="app-vm", physical_device_id="srv1", operating_system_id="os1"),
        VirtualMachine(id="vm2", name="orphan-vm"),
        VirtualMachine(id="vm3", name="edge-vm", physical_device_id="rt1"),
    ])
    session.flush()
    add([
        Container(id="ct-a", name="web", virtual_machine_id="vm1"), Container(id="ct-b", name="db", physical_device_id="srv1"),
        Container(id="ct-c", name="lost", virtual_machine_id="vm2"), Container(id="ct-d", name="edge", virtual_machine_id="vm3"),
        Container(id="ct-e", name="router-box", physical_device_id="rt1"),
    ])
    add([
        InformationSystem(id="is1", name="ИС Альфа", support_organization_id="so1", support_method_id="sm1"), InformationSystem(id="is2", name="ИС Бета"),
        InformationSystem(id="is3", name="ИС Гамма"), InformationSystem(id="is4", name="ИС Дельта"),
        InformationSystem(id="is5", name="ИС Эпсилон"), InformationSystem(id="is6", name="ИС Ява"), InformationSystem(id="is7", name="ИС Яблоко"),
    ])
    session.flush()
    add([
        InformationSystemSource(id="src-dev", information_system_id="is1", source_type="device", owner_id="sw1"),
        InformationSystemSource(id="src-vm", information_system_id="is1", source_type="vm", owner_id="vm1"),
        InformationSystemSource(id="src-ct", information_system_id="is1", source_type="container", owner_id="ct-b"),
        InformationSystemSource(id="src-ct2", information_system_id="is2", source_type="container", owner_id="ct-a"),  # контейнер на ВМ → хост ВМ
        InformationSystemSource(id="src-lost", information_system_id="is3", source_type="vm", owner_id="vm2"),  # ВМ без хоста
        InformationSystemSource(id="src-dup", information_system_id="is1", source_type="device", owner_id="sw1"),  # повтор — в связях один раз
        InformationSystemSource(id="src-ct3", information_system_id="is5", source_type="container", owner_id="ct-d"),  # контейнер на ВМ, хост ВМ — в выбранной единице
        InformationSystemSource(id="src-ct4", information_system_id="is6", source_type="container", owner_id="ct-e"),  # контейнер прямо на устройстве
        InformationSystemSource(id="src-vm3", information_system_id="is7", source_type="vm", owner_id="vm3"),  # ВМ на устройстве из выбранной единицы
        InformationSystemSource(id="src-gone", information_system_id="is1", source_type="device", owner_id="нет-такого"),
    ])
    add([ISDepartment(id="isd1", information_system_id="is1", department_id="dep1"), ISProtocol(id="isp1", information_system_id="is1", protocol_catalog_id="cat-443"), ISPlacementAsset(id="isa1", information_system_id="is1", placement_asset_id="pa1")])
    add([SoftwareAsset(id="sa1", name="1С"), SoftwareAsset(id="sa2", name="Postgres")])
    session.flush()
    add([
        DeployedSoftware(id="ds1", owner_type="virtual_machine", owner_id="vm1", software_asset_id="sa1"),
        DeployedSoftware(id="ds2", owner_type="physical_device", owner_id="srv1", software_asset_id="sa2"),
        DeployedSoftware(id="ds3", owner_type="container", owner_id="ct-a", software_asset_id="sa2"),
    ])
    session.commit()
