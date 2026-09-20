from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
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
    ISDepartment, ISPlacementAsset, ISProtocol,
    InformationSystem, InformationSystemSource, InterfaceIP, InterfaceType, InterfaceVLAN,
    Manufacturer, OpenPort, OperatingSystem, PhysicalDevice, PhysicalDeviceVLAN, PlacementAsset,
    ProtocolPortCatalog, Room, SoftwareAsset, StructuralUnit, SupportMethod, SupportOrganization, VLAN,
    VMIP, VMSoftware, VirtualMachine,
)
from .services.computed import ip_label, device_management_ports_and_ips, local_timestamp_suffix
from .services.excel_safety import excel_safe_row

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
    """Полное наименование версии ОС/среды: "Имя Версия" без разделителя ";" между ними.

    join_values() рассчитан на список из произвольного числа элементов и разделяет их
    через "; " — уместно для перечней (VLAN, IP и т.п.), но для пары "имя + версия"
    даёт нечитаемое "Huawei iBMC; 6.73" вместо "Huawei iBMC 6.73". Здесь имя и версия
    всегда ровно два компонента одного значения, поэтому склеиваются пробелом.
    """
    if not obj:
        return ""
    name = (getattr(obj, "name", None) or "").strip()
    version = (getattr(obj, "version", None) or "").strip()
    if name and version:
        return f"{name} {version}"
    return name or version

def device_label(d):
    return (d.system_name or d.serial_number) if d else ""

def _open_port_label(p, d: SimpleNamespace) -> str:
    """Текст одного открытого порта для отчёта: 'TCP/443 HTTPS Описание порта'. port/protocol_type
    больше не колонки OpenPort (см. models.py, миграция b7f2c1e5a904) — резолвятся join'ом к
    protocol_port_catalogs по protocol_catalog_id при каждом построении отчёта, поэтому правка
    записи справочника отражается на уже созданных портах сразу. Общий хелпер для Листа 3
    (_port_open_info в _connection_row_values_list) и Листа 4 (_vm_row_values), чтобы формат строки
    не разъезжался между ними."""
    cat = d.protocol_catalog.get(p.protocol_catalog_id)
    port = cat.port if cat else None
    proto = cat.protocol_type if cat else None
    return join_values([f"{p.transport_protocol}/{port}" if port else p.transport_protocol, proto, p.description])

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

def _expand_structural_unit_ids(structural_units: dict, selected_ids: list) -> set:
    """Расширяет выбранные ID структурных единиц их потомками (по parent_id, тот же паттерн
    иерархии, что и у Department) — выбор родительской единицы автоматически захватывает все
    вложенные, без необходимости отмечать каждую по отдельности в UI."""
    children_by_parent = defaultdict(list)
    for u in structural_units.values():
        if u.parent_id:
            children_by_parent[u.parent_id].append(u.id)
    selected = {x for x in selected_ids if x in structural_units}
    stack = list(selected)
    while stack:
        uid = stack.pop()
        for child_id in children_by_parent.get(uid, []):
            if child_id not in selected:
                selected.add(child_id)
                stack.append(child_id)
    return selected


def _allowed_device_ids_for_structural_units(d: SimpleNamespace, structural_unit_ids: Optional[list]) -> Optional[set]:
    """None — фильтр не активен, разрешены все устройства (текущее поведение без выбора структурных
    единиц). Иначе — набор id физических устройств, чьё здание размещения (PhysicalDevice.building_id
    -> Building.structural_unit_id) относится к одной из выбранных структурных единиц или их
    потомков. Работает целиком на уже загруженных в d данных (без доп. запросов к БД) — d.devices
    в момент вызова ещё полный (фильтрация списков применяется ПОСЛЕ, см. конец _load_report_data),
    d.buildings/d.structural_units загружены полностью."""
    if not structural_unit_ids:
        return None
    expanded = _expand_structural_unit_ids(d.structural_units, structural_unit_ids)
    allowed_building_ids = {b.id for b in d.buildings.values() if b.structural_unit_id in expanded}
    return {dev.id for dev in d.devices if dev.building_id in allowed_building_ids}


