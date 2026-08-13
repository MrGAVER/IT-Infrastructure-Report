from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Optional
from collections import defaultdict, Counter
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import (
    Building, Connection, ConnectionType, Container, CryptoProtectionMeans, Department,
    DeviceInterface, DeviceModel, DeviceSoftware, DeviceType, EmbeddedOperatingSystem,
    ISContainer, ISDepartment, ISDevice, ISIP, ISPlacementAsset, ISProtocol, ISVM,
    InformationSystem, InformationSystemSource, InterfaceIP, InterfaceType, InterfaceVLAN,
    Manufacturer, OpenPort, OperatingSystem, PhysicalDevice, PhysicalDeviceVLAN, PlacementAsset,
    ProtocolPortCatalog, Rack, Room, SoftwareAsset, SupportMethod, SupportOrganization, VLAN,
    VMIP, VMSoftware, VirtualMachine,
)
from .services.computed import ip_label, device_management_ports_and_ips

HEADERS1 = [
"№","Наименование информационной системы (подситемы/информационного ресурса)","Общее описание информационной системы (подситемы/информационного ресурса)","Назначение использования информационной системы (подсистемы/информационного ресурса) для ИС Организация","Работники, группы работников или подразделения, которые используют в своей работе информационную систему (подсистему/информационный ресурс)","Локализация информационной системы (подсистемы/информационного ресурса)","Оборудование ООО \"Организация\", на котором размещается информационная ситема (подсистема/информационный ресурс), а также прикладное программное обеспечение или интерфейс взаимодействия с внешней информационной системой.","Протокол передачи данных, по которому осуществляется взаимодействие информационной системы (подсистемы/информационного ресурса), как внутри ИС Организация, так и при организации внешнего взаимодейтсвия, в том числе с внешними информационными системами","IP адрес , по которому осуществляется взаимодействие информационной системы (подсистемы/информационного ресурса), как внутри ИС Организация, так и при организации внешнего взаимодейтсвия, в том числе с внешними информационными системами","Применение сертифицированных программных и/или программно-аппаратных средств криптографической защиты информации, применяемых при осуществлении внешнего взаимодействия, в том числе с внешними информационными системами.","Признак получения событий в SIEM","Наименование организации, информационная система которой осуществляет взаимодействие и (или) обеспечивает техническую поддержку","Способ оказания технической поддержки","Описание процесса функционирования ИС, особенности организации направления потоков для обеспечения функционирования ИС","Название физического сервера (ПК, выполняющего роль сервера), на котором установлена информационная система (подсистема/информационный ресурс) или установлена виртуальная машина (контейнер), обеспечивающая (ий) функционирование данной информационной системы (подсистемы/информационного ресурса)","IP-адрес физического сервера, на котором установлена информационная система (подсистема/информационный ресурс)","Наименование виртуальной машины или контейнера, обеспечивающая (ий) функционирование данной информационной системы (подсистемы/информационного ресурса)","IP-адрес виртуальной машины (контейнера), обеспечивающая (ий) функционирование данной информационной системы (подсистемы/информационного ресурса)"]
HEADERS2 = [
"№","Наименование производителя","Модель устройства","Серийный номер устройства","Системное имя устройства, если устройство является управлемым","Версия операционной системы физического устройства","Номер порта управления устройством, если устройство является управлемым","IP-адрес управления устройством","Признак получения событий в SIEM","Количество физических портов устройства","Адрес расположения устройства","Наименование здания (условное или официальное), в котором располагается устройство","Помещение, в котором размещается телекоммуникационный шкаф, в котором размещается устройство или место размещения самого устройства в здании"]
HEADERS3 = [
"№","Вид физического устройства: серверы, сетевое оборудование, средства защиты информации, рабочий ПК системного/сетевого администратора и рабочий ПК администратора безопасности, за исключением ПК пользователей","Серийный номер устройства","Системное имя устройства, если устройство является управлемым","Наименование и версия операционной системы физического устройства","Номер физического или логического порта","IP-адрес порта физического устройства ХХХ.ХХХ.ХХХ.ХХХ/24","Перечень открытых портов транспортного уровня с указанием соответствующим им технологий и (или) протоколов","Протокол (технология)","Идентификаторы виртуальных локальных вычислительных сетей (VLAN ID)","Названия виртуальных локальных вычислительных сетей (VLAN Name)","Физические линии связи с указанием их типа (витая пара, волоконно-оптический кабель и др.)","Сведения о назначении линий связи (передача данных или управление активами информационной системы, средствами защиты информации)","Вид соседнего подключенного физического устройства, в соответствии с каждым физическим портом серверы, сетевое оборудование, средства защиты информации, рабочий ПК сиcтемного/сетевого администратора и   рабочий ПК, а также ПК пользователей","Серийный номер соседнего физического устройства, в том числе ПК пользователей","Системное имя соседнего физического устройства, если устройство является управлемым, в том числе ПК пользователей","Наименование и версия операционной системы соседнего физического устройства","IP-адрес порта соседнего физического устройства ХХХ.ХХХ.ХХХ.ХХХ/24"]
HEADERS4 = [
"Название виртуальной машины","Наименование и версия операционной системы виртуальной машины","Наименование контейнера","Наименование физического устройства , на котором установлена виртуальная машина, согласно его системному имени","Наименование среды виртуализации и ее версия","Целевое использование (функциональное назначение ) виртуальной машины/контейнера","IP-адрес виртуальной машины/контейнера","Перечень открытых портов транспортного уровня с указанием соответствующим им IP-адресов технологий и (или) протоколов","IP-адрес администрирования виртуальной машины/контейнера","Какие программные активы развернуты: 1С, Web-сервер, файловый, AD и т.п."]

