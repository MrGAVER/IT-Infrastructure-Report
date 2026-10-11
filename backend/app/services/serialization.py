from __future__ import annotations
from datetime import date
from types import SimpleNamespace
from typing import Any, Sequence
from sqlalchemy import select
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session
from ..models import (Connection, ConnectionType, DeviceInterface, DeviceSubinterface, IPAddress, OpenPort, PhysicalDevice, SupportOrganization, SupportMethod, PlacementAsset, ISPlacementAsset, VirtualMachine, InformationSystem, ISDepartment, ISProtocol, InformationSystemSource, Department, Container, ProtocolPortCatalog, EmbeddedOperatingSystem, PhysicalDeviceVLAN, VLAN, DeviceStack, DeviceStackMember, InterfaceGroup, InterfaceGroupOpenPort, InterfaceGroupVLAN)
from .port_config import PortConfigStatus, evaluate_port_config, config_differences
from .port_config_db import load_port_configs
from .port_vlans import carries_all_vlans, effective_group_vlan_ids
from ..constants import OwnerType, SourceType
from .computed import device_management_ports_and_ips

def serialize(obj: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for col in inspect(obj).mapper.column_attrs:
        value = getattr(obj, col.key)
        # datetime.datetime — подкласс datetime.date, поэтому одна проверка на date покрывает и
        # DateTime-колонки (created_at/updated_at), и обычные Date-колонки (например,
        # PhysicalDevice.oac_certificate_registry_date) — обе форматируются одинаково через
        # .isoformat(), без отдельной ветки под каждый тип.
        result[col.key] = value.isoformat() if isinstance(value, date) else value
    return result

def enrich_open_port(obj: OpenPort, session: Session) -> dict[str, Any]:
    """port/protocol больше не колонки OpenPort (см. models.py, миграция b7f2c1e5a904) —
    вычисляются на КАЖДОЕ чтение из protocol_port_catalogs по protocol_catalog_id, поэтому правка
    записи справочника отражается на уже созданных портах сразу, без их отдельного пересохранения.
    Единичный вариант enrich_open_ports() ниже — для одного объекта (create_resource/
    update_resource), где батч-загрузка каталога не даёт выигрыша."""
    data = serialize(obj)
    cat = session.get(ProtocolPortCatalog, obj.protocol_catalog_id)
    data['port'] = cat.port if cat else None
    data['protocol'] = cat.protocol_type if cat else None
    return data

def enrich_open_ports(items: Sequence[OpenPort], session: Session) -> list[dict[str, Any]]:
    """Батч-вариант enrich_open_port() — для списков (list_resource('open-ports'),
    sync_interfaces): одним запросом подгружает все нужные записи справочника, а не по одной на
    порт."""
    if not items: return []
    catalog_ids = {x.protocol_catalog_id for x in items if x.protocol_catalog_id}
    catalog_map = {x.id: x for x in session.scalars(select(ProtocolPortCatalog).where(ProtocolPortCatalog.id.in_(catalog_ids))).all()} if catalog_ids else {}
    result = []
    for obj in items:
        data = serialize(obj)
        cat = catalog_map.get(obj.protocol_catalog_id)
        data['port'] = cat.port if cat else None
        data['protocol'] = cat.protocol_type if cat else None
        result.append(data)
    return result

def enrich_devices(devices: Sequence[PhysicalDevice], session: Session) -> list[dict[str, Any]]:
    if not devices: return []
    device_ids = [d.id for d in devices]
    interfaces = session.scalars(select(DeviceInterface).where(DeviceInterface.physical_device_id.in_(device_ids)).order_by(DeviceInterface.name)).all()
    by_device: dict[str, list[DeviceInterface]] = {}
    for iface in interfaces: by_device.setdefault(iface.physical_device_id, []).append(iface)
    interface_ids = [i.id for i in interfaces]
    ips = session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id.in_(interface_ids)).order_by(IPAddress.ip_address)).all() if interface_ids else []
    ips_by_interface: dict[str, list[IPAddress]] = {}
    for ip in ips: ips_by_interface.setdefault(ip.owner_id, []).append(ip)
    # Управление может висеть на подинтерфейсе порта (например, Gi0/0.99 на VLAN управления): подинтерфейс с ролью
    # «Управление» даёт порт и IP управления устройства так же, как в отчётах (reporting.py). Берём только такие
    # подинтерфейсы — остальные на дашборде устройств не нужны. Порт-родитель -> устройство, чтобы разложить по устройствам.
    device_by_interface = {i.id: i.physical_device_id for i in interfaces}
    mgmt_subinterfaces = session.scalars(
        select(DeviceSubinterface).where(DeviceSubinterface.parent_interface_id.in_(interface_ids), DeviceSubinterface.is_management.is_(True)).order_by(DeviceSubinterface.name, DeviceSubinterface.id)
    ).all() if interface_ids else []
    mgmt_subs_by_device: dict[str, list[DeviceSubinterface]] = {}
    for sub in mgmt_subinterfaces: mgmt_subs_by_device.setdefault(device_by_interface[sub.parent_interface_id], []).append(sub)
    sub_ids = [x.id for x in mgmt_subinterfaces]
    sub_ips = session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_SUBINTERFACE, IPAddress.owner_id.in_(sub_ids)).order_by(IPAddress.ip_address)).all() if sub_ids else []
    ips_by_subinterface: dict[str, list[IPAddress]] = {}
    for ip in sub_ips: ips_by_subinterface.setdefault(ip.owner_id, []).append(ip)
    port_name_by_id = {i.id: i.name for i in interfaces}
    embedded_ids = {d.embedded_os_id for d in devices if getattr(d, 'embedded_os_id', None)}
    embedded_map = {x.id: x for x in session.scalars(select(EmbeddedOperatingSystem).where(EmbeddedOperatingSystem.id.in_(embedded_ids))).all()} if embedded_ids else {}
    vlan_links = session.scalars(select(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.physical_device_id.in_(device_ids))).all()
    vlan_ids = {x.vlan_id for x in vlan_links}
    vlan_map = {x.id: x for x in session.scalars(select(VLAN).where(VLAN.id.in_(vlan_ids))).all()} if vlan_ids else {}
    vlans_by_device: dict[str, list[PhysicalDeviceVLAN]] = {}
    for link in vlan_links: vlans_by_device.setdefault(link.physical_device_id, []).append(link)
    # Пункт 2 правки "инвентаризация физических устройств": стек, в который входит устройство —
    # тот же батч-принцип, что и у остальных enrich_devices-полей выше (одним запросом на все
    # device_ids, а не по одному на устройство). Устройство состоит максимум в одном стеке
    # (UniqueConstraint на DeviceStackMember.physical_device_id, см. models.py), поэтому
    # member_by_device — словарь "один к одному", без списков.
    stack_members = session.scalars(select(DeviceStackMember).where(DeviceStackMember.physical_device_id.in_(device_ids))).all()
    member_by_device = {m.physical_device_id: m for m in stack_members}
    stack_ids = {m.stack_id for m in stack_members}
    stack_map = {s.id: s for s in session.scalars(select(DeviceStack).where(DeviceStack.id.in_(stack_ids))).all()} if stack_ids else {}
    result=[]
    for device in devices:
        data=serialize(device); management=[i for i in by_device.get(device.id, []) if i.is_management]
        mgmt_vlan_links=[x for x in vlans_by_device.get(device.id, []) if x.is_management]
        mgmt_names, mgmt_ips = device_management_ports_and_ips(
            management, ips_by_interface, mgmt_vlan_links, vlan_map,
            management_subinterfaces=mgmt_subs_by_device.get(device.id, []), ips_by_subinterface=ips_by_subinterface, port_name_by_id=port_name_by_id)
        data['management_interface']='; '.join(mgmt_names)
        data['management_ips']='; '.join(mgmt_ips)
        data['interface_count']=len(by_device.get(device.id, []))
        data['embedded_os_name']=embedded_map.get(device.embedded_os_id).name if device.embedded_os_id and embedded_map.get(device.embedded_os_id) else ''
        data['embedded_os_version']=embedded_map.get(device.embedded_os_id).version if device.embedded_os_id and embedded_map.get(device.embedded_os_id) else ''
        data['vlan_summary']='; '.join(dict.fromkeys(f"{vlan_map[x.vlan_id].vlan_id} {vlan_map[x.vlan_id].name}" for x in vlans_by_device.get(device.id, []) if x.vlan_id in vlan_map))
        member = member_by_device.get(device.id)
        stack = stack_map.get(member.stack_id) if member else None
        data['stack_id'] = member.stack_id if member else None
        data['stack_name'] = stack.name if stack else None
        data['stack_position'] = member.position if member else None
        result.append(data)
    return result