def _is_source_links(obj, d: SimpleNamespace) -> tuple:
    """Возвращает (linked_devices, linked_vms, linked_containers) для одной ИС из унифицированных
    source-записей (InformationSystemSource — единственный механизм этой связи с миграции
    b7f2c1e5a904, см. models.py). Вынесено из _is_row_values(), чтобы эту же логику мог
    переиспользовать _is_related_device_ids() (фильтр листа 'Перечень ИС' по структурной единице)
    без дублирования и риска разойтись."""
    linked_devices=[]; linked_vms=[]; linked_containers=[]
    for src in d.source_by_is[obj.id]:
        if src.source_type=='device' and src.physical_device_id in d.device_map:
            dev=d.device_map[src.physical_device_id]
            if dev not in linked_devices: linked_devices.append(dev)
        elif src.source_type=='vm' and src.virtual_machine_id in d.vm_map:
            v=d.vm_map[src.virtual_machine_id]
            if v not in linked_vms: linked_vms.append(v)
        elif src.source_type=='container' and src.container_id in d.container_map:
            c=d.container_map[src.container_id]
            if c not in linked_containers: linked_containers.append(c)
    return linked_devices, linked_vms, linked_containers


def _is_related_device_ids(obj, d: SimpleNamespace) -> set:
    """Physical device ids, связанные с ИС напрямую или как хост её ВМ/контейнера — используется
    для фильтрации листа 'Перечень ИС' по структурной единице: ИС попадает в отчёт, только если
    хотя бы один из этих id входит в allowed_device_ids (см. _allowed_device_ids_for_structural_units)."""
    linked_devices, linked_vms, linked_containers = _is_source_links(obj, d)
    ids = {dev.id for dev in linked_devices}
    for v in linked_vms:
        if v.physical_device_id: ids.add(v.physical_device_id)
    for c in linked_containers:
        if c.physical_device_id:
            ids.add(c.physical_device_id)
        elif c.virtual_machine_id and c.virtual_machine_id in d.vm_map:
            host_vm = d.vm_map[c.virtual_machine_id]
            if host_vm.physical_device_id: ids.add(host_vm.physical_device_id)
    return ids