def join_values(values):
    result=[]
    for value in values:
        if value is None: continue
        value=str(value).strip()
        if value and value not in result: result.append(value)
    return "; ".join(result)

def os_label(obj):
    return join_values([getattr(obj,"name",None), getattr(obj,"version",None)]) if obj else ""

def device_label(d):
    return (d.system_name or d.serial_number) if d else ""

def interface_port_count_label(ifaces, interface_types):
    """Return a compact count grouped by interface type, e.g. 10 RJ45 + 4 SFP."""
    counts = Counter()
    for iface in ifaces:
        it = interface_types.get(iface.interface_type_id)
        name = it.name if it else "Без типа"
        counts[name] += 1
    return " + ".join(f"{count} {name}" for name, count in sorted(counts.items(), key=lambda x: x[0].casefold()))

def setup_sheet(ws, headers):
    ws.append(headers)
    for cell in ws[1]:
        cell.font=Font(bold=True)
        cell.alignment=Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes="A2"

def finalize_sheet(ws):
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment=Alignment(vertical="top", wrap_text=True)
    for col in range(1, ws.max_column+1):
        max_len=12
        for cell in ws.iter_rows(min_col=col, max_col=col, values_only=True):
            max_len=max(max_len, min(len(str(cell[0] or "")), 55))
        ws.column_dimensions[get_column_letter(col)].width=min(max_len+2, 55)
    ws.row_dimensions[1].height=72
    if ws.max_row > 1: ws.auto_filter.ref=ws.dimensions