def enrich_interfaces(items: Sequence[DeviceInterface], session: Session) -> list[dict[str, Any]]:
    if not items:
        return []
    interface_ids = [i.id for i in items]
    ips = session.scalars(
        select(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id.in_(interface_ids)).order_by(IPAddress.ip_address)
    ).all()
    by_interface: dict[str, list[IPAddress]] = {}
    for ip in ips:
        by_interface.setdefault(ip.owner_id, []).append(ip)
    result = []
    for iface in items:
        data = serialize(iface)
        data['ip_addresses'] = '; '.join(
            f"{ip.ip_address}/{ip.prefix_length}" if ip.prefix_length is not None else ip.ip_address
            for ip in by_interface.get(iface.id, [])
        )
        data['management_ips'] = '; '.join(
            f"{ip.ip_address}/{ip.prefix_length}" if ip.prefix_length is not None else ip.ip_address
            for ip in by_interface.get(iface.id, []) if iface.is_management
        )
        result.append(data)
    return result

def enrich_interface_groups(groups: Sequence[InterfaceGroup], session: Session) -> list[dict[str, Any]]:
    """Группы портов с вложенными VLAN (vlan_ids, по номеру VLAN) и открытыми портами группы
    (open_ports — id, protocol_catalog_id, transport_protocol, description; подписи порта/протокола
    клиент берёт из справочника «Протоколы и порты», как и для портов устройства). Два запроса на
    все группы разом, а не по запросу на группу."""
    if not groups:
        return []
    group_ids = [g.id for g in groups]
    vlan_links = session.execute(
        select(InterfaceGroupVLAN.group_id, InterfaceGroupVLAN.vlan_id)
        .join(VLAN, VLAN.id == InterfaceGroupVLAN.vlan_id)
        .where(InterfaceGroupVLAN.group_id.in_(group_ids))
        .order_by(VLAN.vlan_id, InterfaceGroupVLAN.vlan_id)
    ).all()
    ports = session.scalars(
        select(InterfaceGroupOpenPort)
        .join(ProtocolPortCatalog, InterfaceGroupOpenPort.protocol_catalog_id == ProtocolPortCatalog.id)
        .where(InterfaceGroupOpenPort.group_id.in_(group_ids))
        .order_by(ProtocolPortCatalog.port, InterfaceGroupOpenPort.transport_protocol)
    ).all()
    vlans_by_group: dict[str, list[str]] = {}
    for group_id, vlan_id in vlan_links:
        vlans_by_group.setdefault(group_id, []).append(vlan_id)
    # Группа с «Все VLAN» хранит только признак: её набор — все VLAN устройства (services/port_vlans.py), по номеру VLAN.
    flagged = [g for g in groups if carries_all_vlans(g)]
    if flagged:
        derived = effective_group_vlan_ids(flagged, session)
        wanted = set().union(*derived.values()) if derived else set()
        number_of = {vlan_id: number for vlan_id, number in session.execute(select(VLAN.id, VLAN.vlan_id).where(VLAN.id.in_(wanted))).all()} if wanted else {}
        for g in flagged:
            vlans_by_group[g.id] = sorted(derived.get(g.id, ()), key=lambda v: (number_of.get(v, 0), v))
    ports_by_group: dict[str, list[dict[str, Any]]] = {}
    for port in ports:
        ports_by_group.setdefault(port.group_id, []).append(serialize(port))
    return [
        {**serialize(g), 'vlan_ids': vlans_by_group.get(g.id, []), 'open_ports': ports_by_group.get(g.id, [])}
        for g in groups
    ]