def _load_report_data(session: Session, only_is: Optional[str], structural_unit_ids: Optional[list] = None) -> SimpleNamespace:
    """Batch-load the whole registry needed to build all 4 sheets. Kept as one function (rather
    than one per sheet) because several lookups are shared across sheets (device_map, ifaces_by_device,
    embedded_os, etc.) and loading them once avoids redundant queries.

    structural_unit_ids — необязательный фильтр по структурным единицам (см.
    _allowed_device_ids_for_structural_units): если задан, d.devices/d.vms/d.systems в конце функции
    сужаются до записей, относящихся к выбранным единицам, а d.allowed_device_ids хранит набор
    допустимых id устройств (или None, если фильтр не активен) для листа 'Организация подключений'
    (см. _connection_row_values_list). d.device_map/d.vm_map/d.container_map остаются ПОЛНЫМИ
    (не сужаются) — они нужны для корректного поиска соседних устройств/хостов независимо от фильтра."""
    d = SimpleNamespace()
    d.systems=session.scalars((select(InformationSystem).where(InformationSystem.id==only_is) if only_is else select(InformationSystem)).order_by(InformationSystem.name)).all()
    d.departments=session.scalars(select(Department)).all(); d.dep_map={x.id:x for x in d.departments}
    d.support_orgs=session.scalars(select(SupportOrganization)).all(); d.support_map={x.id:x for x in d.support_orgs}
    d.devices=session.scalars(select(PhysicalDevice).order_by(PhysicalDevice.system_name,PhysicalDevice.serial_number)).all(); d.device_map={x.id:x for x in d.devices}
    d.device_types={x.id:x for x in session.scalars(select(DeviceType)).all()}
    d.manufacturers={x.id:x for x in session.scalars(select(Manufacturer)).all()}
    d.models={x.id:x for x in session.scalars(select(DeviceModel)).all()}
    d.buildings={x.id:x for x in session.scalars(select(Building)).all()}
    d.rooms={x.id:x for x in session.scalars(select(Room)).all()}
    d.structural_units={x.id:x for x in session.scalars(select(StructuralUnit)).all()}
    d.operating_systems={x.id:x for x in session.scalars(select(OperatingSystem)).all()}
    d.embedded_os={x.id:x for x in session.scalars(select(EmbeddedOperatingSystem)).all()}
    d.support_methods={x.id:x for x in session.scalars(select(SupportMethod)).all()}
    d.crypto_means={x.id:x for x in session.scalars(select(CryptoProtectionMeans)).all()}
    d.placement_assets={x.id:x for x in session.scalars(select(PlacementAsset)).all()}
    d.placement_by_is=defaultdict(list)
    for x in session.scalars(select(ISPlacementAsset)).all(): d.placement_by_is[x.information_system_id].append(x)
    d.interface_types={x.id:x for x in session.scalars(select(InterfaceType)).all()}
    d.interfaces=session.scalars(select(DeviceInterface).order_by(DeviceInterface.name)).all(); d.iface_map={x.id:x for x in d.interfaces}
    d.interface_ips=session.scalars(select(InterfaceIP).order_by(InterfaceIP.ip_address)).all()
    d.ips_by_iface=defaultdict(list)
    for x in d.interface_ips: d.ips_by_iface[x.interface_id].append(x)
    d.ifaces_by_device=defaultdict(list)
    for x in d.interfaces: d.ifaces_by_device[x.physical_device_id].append(x)
    d.vmips=session.scalars(select(VMIP).order_by(VMIP.ip_address)).all(); d.vmips_by_vm=defaultdict(list)
    for x in d.vmips: d.vmips_by_vm[x.virtual_machine_id].append(x)
    d.vms=session.scalars(select(VirtualMachine).order_by(VirtualMachine.name)).all(); d.vm_map={x.id:x for x in d.vms}
    d.containers=session.scalars(select(Container)).all(); d.container_map={x.id:x for x in d.containers}
    d.protocols=session.scalars(select(ProtocolPortCatalog)).all(); d.protocol_catalog={x.id:x for x in d.protocols}
    d.is_deps=session.scalars(select(ISDepartment)).all(); d.is_protocols=session.scalars(select(ISProtocol)).all(); d.is_sources=session.scalars(select(InformationSystemSource)).all()
    d.conns=session.scalars(select(Connection).order_by(Connection.created_at)).all(); d.connection_types={x.id:x for x in session.scalars(select(ConnectionType)).all()}
    d.open_ports=session.scalars(select(OpenPort)).all(); d.open_ports_by_owner=defaultdict(list)
    for x in d.open_ports: d.open_ports_by_owner[(x.owner_type,x.owner_id)].append(x)
    d.vlans=session.scalars(select(VLAN)).all(); d.vlan_map={x.id:x for x in d.vlans}; d.iface_vlans=session.scalars(select(InterfaceVLAN)).all(); d.vlan_by_iface=defaultdict(list)
    d.device_vlan_rows=session.scalars(select(PhysicalDeviceVLAN)).all(); d.device_vlan_by_device=defaultdict(list)
    for x in d.device_vlan_rows: d.device_vlan_by_device[x.physical_device_id].append(x)
    for x in d.iface_vlans: d.vlan_by_iface[x.interface_id].append(d.vlan_map.get(x.vlan_id))
    d.vm_software=session.scalars(select(VMSoftware)).all(); d.software={x.id:x for x in session.scalars(select(SoftwareAsset)).all()}; d.software_by_vm=defaultdict(list)
    for link in d.vm_software:
        if link.software_asset_id in d.software: d.software_by_vm[link.virtual_machine_id].append(d.software[link.software_asset_id])
    d.device_software=session.scalars(select(DeviceSoftware)).all(); d.software_by_device=defaultdict(list)
    for link in d.device_software:
        if link.software_asset_id in d.software: d.software_by_device[link.physical_device_id].append(d.software[link.software_asset_id])
    d.dep_by_is=defaultdict(list); d.protocol_by_is=defaultdict(list); d.source_by_is=defaultdict(list)
    for x in d.is_deps: d.dep_by_is[x.information_system_id].append(x)
    for x in d.is_protocols: d.protocol_by_is[x.information_system_id].append(x)
    for x in d.is_sources: d.source_by_is[x.information_system_id].append(x)

    # Фильтр по структурным единицам применяется В КОНЦЕ, когда все lookup-словари (device_map/
    # vm_map/container_map/source_by_is/...) уже полностью загружены: _is_related_device_ids() и
    # поиск соседних устройств на листе 3 должны видеть ПОЛНЫЙ реестр независимо от фильтра, сужаются
    # только сами списки-перечисления (d.devices/d.vms/d.systems) и флаг d.allowed_device_ids.
    d.allowed_device_ids = _allowed_device_ids_for_structural_units(d, structural_unit_ids)
    if d.allowed_device_ids is not None:
        d.devices = [x for x in d.devices if x.id in d.allowed_device_ids]
        d.vms = [x for x in d.vms if x.physical_device_id in d.allowed_device_ids]
        d.systems = [x for x in d.systems if _is_related_device_ids(x, d) & d.allowed_device_ids]
    return d


