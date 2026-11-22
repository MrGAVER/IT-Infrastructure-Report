from __future__ import annotations
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Sequence
from sqlalchemy import select
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session
from ..models import (
    Connection,
    ConnectionType,
    DeviceInterface,
    DeviceSubinterface,
    IPAddress,
    OpenPort,
    PhysicalDevice,
    SupportOrganization,
    SupportMethod,
    PlacementAsset,
    ISPlacementAsset,
    VirtualMachine,
    InformationSystem,
    ISDepartment,
    ISProtocol,
    InformationSystemSource,
    Department,
    Container,
    ProtocolPortCatalog,
    EmbeddedOperatingSystem,
    PhysicalDeviceVLAN,
    VLAN,
    DeviceStack,
    DeviceStackMember,
    InterfaceGroup,
    InterfaceGroupIP,
    InterfaceGroupOpenPort,
    InterfaceGroupVLAN,
)
from .port_config import PortConfigStatus, evaluate_port_config, config_differences
from .port_config_db import load_port_configs
from .port_vlans import carries_all_vlans, effective_group_vlan_ids
from ..constants import OwnerType, SourceType
from .computed import device_management_ports_and_ips
from .device_label import device_label
from .timeutil import iso_utc


def serialize(obj: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for col in inspect(obj).mapper.column_attrs:
        value = getattr(obj, col.key)
        # iso_utc покрывает и DateTime-колонки (created_at/updated_at — ISO 8601 с явным «+00:00», в БД лежит naive UTC),
        # и обычные Date-колонки (например, PhysicalDevice.oac_certificate_registry_date — «YYYY-MM-DD» как раньше).
        result[col.key] = iso_utc(value)
    return result


# --- общие помощники загрузки: одна пачка запросов на все строки, а не по запросу на строку -------------------------


def _select_in(session: Session, model: Any, column: Any, values: Iterable[Any], *order_by: Any, extra: Sequence[Any] = ()) -> list[Any]:
    """Строки модели, у которых column входит в values (extra — дополнительные условия WHERE). Без значений запрос не выполняется."""
    keys = list(values)
    if not keys:
        return []
    stmt = select(model).where(*extra, column.in_(keys))
    if order_by:
        stmt = stmt.order_by(*order_by)
    return list(session.scalars(stmt).all())


def _by_id(rows: Iterable[Any]) -> dict[str, Any]:
    return {row.id: row for row in rows}


def _group_by(rows: Iterable[Any], key: Callable[[Any], str]) -> dict[str, list[Any]]:
    groups: dict[str, list[Any]] = {}
    for row in rows:
        groups.setdefault(key(row), []).append(row)
    return groups


def _ips_by_owner(session: Session, owner_type: str, owner_ids: Iterable[str]) -> dict[str, list[IPAddress]]:
    """IP-адреса владельцев одного вида (по возрастанию адреса), сгруппированные по id владельца."""
    rows = _select_in(session, IPAddress, IPAddress.owner_id, owner_ids, IPAddress.ip_address, extra=(IPAddress.owner_type == owner_type,))
    return _group_by(rows, lambda ip: ip.owner_id)


def _ip_text(ip: IPAddress) -> str:
    return f"{ip.ip_address}/{ip.prefix_length}" if ip.prefix_length is not None else ip.ip_address


def _unique_joined(values: Iterable[str]) -> str:
    """Значения через «; » без повторов, в порядке первого появления."""
    return "; ".join(dict.fromkeys(values))


def enrich_open_port(obj: OpenPort, session: Session) -> dict[str, Any]:
    """port/protocol больше не колонки OpenPort (см. models.py, миграция b7f2c1e5a904) —
    вычисляются на КАЖДОЕ чтение из protocol_port_catalogs по protocol_catalog_id, поэтому правка
    записи справочника отражается на уже созданных портах сразу, без их отдельного пересохранения.
    Единичный вариант enrich_open_ports() ниже — для одного объекта (create_resource/
    update_resource), где батч-загрузка каталога не даёт выигрыша."""
    data = serialize(obj)
    cat = session.get(ProtocolPortCatalog, obj.protocol_catalog_id)
    data["port"] = cat.port if cat else None
    data["protocol"] = cat.protocol_type if cat else None
    return data


def enrich_open_ports(items: Sequence[OpenPort], session: Session) -> list[dict[str, Any]]:
    """Батч-вариант enrich_open_port() — для списков (list_resource('open-ports'),
    sync_interfaces): одним запросом подгружает все нужные записи справочника, а не по одной на
    порт."""
    if not items:
        return []
    catalog_ids = {x.protocol_catalog_id for x in items if x.protocol_catalog_id}
    catalog_map = {x.id: x for x in session.scalars(select(ProtocolPortCatalog).where(ProtocolPortCatalog.id.in_(catalog_ids))).all()} if catalog_ids else {}
    result = []
    for obj in items:
        data = serialize(obj)
        cat = catalog_map.get(obj.protocol_catalog_id)
        data["port"] = cat.port if cat else None
        data["protocol"] = cat.protocol_type if cat else None
        result.append(data)
    return result


@dataclass(frozen=True)
class _DeviceLookups:
    """Всё, что нужно собрать вычисляемые поля устройств, загруженное разом для всех устройств страницы."""

    interfaces_by_device: dict[str, list[DeviceInterface]]
    ips_by_interface: dict[str, list[IPAddress]]
    mgmt_subs_by_device: dict[str, list[DeviceSubinterface]]
    ips_by_subinterface: dict[str, list[IPAddress]]
    port_name_by_id: dict[str, str]
    embedded_map: dict[str, EmbeddedOperatingSystem]
    vlan_map: dict[str, VLAN]
    vlans_by_device: dict[str, list[PhysicalDeviceVLAN]]
    member_by_device: dict[str, DeviceStackMember]
    stack_map: dict[str, DeviceStack]


def _load_device_lookups(devices: Sequence[PhysicalDevice], session: Session) -> _DeviceLookups:
    device_ids = [d.id for d in devices]
    interfaces = _select_in(session, DeviceInterface, DeviceInterface.physical_device_id, device_ids, DeviceInterface.name)
    device_by_interface = {i.id: i.physical_device_id for i in interfaces}
    # Управление может висеть на подинтерфейсе порта (например, Gi0/0.99 на VLAN управления): подинтерфейс с ролью
    # «Управление» даёт порт и IP управления устройства так же, как в отчётах (reporting.py). Берём только такие
    # подинтерфейсы — остальные на дашборде устройств не нужны.
    mgmt_subs = _select_in(session, DeviceSubinterface, DeviceSubinterface.parent_interface_id, device_by_interface, DeviceSubinterface.name, DeviceSubinterface.id, extra=(DeviceSubinterface.is_management.is_(True),))
    vlan_links = _select_in(session, PhysicalDeviceVLAN, PhysicalDeviceVLAN.physical_device_id, device_ids)
    # Устройство состоит максимум в одном стеке (UniqueConstraint на DeviceStackMember.physical_device_id), поэтому
    # member_by_device — словарь «один к одному», без списков.
    members = _select_in(session, DeviceStackMember, DeviceStackMember.physical_device_id, device_ids)
    embedded_ids = {d.embedded_os_id for d in devices if getattr(d, "embedded_os_id", None)}
    return _DeviceLookups(
        interfaces_by_device=_group_by(interfaces, lambda i: i.physical_device_id),
        ips_by_interface=_ips_by_owner(session, OwnerType.DEVICE_INTERFACE, device_by_interface),
        mgmt_subs_by_device=_group_by(mgmt_subs, lambda sub: device_by_interface[sub.parent_interface_id]),
        ips_by_subinterface=_ips_by_owner(session, OwnerType.DEVICE_SUBINTERFACE, [sub.id for sub in mgmt_subs]),
        port_name_by_id={i.id: i.name for i in interfaces},
        embedded_map=_by_id(_select_in(session, EmbeddedOperatingSystem, EmbeddedOperatingSystem.id, embedded_ids)),
        vlan_map=_by_id(_select_in(session, VLAN, VLAN.id, {x.vlan_id for x in vlan_links})),
        vlans_by_device=_group_by(vlan_links, lambda link: link.physical_device_id),
        member_by_device={m.physical_device_id: m for m in members},
        stack_map=_by_id(_select_in(session, DeviceStack, DeviceStack.id, {m.stack_id for m in members})),
    )


def _device_computed_fields(device: PhysicalDevice, lk: _DeviceLookups) -> dict[str, Any]:
    ports = lk.interfaces_by_device.get(device.id, [])
    vlan_links = lk.vlans_by_device.get(device.id, [])
    mgmt_names, mgmt_ips = device_management_ports_and_ips(
        [i for i in ports if i.is_management],
        lk.ips_by_interface,
        [x for x in vlan_links if x.is_management],
        lk.vlan_map,
        management_subinterfaces=lk.mgmt_subs_by_device.get(device.id, []),
        ips_by_subinterface=lk.ips_by_subinterface,
        port_name_by_id=lk.port_name_by_id,
    )
    embedded = lk.embedded_map.get(device.embedded_os_id) if device.embedded_os_id else None
    member = lk.member_by_device.get(device.id)
    stack = lk.stack_map.get(member.stack_id) if member else None
    return {
        "management_interface": "; ".join(mgmt_names),
        "management_ips": "; ".join(mgmt_ips),
        "interface_count": len(ports),
        "embedded_os_name": embedded.name if embedded else "",
        "embedded_os_version": embedded.version if embedded else "",
        "vlan_summary": _unique_joined(f"{lk.vlan_map[x.vlan_id].vlan_id} {lk.vlan_map[x.vlan_id].name}" for x in vlan_links if x.vlan_id in lk.vlan_map),
        "stack_id": member.stack_id if member else None,
        "stack_name": stack.name if stack else None,
        "stack_position": member.position if member else None,
    }


def enrich_devices(devices: Sequence[PhysicalDevice], session: Session) -> list[dict[str, Any]]:
    if not devices:
        return []
    lookups = _load_device_lookups(devices, session)
    return [{**serialize(device), **_device_computed_fields(device, lookups)} for device in devices]


def enrich_interfaces(items: Sequence[DeviceInterface], session: Session) -> list[dict[str, Any]]:
    if not items:
        return []
    ips_by_interface = _ips_by_owner(session, OwnerType.DEVICE_INTERFACE, [i.id for i in items])
    result = []
    for iface in items:
        data = serialize(iface)
        ip_text = "; ".join(_ip_text(ip) for ip in ips_by_interface.get(iface.id, []))
        data["ip_addresses"] = ip_text
        data["management_ips"] = ip_text if iface.is_management else ""
        result.append(data)
    return result


def _ip_sort_key(ip: InterfaceGroupIP) -> tuple[Any, ...]:
    """Числовой порядок IPv4 (10.0.0.9 перед 10.0.0.10); нечитаемый адрес — после остальных, по тексту."""
    try:
        return (0, tuple(int(part) for part in ip.ip_address.split(".")), ip.id)
    except ValueError:
        return (1, (), ip.ip_address, ip.id)


def enrich_interface_groups(groups: Sequence[InterfaceGroup], session: Session) -> list[dict[str, Any]]:
    """Группы портов с вложенными VLAN (vlan_ids, по номеру VLAN), общими IP-адресами (ips — id, ip_address,
    prefix_length, purpose; в числовом порядке адресов) и открытыми портами группы
    (open_ports — id, protocol_catalog_id, transport_protocol, description; подписи порта/протокола
    клиент берёт из справочника «Протоколы и порты», как и для портов устройства). Запросы — по одному
    на вид вложенных данных для всех групп разом, а не по запросу на группу."""
    if not groups:
        return []
    group_ids = [g.id for g in groups]
    vlan_links = session.execute(
        select(InterfaceGroupVLAN.group_id, InterfaceGroupVLAN.vlan_id).join(VLAN, VLAN.id == InterfaceGroupVLAN.vlan_id).where(InterfaceGroupVLAN.group_id.in_(group_ids)).order_by(VLAN.vlan_id, InterfaceGroupVLAN.vlan_id)
    ).all()
    ports = session.scalars(
        select(InterfaceGroupOpenPort)
        .join(ProtocolPortCatalog, InterfaceGroupOpenPort.protocol_catalog_id == ProtocolPortCatalog.id)
        .where(InterfaceGroupOpenPort.group_id.in_(group_ids))
        .order_by(ProtocolPortCatalog.port, InterfaceGroupOpenPort.transport_protocol)
    ).all()
    ips_by_group: dict[str, list[dict[str, Any]]] = {}
    for ip in sorted(session.scalars(select(InterfaceGroupIP).where(InterfaceGroupIP.group_id.in_(group_ids))).all(), key=_ip_sort_key):
        ips_by_group.setdefault(ip.group_id, []).append(serialize(ip))
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
    return [{**serialize(g), "vlan_ids": vlans_by_group.get(g.id, []), "ips": ips_by_group.get(g.id, []), "open_ports": ports_by_group.get(g.id, [])} for g in groups]


@dataclass(frozen=True)
class _ConnectionLookups:
    interfaces: dict[str, DeviceInterface]
    devices: dict[str, PhysicalDevice]
    connection_types: dict[str, ConnectionType]
    configs: dict[str, Any]  # конфигурация порта (роль, режим, VLAN) по id порта — см. services/port_config_db.py


def _load_connection_lookups(items: Sequence[Connection], session: Session) -> _ConnectionLookups:
    interface_ids = {x.source_interface_id for x in items} | {x.destination_interface_id for x in items}
    interfaces = _select_in(session, DeviceInterface, DeviceInterface.id, interface_ids)
    return _ConnectionLookups(
        interfaces=_by_id(interfaces),
        devices=_by_id(_select_in(session, PhysicalDevice, PhysicalDevice.id, {x.physical_device_id for x in interfaces})),
        connection_types=_by_id(_select_in(session, ConnectionType, ConnectionType.id, {x.connection_type_id for x in items})),
        configs=load_port_configs(session, interfaces),
    )


def _endpoint_fields(side: str, iface: DeviceInterface | None, device: PhysicalDevice | None, config: Any) -> dict[str, Any]:
    """Поля одного конца подключения (side — 'source' или 'destination'): устройство, порт и его конфигурация."""
    return {
        f"{side}_device_name": device_label(device),
        f"{side}_interface_name": iface.name if iface else "",
        f"{side}_port_role": config.role.value if config else None,
        f"{side}_vlan_mode": config.mode if config else None,
        f"{side}_vlans": sorted(config.vlans) if config else [],
    }


def _port_config_fields(conn: Connection, src_cfg: Any, dst_cfg: Any) -> dict[str, Any]:
    """Статус сверки конфигурации портов и список различающихся граней. Считаются здесь же, на сервере, чтобы дашборд, форма
    и любой другой клиент видели одно и то же (правила — в services/port_config.py)."""
    paired = src_cfg is not None and dst_cfg is not None
    active = conn.is_active is not False
    return {
        "port_config_diff": [f.value for f in config_differences(src_cfg, dst_cfg)] if paired and active else [],
        "port_config_status": evaluate_port_config(src_cfg, dst_cfg, conn.port_config_approved_signature, is_active=active).value if paired else PortConfigStatus.OK.value,
    }


def _connection_computed_fields(conn: Connection, lk: _ConnectionLookups) -> dict[str, Any]:
    src = lk.interfaces.get(conn.source_interface_id)
    dst = lk.interfaces.get(conn.destination_interface_id)
    src_cfg, dst_cfg = lk.configs.get(conn.source_interface_id), lk.configs.get(conn.destination_interface_id)
    connection_type = lk.connection_types.get(conn.connection_type_id)
    return {
        **_endpoint_fields("source", src, lk.devices.get(src.physical_device_id) if src else None, src_cfg),
        **_endpoint_fields("destination", dst, lk.devices.get(dst.physical_device_id) if dst else None, dst_cfg),
        "connection_type_name": connection_type.name if connection_type else "",
        **_port_config_fields(conn, src_cfg, dst_cfg),
    }


def enrich_connections(items: Sequence[Connection], session: Session) -> list[dict[str, Any]]:
    if not items:
        return []
    lookups = _load_connection_lookups(items, session)
    result = []
    for conn in items:
        data = {**serialize(conn), **_connection_computed_fields(conn, lookups)}
        # Сырая подпись одобрения — внутренняя деталь: наружу отдаётся только итоговый статус и список различающихся граней.
        data.pop("port_config_approved_signature", None)
        result.append(data)
    return result


@dataclass(frozen=True)
class _InformationSystemLinks:
    """Связанные данные всех ИС страницы, загруженные разом (иначе — запрос на каждую ИС)."""

    support_map: dict[str, SupportOrganization]
    method_map: dict[str, SupportMethod]
    placement_map: dict[str, PlacementAsset]
    placement_by_is: dict[str, list[ISPlacementAsset]]
    dep_map: dict[str, Department]
    dep_by_is: dict[str, list[ISDepartment]]
    proto_map: dict[str, ProtocolPortCatalog]
    proto_by_is: dict[str, list[ISProtocol]]
    source_by_is: dict[str, list[InformationSystemSource]]
    device_map: dict[str, PhysicalDevice]
    vm_map: dict[str, VirtualMachine]
    cont_map: dict[str, Container]
    vm_ips_by_vm: dict[str, list[IPAddress]]
    source_ips_by_source: dict[str, list[IPAddress]]


def _owner_ids(sources: Sequence[InformationSystemSource], source_type: str) -> set[str]:
    # owner_id хранит id устройства/ВМ/контейнера в зависимости от source_type (миграция 944bd490d967): принадлежность
    # владельца к виду определяется только по source_type, поэтому фильтр по нему обязателен на каждой строке.
    return {x.owner_id for x in sources if x.source_type == source_type and x.owner_id}


def _load_information_systems_links(items: Sequence[InformationSystem], session: Session) -> _InformationSystemLinks:
    """Батч-загрузка всех связанных данных для enrich_information_systems()."""
    ids = [x.id for x in items]
    deps = _select_in(session, ISDepartment, ISDepartment.information_system_id, ids)
    protocols = _select_in(session, ISProtocol, ISProtocol.information_system_id, ids)
    sources = _select_in(session, InformationSystemSource, InformationSystemSource.information_system_id, ids)
    placements = _select_in(session, ISPlacementAsset, ISPlacementAsset.information_system_id, ids)
    vm_map = _by_id(_select_in(session, VirtualMachine, VirtualMachine.id, _owner_ids(sources, SourceType.VM)))
    return _InformationSystemLinks(
        support_map=_by_id(_select_in(session, SupportOrganization, SupportOrganization.id, {x.support_organization_id for x in items if x.support_organization_id})),
        method_map=_by_id(_select_in(session, SupportMethod, SupportMethod.id, {x.support_method_id for x in items if x.support_method_id})),
        placement_map=_by_id(_select_in(session, PlacementAsset, PlacementAsset.id, {x.placement_asset_id for x in placements})),
        placement_by_is=_group_by(placements, lambda x: x.information_system_id),
        dep_map=_by_id(_select_in(session, Department, Department.id, {x.department_id for x in deps})),
        dep_by_is=_group_by(deps, lambda x: x.information_system_id),
        proto_map=_by_id(_select_in(session, ProtocolPortCatalog, ProtocolPortCatalog.id, {x.protocol_catalog_id for x in protocols if x.protocol_catalog_id})),
        proto_by_is=_group_by(protocols, lambda x: x.information_system_id),
        source_by_is=_group_by(sources, lambda x: x.information_system_id),
        device_map=_by_id(_select_in(session, PhysicalDevice, PhysicalDevice.id, _owner_ids(sources, SourceType.DEVICE))),
        vm_map=vm_map,
        cont_map=_by_id(_select_in(session, Container, Container.id, _owner_ids(sources, SourceType.CONTAINER))),
        # IP всех ВМ, на которые ссылаются источники, и IP «ручных» источников (отдельные строки IPAddress, владелец —
        # information_system_source) — одним запросом на все ИС, а не по запросу на ИС (N+1).
        vm_ips_by_vm=_ips_by_owner(session, OwnerType.VIRTUAL_MACHINE, vm_map.keys()),
        source_ips_by_source=_ips_by_owner(session, OwnerType.INFORMATION_SYSTEM_SOURCE, [s.id for s in sources]),
    )


def _name_in(rows: dict[str, Any], key: str | None) -> str:
    row = rows.get(key) if key else None
    return row.name if row else ""


def _distinct_owners(sources: Sequence[InformationSystemSource], source_type: str, owners: dict[str, Any]) -> list[Any]:
    """Устройства/ВМ/контейнеры источников одного вида — без повторов, в порядке источников."""
    found: list[Any] = []
    for src in sources:
        owner = owners.get(src.owner_id) if src.source_type == source_type else None
        if owner is not None and owner not in found:
            found.append(owner)
    return found


def _is_ip_addresses(sources: Sequence[InformationSystemSource], vms: Sequence[VirtualMachine], ln: _InformationSystemLinks) -> list[str]:
    """Тот же набор, что в столбце «IP-адреса» листа 1 регламентного отчёта (reporting._is_row_values): адреса ручных
    источников, затем адреса ВМ (последние — с префиксом); без пустых и повторов."""
    ips = [x.ip_address for src in sources for x in ln.source_ips_by_source.get(src.id, [])]
    ips += [_ip_text(x) for v in vms for x in ln.vm_ips_by_vm.get(v.id, [])]
    return list(dict.fromkeys(x for x in ips if x))


def _enrich_single_information_system(obj: InformationSystem, ln: _InformationSystemLinks) -> dict[str, Any]:
    """Читаемые summary-поля одной ИС из унифицированных source-записей (InformationSystemSource — единственный механизм
    этой связи, см. models.py)."""
    sources = ln.source_by_is.get(obj.id, [])
    devices = _distinct_owners(sources, SourceType.DEVICE, ln.device_map)
    vms = _distinct_owners(sources, SourceType.VM, ln.vm_map)
    containers = _distinct_owners(sources, SourceType.CONTAINER, ln.cont_map)
    ip_addresses = _is_ip_addresses(sources, vms, ln)
    return {
        **serialize(obj),
        "support_organization_name": _name_in(ln.support_map, obj.support_organization_id),
        "support_method_name": _name_in(ln.method_map, obj.support_method_id),
        "placement_assets_summary": _unique_joined(ln.placement_map[x.placement_asset_id].name for x in ln.placement_by_is.get(obj.id, []) if x.placement_asset_id in ln.placement_map),
        "departments_summary": _unique_joined(ln.dep_map[x.department_id].name for x in ln.dep_by_is.get(obj.id, []) if x.department_id in ln.dep_map),
        # Список — для экрана (по строке на адрес), строка — для отчётов и конструктора.
        "ip_addresses": ip_addresses,
        "ip_addresses_summary": "; ".join(ip_addresses),
        # protocol_catalog_id обязателен для ISProtocol (NOT NULL, миграция b7f2c1e5a904): свободного текста без справочника не бывает.
        "protocols_summary": _unique_joined(f"{ln.proto_map[x.protocol_catalog_id].protocol_type}/{ln.proto_map[x.protocol_catalog_id].port}" for x in ln.proto_by_is.get(obj.id, []) if x.protocol_catalog_id in ln.proto_map),
        "physical_devices_summary": _unique_joined(device_label(d, fallback=d.id) for d in devices),
        "vms_summary": _unique_joined(v.name or v.id for v in vms),
        "containers_summary": _unique_joined(c.name or c.id for c in containers),
    }


def enrich_information_systems(items: Sequence[InformationSystem], session: Session) -> list[dict[str, Any]]:
    if not items:
        return []
    ln = _load_information_systems_links(items, session)
    return [_enrich_single_information_system(obj, ln) for obj in items]