def enrich_connections(items: Sequence[Connection], session: Session) -> list[dict[str, Any]]:
    if not items:
        return []
    interface_ids = list({x.source_interface_id for x in items} | {x.destination_interface_id for x in items})
    interfaces = session.scalars(select(DeviceInterface).where(DeviceInterface.id.in_(interface_ids))).all()
    iface_by_id = {x.id: x for x in interfaces}
    device_ids = list({x.physical_device_id for x in interfaces})
    devices = session.scalars(select(PhysicalDevice).where(PhysicalDevice.id.in_(device_ids))).all() if device_ids else []
    device_by_id = {x.id: x for x in devices}
    ct_ids = list({x.connection_type_id for x in items})
    ctypes = session.scalars(select(ConnectionType).where(ConnectionType.id.in_(ct_ids))).all() if ct_ids else []
    ct_by_id = {x.id: x for x in ctypes}
    configs = load_port_configs(session, interfaces)
    result=[]
    for conn in items:
        data=serialize(conn)
        src=iface_by_id.get(conn.source_interface_id); dst=iface_by_id.get(conn.destination_interface_id)
        sd=device_by_id.get(src.physical_device_id) if src else None; dd=device_by_id.get(dst.physical_device_id) if dst else None
        data['source_device_name']=sd.system_name or sd.serial_number if sd else ''
        data['source_interface_name']=src.name if src else ''
        data['destination_device_name']=dd.system_name or dd.serial_number if dd else ''
        data['destination_interface_name']=dst.name if dst else ''
        data['connection_type_name']=ct_by_id.get(conn.connection_type_id).name if ct_by_id.get(conn.connection_type_id) else ''
        # Конфигурация портов (роль, режим, VLAN) и статус сверки считаются здесь же, на сервере,
        # чтобы дашборд, форма и любой другой клиент видели одно и то же (правила — в
        # services/port_config.py). Сырая подпись одобрения — внутренняя деталь, наружу отдаётся
        # только итоговый статус и список различающихся граней.
        src_cfg, dst_cfg = configs.get(conn.source_interface_id), configs.get(conn.destination_interface_id)
        data['source_port_role']=src_cfg.role.value if src_cfg else None
        data['destination_port_role']=dst_cfg.role.value if dst_cfg else None
        data['source_vlan_mode']=src_cfg.mode if src_cfg else None
        data['destination_vlan_mode']=dst_cfg.mode if dst_cfg else None
        data['source_vlans']=sorted(src_cfg.vlans) if src_cfg else []
        data['destination_vlans']=sorted(dst_cfg.vlans) if dst_cfg else []
        paired = src_cfg is not None and dst_cfg is not None
        data['port_config_diff']=[f.value for f in config_differences(src_cfg, dst_cfg)] if paired and conn.is_active is not False else []
        data['port_config_status']=evaluate_port_config(src_cfg, dst_cfg, conn.port_config_approved_signature, is_active=conn.is_active is not False).value if paired else PortConfigStatus.OK.value
        data.pop('port_config_approved_signature', None)
        result.append(data)
    return result