def _is_row_values(obj, d: SimpleNamespace) -> list:
    """Значения одной строки листа 'Перечень ИС' (без №) — вынесено из _populate_sheet1, чтобы эту
    же логику мог переиспользовать конструктор отчётов (services/report_registry_rows.py) без
    дублирования: расхождение между регламентированным отчётом и его "точной" заготовкой в
    конструкторе было бы куда хуже, чем общая функция."""
    source_rows=d.source_by_is[obj.id]
    linked_devices, linked_vms, linked_containers = _is_source_links(obj, d)
    equipment=[]
    for dev in linked_devices:
        equipment.append(device_label(dev))
        equipment += [f"ПО: {s.name}" for s in d.software_by_device.get(dev.id,[])]
    for v in linked_vms: equipment.append(f"VM: {v.name}")
    for c in linked_containers: equipment.append(f"Контейнер: {c.name}")
    equipment += [d.placement_assets[x.placement_asset_id].name for x in d.placement_by_is[obj.id] if x.placement_asset_id in d.placement_assets]
    protocols_text=[]
    for p in d.protocol_by_is[obj.id]:
        cat=d.protocol_catalog.get(p.protocol_catalog_id)
        proto=cat.protocol_type if cat else ""
        port=cat.port if cat else None
        desc=join_values([cat.description if cat else None, p.description])
        protocols_text.append(join_values([f"{proto}/{port}" if port else proto, desc]))
    physical_names=linked_devices[:]
    # Add hosts of linked VMs and their management IPs.
    for v in linked_vms:
        if v.physical_device_id in d.device_map and d.device_map[v.physical_device_id] not in physical_names: physical_names.append(d.device_map[v.physical_device_id])
    physical_ips=[]
    for dev in physical_names:
        physical_ips += [ip_label(ip) for iface in d.ifaces_by_device.get(dev.id,[]) if iface.is_management for ip in d.ips_by_iface.get(iface.id,[])]
    vm_names=[v.name for v in linked_vms] + [c.name for c in linked_containers]
    vm_ips=[ip_label(ip) for v in linked_vms for ip in d.vmips_by_vm.get(v.id,[])] + [c.management_ip for c in linked_containers if c.management_ip]
    departments_text=join_values([d.dep_map[x.department_id].name for x in d.dep_by_is[obj.id] if x.department_id in d.dep_map])
    ips_text=join_values([x.ip_address for x in source_rows if x.ip_address] + vm_ips)
    support=d.support_map.get(obj.support_organization_id)
    support_method_name=d.support_methods[obj.support_method_id].name if obj.support_method_id in d.support_methods else ""
    crypto_mean=d.crypto_means.get(obj.crypto_protection_description_id)
    crypto_text=join_values(["Да" if obj.crypto_protection_enabled else "Нет", crypto_mean.name if crypto_mean else None])
    return [obj.name,obj.description or "",obj.purpose or "",departments_text,obj.localization or "",join_values(equipment),join_values(protocols_text),ips_text,crypto_text,"Да" if obj.siem_enabled else "Нет",support.name if support else "",support_method_name,obj.process_description or "",join_values([device_label(dev) for dev in physical_names]),join_values(physical_ips),join_values(vm_names),join_values(vm_ips)]


def _populate_sheet1(ws1, d: SimpleNamespace) -> None:
    """Лист 'Перечень ИС': все привязанные источники плюс детали протоколов/IP."""
    for n,obj in enumerate(d.systems,1):
        ws1.append(excel_safe_row([n, *_is_row_values(obj, d)]))