def build_report(session: Session, report_dir: Path, only_is: Optional[str] = None) -> Path:
    wb=Workbook()
    ws1=wb.active; ws1.title="Перечень ИС"; setup_sheet(ws1,HEADERS1)
    ws2=wb.create_sheet("Инвентаризац. физ. устройств ИС"); setup_sheet(ws2,HEADERS2)
    ws3=wb.create_sheet("Организация подключений"); setup_sheet(ws3,HEADERS3)
    ws4=wb.create_sheet("Организация управления ВМ"); setup_sheet(ws4,HEADERS4)

    # Load the registry in batches. This avoids the old N+1 pattern and guarantees that
    # information entered in the UI is represented in the report.
    systems=session.scalars((select(InformationSystem).where(InformationSystem.id==only_is) if only_is else select(InformationSystem)).order_by(InformationSystem.name)).all()
    departments=session.scalars(select(Department)).all(); dep_map={x.id:x for x in departments}
    support_orgs=session.scalars(select(SupportOrganization)).all(); support_map={x.id:x for x in support_orgs}
    devices=session.scalars(select(PhysicalDevice).order_by(PhysicalDevice.system_name,PhysicalDevice.serial_number)).all(); device_map={x.id:x for x in devices}
    device_types={x.id:x for x in session.scalars(select(DeviceType)).all()}
    manufacturers={x.id:x for x in session.scalars(select(Manufacturer)).all()}
    models={x.id:x for x in session.scalars(select(DeviceModel)).all()}
    buildings={x.id:x for x in session.scalars(select(Building)).all()}
    rooms={x.id:x for x in session.scalars(select(Room)).all()}
    racks={x.id:x for x in session.scalars(select(Rack)).all()}
    operating_systems={x.id:x for x in session.scalars(select(OperatingSystem)).all()}
    embedded_os={x.id:x for x in session.scalars(select(EmbeddedOperatingSystem)).all()}
    support_methods={x.id:x for x in session.scalars(select(SupportMethod)).all()}
    crypto_means={x.id:x for x in session.scalars(select(CryptoProtectionMeans)).all()}
    placement_assets={x.id:x for x in session.scalars(select(PlacementAsset)).all()}
    placement_by_is=defaultdict(list)
    for x in session.scalars(select(ISPlacementAsset)).all(): placement_by_is[x.information_system_id].append(x)
    interface_types={x.id:x for x in session.scalars(select(InterfaceType)).all()}
    interfaces=session.scalars(select(DeviceInterface).order_by(DeviceInterface.name)).all(); iface_map={x.id:x for x in interfaces}
    interface_ips=session.scalars(select(InterfaceIP).order_by(InterfaceIP.ip_address)).all()
    ips_by_iface=defaultdict(list)
    for x in interface_ips: ips_by_iface[x.interface_id].append(x)
    ifaces_by_device=defaultdict(list)
    for x in interfaces: ifaces_by_device[x.physical_device_id].append(x)
    vmips=session.scalars(select(VMIP).order_by(VMIP.ip_address)).all(); vmips_by_vm=defaultdict(list)
    for x in vmips: vmips_by_vm[x.virtual_machine_id].append(x)
    vms=session.scalars(select(VirtualMachine).order_by(VirtualMachine.name)).all(); vm_map={x.id:x for x in vms}
    containers=session.scalars(select(Container)).all(); container_map={x.id:x for x in containers}
    protocols=session.scalars(select(ProtocolPortCatalog)).all(); protocol_catalog={x.id:x for x in protocols}
    is_deps=session.scalars(select(ISDepartment)).all(); is_ips=session.scalars(select(ISIP)).all(); is_protocols=session.scalars(select(ISProtocol)).all(); is_devices=session.scalars(select(ISDevice)).all(); is_vms=session.scalars(select(ISVM)).all(); is_containers=session.scalars(select(ISContainer)).all(); is_sources=session.scalars(select(InformationSystemSource)).all()
    conns=session.scalars(select(Connection).order_by(Connection.created_at)).all(); connection_types={x.id:x for x in session.scalars(select(ConnectionType)).all()}
    open_ports=session.scalars(select(OpenPort)).all(); open_ports_by_owner=defaultdict(list)
    for x in open_ports: open_ports_by_owner[(x.owner_type,x.owner_id)].append(x)
    vlans=session.scalars(select(VLAN)).all(); vlan_map={x.id:x for x in vlans}; iface_vlans=session.scalars(select(InterfaceVLAN)).all(); vlan_by_iface=defaultdict(list)
    device_vlan_rows=session.scalars(select(PhysicalDeviceVLAN)).all(); device_vlan_by_device=defaultdict(list)
    for x in device_vlan_rows: device_vlan_by_device[x.physical_device_id].append(x)
    for x in iface_vlans: vlan_by_iface[x.interface_id].append(vlan_map.get(x.vlan_id))
    vm_software=session.scalars(select(VMSoftware)).all(); software={x.id:x for x in session.scalars(select(SoftwareAsset)).all()}; software_by_vm=defaultdict(list)
    for link in vm_software:
        if link.software_asset_id in software: software_by_vm[link.virtual_machine_id].append(software[link.software_asset_id])
    device_software=session.scalars(select(DeviceSoftware)).all(); software_by_device=defaultdict(list)
    for link in device_software:
        if link.software_asset_id in software: software_by_device[link.physical_device_id].append(software[link.software_asset_id])
    dep_by_is=defaultdict(list); ip_by_is=defaultdict(list); protocol_by_is=defaultdict(list); device_by_is=defaultdict(list); vm_by_is=defaultdict(list); container_by_is=defaultdict(list); source_by_is=defaultdict(list)
    for x in is_deps: dep_by_is[x.information_system_id].append(x)
    for x in is_ips: ip_by_is[x.information_system_id].append(x)
    for x in is_protocols: protocol_by_is[x.information_system_id].append(x)
    for x in is_devices: device_by_is[x.information_system_id].append(x)
    for x in is_vms: vm_by_is[x.information_system_id].append(x)
    for x in is_containers: container_by_is[x.information_system_id].append(x)
    for x in is_sources: source_by_is[x.information_system_id].append(x)

    # Sheet 1: all linked sources plus protocol/IP details.
    for n,obj in enumerate(systems,1):
        source_rows=source_by_is[obj.id]
        if source_rows:
            # InformationSystemSource is the current, authoritative representation once an IS has
            # been saved through the information-system form at least once.
            linked_devices=[]; linked_vms=[]; linked_containers=[]
            for src in source_rows:
                if src.source_type=='device' and src.physical_device_id in device_map:
                    d=device_map[src.physical_device_id]
                    if d not in linked_devices: linked_devices.append(d)
                elif src.source_type=='vm' and src.virtual_machine_id in vm_map:
                    v=vm_map[src.virtual_machine_id]
                    if v not in linked_vms: linked_vms.append(v)
                elif src.source_type=='container' and src.container_id in container_map:
                    c=container_map[src.container_id]
                    if c not in linked_containers: linked_containers.append(c)
        else:
            # Historical data predating the unified source model (IS never re-saved through the
            # current form) — fall back to the legacy link tables, same as the form itself does.
            linked_devices=[device_map[x.physical_device_id] for x in device_by_is[obj.id] if x.physical_device_id in device_map]
            linked_vms=[vm_map[x.virtual_machine_id] for x in vm_by_is[obj.id] if x.virtual_machine_id in vm_map]
            linked_containers=[container_map[x.container_id] for x in container_by_is[obj.id] if x.container_id in container_map]
        equipment=[]
        for d in linked_devices:
            equipment.append(device_label(d))
            equipment += [f"ПО: {s.name}" for s in software_by_device.get(d.id,[])]
        for v in linked_vms: equipment.append(f"VM: {v.name}")
        for c in linked_containers: equipment.append(f"Контейнер: {c.name}")
        equipment += [placement_assets[x.placement_asset_id].name for x in placement_by_is[obj.id] if x.placement_asset_id in placement_assets]
        protocols_text=[]
        for p in protocol_by_is[obj.id]:
            cat=protocol_catalog.get(p.protocol_catalog_id)
            proto=cat.protocol_type if cat else p.protocol
            port=cat.port if cat else p.port
            desc=cat.description if cat else p.description
            protocols_text.append(join_values([f"{proto}/{port}" if port else proto, desc]))
        physical_names=linked_devices[:]
        # Add hosts of linked VMs and their management IPs.
        for v in linked_vms:
            if v.physical_device_id in device_map and device_map[v.physical_device_id] not in physical_names: physical_names.append(device_map[v.physical_device_id])
        physical_ips=[]
        for d in physical_names:
            physical_ips += [ip_label(ip) for iface in ifaces_by_device.get(d.id,[]) if iface.is_management for ip in ips_by_iface.get(iface.id,[])]
        vm_names=[v.name for v in linked_vms] + [c.name for c in linked_containers]
        vm_ips=[ip_label(ip) for v in linked_vms for ip in vmips_by_vm.get(v.id,[])] + [c.management_ip for c in linked_containers if c.management_ip]
        departments_text=join_values([dep_map[x.department_id].name for x in dep_by_is[obj.id] if x.department_id in dep_map])
        legacy_ips=[x.ip_address for x in ip_by_is[obj.id]] if not source_rows else []
        ips_text=join_values(legacy_ips + [x.ip_address for x in source_rows if x.ip_address] + vm_ips)
        support=support_map.get(obj.support_organization_id)
        support_method_name=support_methods[obj.support_method_id].name if obj.support_method_id in support_methods else ""
        crypto_mean=crypto_means.get(obj.crypto_protection_description_id)
        crypto_text=join_values(["Да" if obj.crypto_protection_enabled else "Нет", crypto_mean.name if crypto_mean else None])
        ws1.append([n,obj.name,obj.description or "",obj.purpose or "",departments_text,obj.localization or "",join_values(equipment),join_values(protocols_text),ips_text,crypto_text,"Да" if obj.siem_enabled else "Нет",support.name if support else "",support_method_name,obj.process_description or "",join_values([device_label(d) for d in physical_names]),join_values(physical_ips),join_values(vm_names),join_values(vm_ips)])

    # Sheet 2: one row per physical device.
    for n,d in enumerate(devices,1):
        all_ifaces=ifaces_by_device.get(d.id,[])
        mgmt_ifaces=[i for i in all_ifaces if i.is_management]
        mgmt_vlan=[x for x in device_vlan_by_device.get(d.id,[]) if x.is_management]
        mgmt_port_names,mgmt_ip_values=device_management_ports_and_ips(mgmt_ifaces,ips_by_iface,mgmt_vlan,vlan_map,vlan_label_with_name=False)
        mgmt_ports=join_values(mgmt_port_names)
        mgmt_ips=join_values(mgmt_ip_values)
        serial=d.serial_number or ""; sysname=d.system_name or ""
        os_names=os_label(embedded_os.get(d.embedded_os_id))
        manufacturer_names=manufacturers.get(d.manufacturer_id).name if manufacturers.get(d.manufacturer_id) else ''
        model_names=models.get(d.model_id).model if models.get(d.model_id) else ''
        addresses=buildings.get(d.building_id).address if buildings.get(d.building_id) else ''
        building_names=buildings.get(d.building_id).name if buildings.get(d.building_id) else ''
        room_names=rooms.get(d.room_id).name if rooms.get(d.room_id) else ''
        ws2.append([n,manufacturer_names,model_names,serial,sysname,os_names,mgmt_ports,mgmt_ips,"Да" if d.siem_enabled else "Нет",interface_port_count_label(all_ifaces, interface_types),addresses,building_names,room_names])

    # Sheet 3: every physical port must appear — connected ports show both ends of the link
    # (own device + neighbor), disconnected ports still get a row of their own, though ports on the
    # same device with no connection that share an IP signature (including "no IP") may be grouped
    # into a single row rather than one row each.
    _port_open_info_cache={}
    def _port_open_info(device_id):
        if device_id in _port_open_info_cache: return _port_open_info_cache[device_id]
        ports=open_ports_by_owner.get(('physical_device',device_id),[])
        open_text=join_values([join_values([f"{p.transport_protocol}/{p.port}" if p.port else p.transport_protocol,p.protocol,p.description]) for p in ports])
        proto_text=join_values([p.protocol for p in ports])
        _port_open_info_cache[device_id]=(open_text,proto_text)
        return open_text,proto_text

    def _device_management_ips(device):
        """A device's management IPs: physical management interfaces plus VLAN-based management (incl. VLAN)."""
        mgmt_ifaces=[i for i in ifaces_by_device.get(device.id,[]) if i.is_management]
        mgmt_vlan=[x for x in device_vlan_by_device.get(device.id,[]) if x.is_management]
        _,ip_values=device_management_ports_and_ips(mgmt_ifaces,ips_by_iface,mgmt_vlan,vlan_map)
        return ip_values

    def _link_purpose_label(iface):
        mgmt=bool(iface.is_management); data=bool(iface.is_data_transfer)
        if mgmt and data: return "Управление активами, передача данных"
        if mgmt: return "Управление активами"
        if data: return "Передача данных"
        return "-"

    def _conn_row(own_iface, own_device, neighbor_iface, neighbor_device, c, ct):
        own_ips=join_values([ip_label(x) for x in ips_by_iface.get(own_iface.id,[])])
        neighbor_mgmt_ips=_device_management_ips(neighbor_device)
        neighbor_ips=join_values(neighbor_mgmt_ips if neighbor_mgmt_ips else [ip_label(x) for x in ips_by_iface.get(neighbor_iface.id,[])])
        open_text,proto_text=_port_open_info(own_device.id)
        own_vlans=[v for v in vlan_by_iface.get(own_iface.id,[]) if v]
        neighbor_vlans=[v for v in vlan_by_iface.get(neighbor_iface.id,[]) if v]
        vlan_rows=own_vlans if own_vlans else neighbor_vlans
        return [0,device_types.get(own_device.device_type_id).name if device_types.get(own_device.device_type_id) else "",own_device.serial_number,own_device.system_name or "",os_label(embedded_os.get(own_device.embedded_os_id)),own_iface.name,own_ips or "не назначен",open_text,proto_text,join_values([str(v.vlan_id) for v in vlan_rows]),join_values([v.name for v in vlan_rows]),ct.name if ct else "",_link_purpose_label(own_iface),device_types.get(neighbor_device.device_type_id).name if device_types.get(neighbor_device.device_type_id) else "",neighbor_device.serial_number,neighbor_device.system_name or "",os_label(embedded_os.get(neighbor_device.embedded_os_id)),neighbor_ips or "не назначен"]

    def _disconnected_row(own_device, iface_group):
        own_ips=join_values([ip_label(x) for i in iface_group for x in ips_by_iface.get(i.id,[])])
        open_text,proto_text=_port_open_info(own_device.id)
        own_vlans=[v for i in iface_group for v in vlan_by_iface.get(i.id,[]) if v]
        purposes=join_values([_link_purpose_label(i) for i in iface_group if _link_purpose_label(i)!="-"]) or "-"
        return [0,device_types.get(own_device.device_type_id).name if device_types.get(own_device.device_type_id) else "",own_device.serial_number,own_device.system_name or "",os_label(embedded_os.get(own_device.embedded_os_id)),join_values([i.name for i in iface_group]),own_ips or "не назначен",open_text,proto_text,join_values([str(v.vlan_id) for v in own_vlans]),join_values([v.name for v in own_vlans]),"",purposes,"","","","",""]

    pending_rows=[]
    connected_iface_ids=set()
    for c in conns:
        src=iface_map.get(c.source_interface_id); dst=iface_map.get(c.destination_interface_id)
        if not src or not dst: continue
        sd=device_map.get(src.physical_device_id); dd=device_map.get(dst.physical_device_id)
        if not sd or not dd: continue
        ct=connection_types.get(c.connection_type_id)
        connected_iface_ids.add(src.id); connected_iface_ids.add(dst.id)
        pending_rows.append((sd, _conn_row(src, sd, dst, dd, c, ct)))
        pending_rows.append((dd, _conn_row(dst, dd, src, sd, c, ct)))

    for d in devices:
        own_ifaces=[i for i in ifaces_by_device.get(d.id,[]) if i.id not in connected_iface_ids]
        if not own_ifaces: continue
        groups=defaultdict(list)
        for i in own_ifaces:
            key=tuple(sorted(ip_label(x) for x in ips_by_iface.get(i.id,[])))
            groups[key].append(i)
        for iface_group in groups.values():
            pending_rows.append((d, _disconnected_row(d, iface_group)))

    # Group consecutively by "own" device (stable sort preserves the connected-then-disconnected,
    # per-connection order within each device) instead of interleaving devices row by row.
    device_order={d.id:idx for idx,d in enumerate(devices)}
    pending_rows.sort(key=lambda pair: device_order.get(pair[0].id, len(devices)))

    for i,(_,row) in enumerate(pending_rows,1):
        row=[cell if cell not in (None,"") else "-" for cell in row]
        row[0]=i
        ws3.append(row)

    # Sheet 4: VM host/hypervisor comes from the physical host's OS; admin IP is all management VM IPs.
    for v in vms:
        host=device_map.get(v.physical_device_id); hyp=operating_systems.get(host.operating_system_id) if host and host.operating_system_id else operating_systems.get(v.hypervisor_os_id)
        ips=vmips_by_vm.get(v.id,[]); containers_for_vm=[c for c in containers if c.virtual_machine_id==v.id]
        openp=open_ports_by_owner.get(('virtual_machine',v.id),[])
        admin_ips=join_values([ip_label(x) for x in ips if x.is_management])
        ws4.append([v.name,os_label(operating_systems.get(v.operating_system_id)),join_values([c.name for c in containers_for_vm]),device_label(host),os_label(hyp),v.purpose or "",join_values([ip_label(x) for x in ips]),join_values([join_values([f"{p.transport_protocol}/{p.port}" if p.port else p.transport_protocol,p.protocol,p.description]) for p in openp]),admin_ips,join_values([s.name for s in software_by_vm.get(v.id,[])])])

    for ws in wb.worksheets: finalize_sheet(ws)
    report_dir.mkdir(parents=True,exist_ok=True)
    path=report_dir/f"Инвентаризация_ИС_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"
    wb.save(path)
    return path