def _load_information_systems_links(items: Sequence[InformationSystem], session: Session) -> SimpleNamespace:
    """Батч-загрузка всех связанных данных для enrich_information_systems(). Вынесено из неё же,
    чтобы снизить цикломатическую сложность внешней функции — логика не изменена."""
    ids = [x.id for x in items]
    ln = SimpleNamespace()
    dep_links = session.scalars(select(ISDepartment).where(ISDepartment.information_system_id.in_(ids))).all()
    proto_rows = session.scalars(select(ISProtocol).where(ISProtocol.information_system_id.in_(ids))).all()
    source_rows = session.scalars(select(InformationSystemSource).where(InformationSystemSource.information_system_id.in_(ids))).all()
    placement_links = session.scalars(select(ISPlacementAsset).where(ISPlacementAsset.information_system_id.in_(ids))).all()

    support_ids = {x.support_organization_id for x in items if x.support_organization_id}
    ln.support_map = {x.id: x for x in session.scalars(select(SupportOrganization).where(SupportOrganization.id.in_(support_ids))).all()} if support_ids else {}
    method_ids = {x.support_method_id for x in items if x.support_method_id}
    ln.method_map = {x.id: x for x in session.scalars(select(SupportMethod).where(SupportMethod.id.in_(method_ids))).all()} if method_ids else {}
    placement_ids = {x.placement_asset_id for x in placement_links}
    ln.placement_map = {x.id: x for x in session.scalars(select(PlacementAsset).where(PlacementAsset.id.in_(placement_ids))).all()} if placement_ids else {}
    ln.placement_by_is: dict[str, list[ISPlacementAsset]] = {}
    for x in placement_links: ln.placement_by_is.setdefault(x.information_system_id, []).append(x)
    dep_ids = {x.department_id for x in dep_links}
    ln.dep_map = {x.id: x for x in session.scalars(select(Department).where(Department.id.in_(dep_ids))).all()} if dep_ids else {}

    # owner_id хранит id устройства/ВМ/контейнера в зависимости от source_type (миграция
    # 944bd490d967, см. models.InformationSystemSource) — раньше это были три отдельные FK-колонки,
    # каждая фильтровалась просто на "не NULL"; теперь принадлежность владельца к конкретному типу
    # определяется исключительно по source_type, поэтому фильтр по нему обязателен на каждой строке.
    device_ids = {x.owner_id for x in source_rows if x.source_type == SourceType.DEVICE and x.owner_id}
    ln.device_map = {x.id: x for x in session.scalars(select(PhysicalDevice).where(PhysicalDevice.id.in_(device_ids))).all()} if device_ids else {}

    vm_ids = {x.owner_id for x in source_rows if x.source_type == SourceType.VM and x.owner_id}
    ln.vm_map = {x.id: x for x in session.scalars(select(VirtualMachine).where(VirtualMachine.id.in_(vm_ids))).all()} if vm_ids else {}

    cont_ids = {x.owner_id for x in source_rows if x.source_type == SourceType.CONTAINER and x.owner_id}
    ln.cont_map = {x.id: x for x in session.scalars(select(Container).where(Container.id.in_(cont_ids))).all()} if cont_ids else {}

    proto_ids = {x.protocol_catalog_id for x in proto_rows if x.protocol_catalog_id}
    ln.proto_map = {x.id: x for x in session.scalars(select(ProtocolPortCatalog).where(ProtocolPortCatalog.id.in_(proto_ids))).all()} if proto_ids else {}

    ln.dep_by_is: dict[str, list[ISDepartment]] = {}; ln.proto_by_is: dict[str, list[ISProtocol]] = {}
    ln.source_by_is: dict[str, list[InformationSystemSource]] = {}
    for x in dep_links: ln.dep_by_is.setdefault(x.information_system_id, []).append(x)
    for x in proto_rows: ln.proto_by_is.setdefault(x.information_system_id, []).append(x)
    for x in source_rows: ln.source_by_is.setdefault(x.information_system_id, []).append(x)

    # Every VM referenced by any IS (through a source row) contributes its actual IPs to that IS's
    # summary. Loaded once here for all systems, instead of once per system inside the loop below,
    # to avoid an N+1 query against IPAddress.
    all_referenced_vm_ids = set(ln.vm_map.keys())
    ln.vm_ips_by_vm: dict[str, list[IPAddress]] = {}
    if all_referenced_vm_ids:
        for x in session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.VIRTUAL_MACHINE, IPAddress.owner_id.in_(all_referenced_vm_ids))).all():
            ln.vm_ips_by_vm.setdefault(x.owner_id, []).append(x)

    # IP-адреса "ручных" источников ИС — раньше src.ip_address (одна строка, несколько адресов
    # через запятую), теперь отдельные строки IPAddress (миграция d8e35a1c7f60, owner_type=
    # "information_system_source"), по той же причине загружены здесь одним batch-запросом.
    ln.source_ips_by_source: dict[str, list[IPAddress]] = {}
    if source_rows:
        for x in session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.INFORMATION_SYSTEM_SOURCE, IPAddress.owner_id.in_([s.id for s in source_rows]))).all():
            ln.source_ips_by_source.setdefault(x.owner_id, []).append(x)
    return ln