def _device_row_values(dev, d: SimpleNamespace) -> list:
    """Значения одной строки листа 'Инвентаризац. физ. устройств ИС' (без №) — см. _is_row_values
    про переиспользование в конструкторе отчётов."""
    all_ifaces=d.ifaces_by_device.get(dev.id,[])
    mgmt_ifaces=[i for i in all_ifaces if i.is_management]
    mgmt_vlan=[x for x in d.device_vlan_by_device.get(dev.id,[]) if x.is_management]
    mgmt_port_names,mgmt_ip_values=device_management_ports_and_ips(mgmt_ifaces,d.ips_by_iface,mgmt_vlan,d.vlan_map,vlan_label_with_name=False)
    mgmt_ports=join_values(mgmt_port_names)
    mgmt_ips=join_values(mgmt_ip_values)
    serial=dev.serial_number or ""; sysname=dev.system_name or ""
    os_names=os_label(d.embedded_os.get(dev.embedded_os_id))
    manufacturer_names=d.manufacturers.get(dev.manufacturer_id).name if d.manufacturers.get(dev.manufacturer_id) else ''
    model_names=d.models.get(dev.model_id).model if d.models.get(dev.model_id) else ''
    addresses=d.buildings.get(dev.building_id).address if d.buildings.get(dev.building_id) else ''
    building_names=d.buildings.get(dev.building_id).name if d.buildings.get(dev.building_id) else ''
    room_names=d.rooms.get(dev.room_id).name if d.rooms.get(dev.room_id) else ''
    return [manufacturer_names,model_names,serial,sysname,os_names,mgmt_ports,mgmt_ips,"Да" if dev.siem_enabled else "Нет",interface_port_count_label(all_ifaces, d.interface_types),addresses,building_names,room_names]


def _populate_sheet2(ws2, d: SimpleNamespace) -> None:
    """Лист 'Инвентаризац. физ. устройств ИС': одна строка на физическое устройство."""
    for n,dev in enumerate(d.devices,1):
        ws2.append(excel_safe_row([n, *_device_row_values(dev, d)]))


