from __future__ import annotations
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Sequence
from sqlalchemy import select
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session
from ..models import (Connection, ConnectionType, DeviceInterface, InterfaceIP, PhysicalDevice, SupportOrganization, SupportMethod, PlacementAsset, ISPlacementAsset, VirtualMachine, InformationSystem, ISDepartment, ISIP, ISProtocol, ISDevice, ISVM, ISContainer, InformationSystemSource, Department, Container, ProtocolPortCatalog, VMIP, EmbeddedOperatingSystem, PhysicalDeviceVLAN, VLAN)
from .computed import device_management_ports_and_ips

def serialize(obj: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for col in inspect(obj).mapper.column_attrs:
        value = getattr(obj, col.key)
        result[col.key] = value.isoformat() if isinstance(value, datetime) else value
    return result

def enrich_devices(devices: Sequence[PhysicalDevice], session: Session) -> list[dict[str, Any]]:
    if not devices: return []
    device_ids = [d.id for d in devices]
    interfaces = session.scalars(select(DeviceInterface).where(DeviceInterface.physical_device_id.in_(device_ids)).order_by(DeviceInterface.name)).all()
    by_device: dict[str, list[DeviceInterface]] = {}
    for iface in interfaces: by_device.setdefault(iface.physical_device_id, []).append(iface)
    interface_ids = [i.id for i in interfaces]
    ips = session.scalars(select(InterfaceIP).where(InterfaceIP.interface_id.in_(interface_ids)).order_by(InterfaceIP.ip_address)).all() if interface_ids else []
    ips_by_interface: dict[str, list[InterfaceIP]] = {}
    for ip in ips: ips_by_interface.setdefault(ip.interface_id, []).append(ip)
    embedded_ids = {d.embedded_os_id for d in devices if getattr(d, 'embedded_os_id', None)}
    embedded_map = {x.id: x for x in session.scalars(select(EmbeddedOperatingSystem).where(EmbeddedOperatingSystem.id.in_(embedded_ids))).all()} if embedded_ids else {}
    vlan_links = session.scalars(select(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.physical_device_id.in_(device_ids))).all()
    vlan_ids = {x.vlan_id for x in vlan_links}
    vlan_map = {x.id: x for x in session.scalars(select(VLAN).where(VLAN.id.in_(vlan_ids))).all()} if vlan_ids else {}
    vlans_by_device: dict[str, list[PhysicalDeviceVLAN]] = {}
    for link in vlan_links: vlans_by_device.setdefault(link.physical_device_id, []).append(link)
    result=[]
    for device in devices:
        data=serialize(device); management=[i for i in by_device.get(device.id, []) if i.is_management]
        mgmt_vlan_links=[x for x in vlans_by_device.get(device.id, []) if x.is_management]
        mgmt_names, mgmt_ips = device_management_ports_and_ips(management, ips_by_interface, mgmt_vlan_links, vlan_map)
        data['management_interface']='; '.join(mgmt_names)
        data['management_ips']='; '.join(mgmt_ips)
        data['interface_count']=len(by_device.get(device.id, []))
        data['embedded_os_name']=embedded_map.get(device.embedded_os_id).name if device.embedded_os_id and embedded_map.get(device.embedded_os_id) else ''
        data['embedded_os_version']=embedded_map.get(device.embedded_os_id).version if device.embedded_os_id and embedded_map.get(device.embedded_os_id) else ''
        data['vlan_summary']='; '.join(dict.fromkeys(f"{vlan_map[x.vlan_id].vlan_id} {vlan_map[x.vlan_id].name}" for x in vlans_by_device.get(device.id, []) if x.vlan_id in vlan_map))
        result.append(data)
    return result


def enrich_interfaces(items: Sequence[DeviceInterface], session: Session) -> list[dict[str, Any]]:
    if not items:
        return []
    interface_ids = [i.id for i in items]
    ips = session.scalars(
        select(InterfaceIP).where(InterfaceIP.interface_id.in_(interface_ids)).order_by(InterfaceIP.ip_address)
    ).all()
    by_interface: dict[str, list[InterfaceIP]] = {}
    for ip in ips:
        by_interface.setdefault(ip.interface_id, []).append(ip)
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
        result.append(data)
    return result


def _load_information_systems_links(items: Sequence[InformationSystem], session: Session) -> SimpleNamespace:
    """Батч-загрузка всех связанных данных для enrich_information_systems(). Вынесено из неё же,
    чтобы снизить цикломатическую сложность внешней функции (была 19) — логика не изменена."""
    ids = [x.id for x in items]
    ln = SimpleNamespace()
    dep_links = session.scalars(select(ISDepartment).where(ISDepartment.information_system_id.in_(ids))).all()
    ip_rows = session.scalars(select(ISIP).where(ISIP.information_system_id.in_(ids)).order_by(ISIP.ip_address)).all()
    proto_rows = session.scalars(select(ISProtocol).where(ISProtocol.information_system_id.in_(ids))).all()
    dev_links = session.scalars(select(ISDevice).where(ISDevice.information_system_id.in_(ids))).all()
    vm_links = session.scalars(select(ISVM).where(ISVM.information_system_id.in_(ids))).all()
    cont_links = session.scalars(select(ISContainer).where(ISContainer.information_system_id.in_(ids))).all()
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

    device_ids = {x.physical_device_id for x in dev_links if x.physical_device_id}
    device_ids.update(x.physical_device_id for x in source_rows if x.physical_device_id)
    ln.device_map = {x.id: x for x in session.scalars(select(PhysicalDevice).where(PhysicalDevice.id.in_(device_ids))).all()} if device_ids else {}

    vm_ids = {x.virtual_machine_id for x in vm_links if x.virtual_machine_id}
    vm_ids.update(x.virtual_machine_id for x in source_rows if x.virtual_machine_id)
    ln.vm_map = {x.id: x for x in session.scalars(select(VirtualMachine).where(VirtualMachine.id.in_(vm_ids))).all()} if vm_ids else {}

    cont_ids = {x.container_id for x in cont_links if x.container_id}
    cont_ids.update(x.container_id for x in source_rows if x.container_id)
    ln.cont_map = {x.id: x for x in session.scalars(select(Container).where(Container.id.in_(cont_ids))).all()} if cont_ids else {}

    proto_ids = {x.protocol_catalog_id for x in proto_rows if x.protocol_catalog_id}
    ln.proto_map = {x.id: x for x in session.scalars(select(ProtocolPortCatalog).where(ProtocolPortCatalog.id.in_(proto_ids))).all()} if proto_ids else {}

    ln.dep_by_is: dict[str, list[ISDepartment]] = {}; ln.ip_by_is: dict[str, list[ISIP]] = {}; ln.proto_by_is: dict[str, list[ISProtocol]] = {}
    ln.dev_by_is: dict[str, list[ISDevice]] = {}; ln.vm_by_is: dict[str, list[ISVM]] = {}; ln.cont_by_is: dict[str, list[ISContainer]] = {}; ln.source_by_is: dict[str, list[InformationSystemSource]] = {}
    for x in dep_links: ln.dep_by_is.setdefault(x.information_system_id, []).append(x)
    for x in ip_rows: ln.ip_by_is.setdefault(x.information_system_id, []).append(x)
    for x in proto_rows: ln.proto_by_is.setdefault(x.information_system_id, []).append(x)
    for x in dev_links: ln.dev_by_is.setdefault(x.information_system_id, []).append(x)
    for x in vm_links: ln.vm_by_is.setdefault(x.information_system_id, []).append(x)
    for x in cont_links: ln.cont_by_is.setdefault(x.information_system_id, []).append(x)
    for x in source_rows: ln.source_by_is.setdefault(x.information_system_id, []).append(x)

    # Every VM referenced by any IS (via ISVM or a unified source row) contributes its actual
    # IPs to that IS's summary. Loaded once here for all systems, instead of once per system
    # inside the loop below, to avoid an N+1 query against VMIP.
    all_referenced_vm_ids = set(ln.vm_map.keys())
    ln.vm_ips_by_vm: dict[str, list[VMIP]] = {}
    if all_referenced_vm_ids:
        for x in session.scalars(select(VMIP).where(VMIP.virtual_machine_id.in_(all_referenced_vm_ids))).all():
            ln.vm_ips_by_vm.setdefault(x.virtual_machine_id, []).append(x)
    return ln


def _enrich_single_information_system(obj: InformationSystem, ln: SimpleNamespace) -> dict[str, Any]:
    """Строит читаемые summary-поля для одной ИС из нормализованных legacy-связей и унифицированных
    source-записей. Вынесено из enrich_information_systems() по той же причине, что и загрузка выше."""
    data = serialize(obj)
    data['support_organization_name'] = ln.support_map.get(obj.support_organization_id).name if obj.support_organization_id and ln.support_map.get(obj.support_organization_id) else ''
    data['support_method_name'] = ln.method_map.get(obj.support_method_id).name if obj.support_method_id and ln.method_map.get(obj.support_method_id) else ''
    data['placement_assets_summary'] = '; '.join(dict.fromkeys(ln.placement_map[x.placement_asset_id].name for x in ln.placement_by_is.get(obj.id, []) if x.placement_asset_id in ln.placement_map))
    data['departments_summary'] = '; '.join(dict.fromkeys(ln.dep_map[x.department_id].name for x in ln.dep_by_is.get(obj.id, []) if x.department_id in ln.dep_map))

    ips = [x.ip_address for x in ln.ip_by_is.get(obj.id, []) if x.ip_address]
    devices = [ln.device_map[x.physical_device_id] for x in ln.dev_by_is.get(obj.id, []) if x.physical_device_id in ln.device_map]
    vms = [ln.vm_map[x.virtual_machine_id] for x in ln.vm_by_is.get(obj.id, []) if x.virtual_machine_id in ln.vm_map]
    containers = [ln.cont_map[x.container_id] for x in ln.cont_by_is.get(obj.id, []) if x.container_id in ln.cont_map]
    for src in ln.source_by_is.get(obj.id, []):
        if src.ip_address:
            ips.extend(p.strip() for p in src.ip_address.split(',') if p.strip())
        if src.physical_device_id in ln.device_map and ln.device_map[src.physical_device_id] not in devices:
            devices.append(ln.device_map[src.physical_device_id])
        if src.virtual_machine_id in ln.vm_map and ln.vm_map[src.virtual_machine_id] not in vms:
            vms.append(ln.vm_map[src.virtual_machine_id])
        if src.container_id in ln.cont_map and ln.cont_map[src.container_id] not in containers:
            containers.append(ln.cont_map[src.container_id])

    # If an IS is linked to a VM, include its actual VM IPs in the summary.
    for v in vms:
        ips.extend(f'{x.ip_address}/{x.prefix_length}' if x.prefix_length is not None else x.ip_address for x in ln.vm_ips_by_vm.get(v.id, []))

    data['ip_addresses_summary'] = '; '.join(dict.fromkeys(x for x in ips if x))
    data['protocols_summary'] = '; '.join(dict.fromkeys(
        (f'{ln.proto_map[x.protocol_catalog_id].protocol_type}/{ln.proto_map[x.protocol_catalog_id].port}' if x.protocol_catalog_id in ln.proto_map else f'{x.protocol}/{x.port}' if x.port else x.protocol)
        for x in ln.proto_by_is.get(obj.id, []) if x.protocol or x.protocol_catalog_id
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