def _enrich_single_information_system(obj: InformationSystem, ln: SimpleNamespace) -> dict[str, Any]:
    """Строит читаемые summary-поля для одной ИС из унифицированных source-записей
    (InformationSystemSource — единственный механизм этой связи, см. models.py). Вынесено из
    enrich_information_systems() по той же причине, что и загрузка выше."""
    data = serialize(obj)
    data['support_organization_name'] = ln.support_map.get(obj.support_organization_id).name if obj.support_organization_id and ln.support_map.get(obj.support_organization_id) else ''
    data['support_method_name'] = ln.method_map.get(obj.support_method_id).name if obj.support_method_id and ln.method_map.get(obj.support_method_id) else ''
    data['placement_assets_summary'] = '; '.join(dict.fromkeys(ln.placement_map[x.placement_asset_id].name for x in ln.placement_by_is.get(obj.id, []) if x.placement_asset_id in ln.placement_map))
    data['departments_summary'] = '; '.join(dict.fromkeys(ln.dep_map[x.department_id].name for x in ln.dep_by_is.get(obj.id, []) if x.department_id in ln.dep_map))

    ips = []
    devices = []
    vms = []
    containers = []
    for src in ln.source_by_is.get(obj.id, []):
        ips.extend(x.ip_address for x in ln.source_ips_by_source.get(src.id, []))
        if src.source_type == SourceType.DEVICE and src.owner_id in ln.device_map and ln.device_map[src.owner_id] not in devices:
            devices.append(ln.device_map[src.owner_id])
        if src.source_type == SourceType.VM and src.owner_id in ln.vm_map and ln.vm_map[src.owner_id] not in vms:
            vms.append(ln.vm_map[src.owner_id])
        if src.source_type == SourceType.CONTAINER and src.owner_id in ln.cont_map and ln.cont_map[src.owner_id] not in containers:
            containers.append(ln.cont_map[src.owner_id])

    # If an IS is linked to a VM, include its actual VM IPs in the summary.
    for v in vms:
        ips.extend(f'{x.ip_address}/{x.prefix_length}' if x.prefix_length is not None else x.ip_address for x in ln.vm_ips_by_vm.get(v.id, []))

    data['ip_addresses_summary'] = '; '.join(dict.fromkeys(x for x in ips if x))
    # protocol_catalog_id обязателен для ISProtocol (NOT NULL, миграция b7f2c1e5a904) — свободного
    # текста без справочника, ради которого раньше был нужен fallback, больше не бывает.
    data['protocols_summary'] = '; '.join(dict.fromkeys(
        f'{ln.proto_map[x.protocol_catalog_id].protocol_type}/{ln.proto_map[x.protocol_catalog_id].port}'
        for x in ln.proto_by_is.get(obj.id, []) if x.protocol_catalog_id in ln.proto_map
    ))
    data['physical_devices_summary'] = '; '.join(dict.fromkeys((d.system_name or d.serial_number or d.id) for d in devices))
    data['vms_summary'] = '; '.join(dict.fromkeys(v.name or v.id for v in vms))
    data['containers_summary'] = '; '.join(dict.fromkeys(c.name or c.id for c in containers))
    return data


def enrich_information_systems(items: Sequence[InformationSystem], session: Session) -> list[dict[str, Any]]:
    if not items:
        return []
    ln = _load_information_systems_links(items, session)
    return [_enrich_single_information_system(obj, ln) for obj in items]