def _connection_row_values_list(d: SimpleNamespace) -> list:
    """Пронумерованные строки листа 'Организация подключений' (первый элемент каждой строки — №,
    как ждёт _populate_sheet3) — вынесено из неё же, см. _is_row_values про переиспользование в
    конструкторе отчётов."""
    # Every physical port must appear — connected ports show both ends of the link (own device +
    # neighbor), disconnected ports still get a row of their own, though ports on the same device
    # with no connection that share an IP signature (including "no IP") may be grouped into a
    # single row rather than one row each.
    _port_open_info_cache={}
    def _port_open_info(iface_ids):
        # п.1.4 (батч4): открытые порты теперь свойство КОНКРЕТНОГО интерфейса (порта), а не
        # всего устройства — раньше один и тот же список открытых портов устройства подставлялся
        # в КАЖДУЮ строку Листа 3 (на каждый порт), что было некорректно уже при более чем одном
        # порте на устройстве. iface_ids — кортеж id интерфейсов, формирующих одну строку отчёта
        # (обычно один, но для сгруппированных disconnected-строк — несколько, см.
        # _disconnected_row). 'physical_device'-владение (см. OwnerType в constants.py) больше не
        # читается здесь намеренно — устаревшие записи, заведённые до этого фикса на устройствах
        # с несколькими портами, неоднозначны (неизвестно, какому порту принадлежат) и не
        # переносятся автоматически, см. докстринг миграции 20260911_ports_per_interface.
        key=tuple(sorted(iface_ids))
        if key in _port_open_info_cache: return _port_open_info_cache[key]
        ports=[p for iid in iface_ids for p in d.open_ports_by_owner.get(('device_interface',iid),[])]
        open_text=join_values([_open_port_label(p, d) for p in ports])
        proto_text=join_values([d.protocol_catalog[p.protocol_catalog_id].protocol_type for p in ports if p.protocol_catalog_id in d.protocol_catalog])
        _port_open_info_cache[key]=(open_text,proto_text)
        return open_text,proto_text

    def _device_management_ips(device):
        """A device's management IPs: physical management interfaces plus VLAN-based management (incl. VLAN)."""
        mgmt_ifaces=[i for i in d.ifaces_by_device.get(device.id,[]) if i.is_management]
        mgmt_vlan=[x for x in d.device_vlan_by_device.get(device.id,[]) if x.is_management]
        _,ip_values=device_management_ports_and_ips(mgmt_ifaces,d.ips_by_iface,mgmt_vlan,d.vlan_map)
        return ip_values

    def _link_purpose_label(iface):
        mgmt=bool(iface.is_management); data=bool(iface.is_data_transfer)
        if mgmt and data: return "Управление активами, передача данных"
        if mgmt: return "Управление активами"
        if data: return "Передача данных"
        return "-"

    def _conn_row(own_iface, own_device, neighbor_iface, neighbor_device, c, ct):
        own_ips=join_values([ip_label(x) for x in d.ips_by_iface.get(own_iface.id,[])])
        neighbor_mgmt_ips=_device_management_ips(neighbor_device)
        neighbor_ips=join_values(neighbor_mgmt_ips if neighbor_mgmt_ips else [ip_label(x) for x in d.ips_by_iface.get(neighbor_iface.id,[])])
        open_text,proto_text=_port_open_info((own_iface.id,))
        own_vlans=[v for v in d.vlan_by_iface.get(own_iface.id,[]) if v]
        neighbor_vlans=[v for v in d.vlan_by_iface.get(neighbor_iface.id,[]) if v]
        vlan_rows=own_vlans if own_vlans else neighbor_vlans
        return [0,d.device_types.get(own_device.device_type_id).name if d.device_types.get(own_device.device_type_id) else "",own_device.serial_number,own_device.system_name or "",os_label(d.embedded_os.get(own_device.embedded_os_id)),own_iface.name,own_ips or "не назначен",open_text,proto_text,join_values([str(v.vlan_id) for v in vlan_rows]),join_values([v.name for v in vlan_rows]),ct.name if ct else "",_link_purpose_label(own_iface),d.device_types.get(neighbor_device.device_type_id).name if d.device_types.get(neighbor_device.device_type_id) else "",neighbor_device.serial_number,neighbor_device.system_name or "",os_label(d.embedded_os.get(neighbor_device.embedded_os_id)),neighbor_ips or "не назначен"]

    def _disconnected_row(own_device, iface_group):
        own_ips=join_values([ip_label(x) for i in iface_group for x in d.ips_by_iface.get(i.id,[])])
        open_text,proto_text=_port_open_info(tuple(i.id for i in iface_group))
        own_vlans=[v for i in iface_group for v in d.vlan_by_iface.get(i.id,[]) if v]
        purposes=join_values([_link_purpose_label(i) for i in iface_group if _link_purpose_label(i)!="-"]) or "-"
        return [0,d.device_types.get(own_device.device_type_id).name if d.device_types.get(own_device.device_type_id) else "",own_device.serial_number,own_device.system_name or "",os_label(d.embedded_os.get(own_device.embedded_os_id)),join_values([i.name for i in iface_group]),own_ips or "не назначен",open_text,proto_text,join_values([str(v.vlan_id) for v in own_vlans]),join_values([v.name for v in own_vlans]),"",purposes,"","","","",""]

    pending_rows=[]
    connected_iface_ids=set()
    for c in d.conns:
        src=d.iface_map.get(c.source_interface_id); dst=d.iface_map.get(c.destination_interface_id)
        if not src or not dst: continue
        sd=d.device_map.get(src.physical_device_id); dd=d.device_map.get(dst.physical_device_id)
        if not sd or not dd: continue
        ct=d.connection_types.get(c.connection_type_id)
        connected_iface_ids.add(src.id); connected_iface_ids.add(dst.id)
        # Каждая сторона связи попадает в отчёт независимо от другой: при активном фильтре по
        # структурным единицам сосед вне выбранных единиц по-прежнему показывается как контекст
        # порта устройства ИЗ единицы (см. d.allowed_device_ids), но не получает собственную строку.
        allowed=d.allowed_device_ids
        if allowed is None or sd.id in allowed:
            pending_rows.append((sd, _conn_row(src, sd, dst, dd, c, ct)))
        if allowed is None or dd.id in allowed:
            pending_rows.append((dd, _conn_row(dst, dd, src, sd, c, ct)))

    for dev in d.devices:
        own_ifaces=[i for i in d.ifaces_by_device.get(dev.id,[]) if i.id not in connected_iface_ids]
        if not own_ifaces: continue
        groups=defaultdict(list)
        for i in own_ifaces:
            key=tuple(sorted(ip_label(x) for x in d.ips_by_iface.get(i.id,[])))
            groups[key].append(i)
        for iface_group in groups.values():
            pending_rows.append((dev, _disconnected_row(dev, iface_group)))

    # Group consecutively by "own" device (stable sort preserves the connected-then-disconnected,
    # per-connection order within each device) instead of interleaving devices row by row.
    device_order={dev.id:idx for idx,dev in enumerate(d.devices)}
    pending_rows.sort(key=lambda pair: device_order.get(pair[0].id, len(d.devices)))

    numbered=[]
    for i,(_,row) in enumerate(pending_rows,1):
        row=[cell if cell not in (None,"") else "-" for cell in row]
        row[0]=i
        numbered.append(row)
    return numbered


def _populate_sheet3(ws3, d: SimpleNamespace) -> None:
    for row in _connection_row_values_list(d):
        ws3.append(excel_safe_row(row))


def _vm_row_values(v, d: SimpleNamespace) -> list:
    """Значения одной строки листа 'Организация управления ВМ' — см. _is_row_values про
    переиспользование в конструкторе отчётов. Хост/гипервизор берётся из ОС физического хоста;
    IP администрирования — все management-IP ВМ."""
    host=d.device_map.get(v.physical_device_id); hyp=d.operating_systems.get(host.operating_system_id) if host and host.operating_system_id else d.operating_systems.get(v.hypervisor_os_id)
    ips=d.vmips_by_vm.get(v.id,[]); containers_for_vm=[c for c in d.containers if c.virtual_machine_id==v.id]
    openp=d.open_ports_by_owner.get(('virtual_machine',v.id),[])
    admin_ips=join_values([ip_label(x) for x in ips if x.is_management])
    return [v.name,os_label(d.operating_systems.get(v.operating_system_id)),join_values([c.name for c in containers_for_vm]),device_label(host),os_label(hyp),v.purpose or "",join_values([ip_label(x) for x in ips]),join_values([_open_port_label(p, d) for p in openp]),admin_ips,join_values([s.name for s in d.software_by_vm.get(v.id,[])])]


def _populate_sheet4(ws4, d: SimpleNamespace) -> None:
    """Лист 'Организация управления ВМ': хост/гипервизор берётся из ОС физического хоста;
    IP администрирования — все management-IP ВМ."""
    for v in d.vms:
        ws4.append(excel_safe_row(_vm_row_values(v, d)))


def build_report(session: Session, report_dir: Path, only_is: Optional[str] = None,
                  structural_unit_ids: Optional[list] = None) -> Path:
    """structural_unit_ids — необязательный список id структурных единиц (см. models.StructuralUnit):
    если задан, все 4 листа ограничиваются оборудованием, размещённым в этих единицах (и их
    вложенных, см. _expand_structural_unit_ids) — устройствами (лист 2), их портами/связями (лист 3,
    сосед показывается как контекст, даже если сам вне выбранных единиц), размещёнными на них ВМ
    (лист 4) и информационными системами, у которых есть хотя бы один такой физический источник
    (лист 1, см. _is_related_device_ids). None или пустой список — без ограничения (все устройства),
    как и раньше."""
    wb=Workbook()
    ws1=wb.active; ws1.title="Перечень ИС"; setup_sheet(ws1,HEADERS1)
    ws2=wb.create_sheet("Инвентаризац. физ. устройств ИС"); setup_sheet(ws2,HEADERS2)
    ws3=wb.create_sheet("Организация подключений"); setup_sheet(ws3,HEADERS3)
    ws4=wb.create_sheet("Организация управления ВМ"); setup_sheet(ws4,HEADERS4)

    # Load the registry in batches. This avoids the old N+1 pattern and guarantees that
    # information entered in the UI is represented in the report.
    data = _load_report_data(session, only_is, structural_unit_ids)

    _populate_sheet1(ws1, data)
    _populate_sheet2(ws2, data)
    _populate_sheet3(ws3, data)
    _populate_sheet4(ws4, data)

    for ws in wb.worksheets: finalize_sheet(ws)
    report_dir.mkdir(parents=True,exist_ok=True)
    path=report_dir/f"Инвентаризация_ИС_{local_timestamp_suffix()}.xlsx"
    wb.save(path)
    return path
