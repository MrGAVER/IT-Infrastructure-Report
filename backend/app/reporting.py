from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from collections import defaultdict, Counter
from openpyxl import Workbook
from openpyxl.styles import Alignment
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import (
    Building,
    Connection,
    ConnectionType,
    Container,
    CryptoProtectionMeans,
    Department,
    DeployedSoftware,
    DeviceInterface,
    DeviceModel,
    DeviceSubinterface,
    DeviceType,
    EmbeddedOperatingSystem,
    IPAddress,
    ISDepartment,
    ISPlacementAsset,
    ISProtocol,
    InformationSystem,
    InformationSystemSource,
    InterfaceType,
    InterfaceVLAN,
    Manufacturer,
    OpenPort,
    OperatingSystem,
    PhysicalDevice,
    PhysicalDeviceVLAN,
    PlacementAsset,
    ProtocolPortCatalog,
    Room,
    SoftwareAsset,
    StructuralUnit,
    SupportMethod,
    SupportOrganization,
    VLAN,
    VirtualMachine,
)
from .constants import OwnerType
from .services.computed import (
    ip_label,
    device_management_ports_and_ips,
    local_timestamp_suffix,
    port_label_with_subinterfaces,
    subinterface_ip_values,
)
from .services.device_label import device_label
from .services.excel_layout import apply_sheet_layout, fit_sheet_size, style_header
from .services.excel_safety import append_safe_row
from .services.port_vlans import carries_all_vlans, effective_vlan_ids

HEADERS1 = [
    "№",
    "Наименование информационной системы (подситемы/информационного ресурса)",
    "Общее описание информационной системы (подситемы/информационного ресурса)",
    "Назначение использования информационной системы (подсистемы/информационного ресурса) для ИС Организация",
    "Работники, группы работников или подразделения, которые используют в своей работе информационную "
    "систему (подсистему/информационный ресурс)",
    "Локализация информационной системы (подсистемы/информационного ресурса)",
    'Оборудование ООО "Организация", на котором размещается информационная ситема (подсистема/информационный '
    "ресурс), а также прикладное программное обеспечение или интерфейс взаимодействия с внешней информационной "
    "системой.",
    "Протокол передачи данных, по которому осуществляется взаимодействие информационной системы "
    "(подсистемы/информационного ресурса), как внутри ИС Организация, так и при организации внешнего "
    "взаимодейтсвия, в том числе с внешними информационными системами",
    "IP адрес , по которому осуществляется взаимодействие информационной системы (подсистемы/информационного "
    "ресурса), как внутри ИС Организация, так и при организации внешнего взаимодейтсвия, в том числе с внешними "
    "информационными системами",
    "Применение сертифицированных программных и/или программно-аппаратных средств криптографической защиты "
    "информации, применяемых при осуществлении внешнего взаимодействия, в том числе с внешними информационными "
    "системами.",
    "Признак получения событий в SIEM",
    "Наименование организации, информационная система которой осуществляет взаимодействие и (или) обеспечивает техническую поддержку",
    "Способ оказания технической поддержки",
    "Описание процесса функционирования ИС, особенности организации направления потоков для обеспечения функционирования ИС",
    "Название физического сервера (ПК, выполняющего роль сервера), на котором установлена информационная система "
    "(подсистема/информационный ресурс) или установлена виртуальная машина (контейнер), обеспечивающая (ий) функционирование данной "
    "информационной системы (подсистемы/информационного ресурса)",
    "IP-адрес физического сервера, на котором установлена информационная система (подсистема/информационный ресурс)",
    "Наименование виртуальной машины или контейнера, обеспечивающая (ий) функционирование данной "
    "информационной системы (подсистемы/информационного ресурса)",
    "IP-адрес виртуальной машины (контейнера), обеспечивающая (ий) функционирование данной "
    "информационной системы (подсистемы/информационного ресурса)",
]
HEADERS2 = [
    "№",
    "Наименование производителя",
    "Модель устройства",
    "Серийный номер устройства",
    "Системное имя устройства, если устройство является управлемым",
    "Версия операционной системы физического устройства",
    "Номер порта управления устройством, если устройство является управлемым",
    "IP-адрес управления устройством",
    "Признак получения событий в SIEM",
    "Количество физических портов устройства",
    "Адрес расположения устройства",
    "Наименование здания (условное или официальное), в котором располагается устройство",
    "Помещение, в котором размещается телекоммуникационный шкаф, в котором размещается устройство или "
    "место размещения самого устройства в здании",
]
HEADERS3 = [
    "№",
    "Вид физического устройства: серверы, сетевое оборудование, средства защиты информации, рабочий ПК "
    "системного/сетевого администратора и рабочий ПК администратора безопасности, за исключением ПК пользователей",
    "Серийный номер устройства",
    "Системное имя устройства, если устройство является управлемым",
    "Наименование и версия операционной системы физического устройства",
    "Номер физического или логического порта",
    "IP-адрес порта физического устройства ХХХ.ХХХ.ХХХ.ХХХ/24",
    "Перечень открытых портов транспортного уровня с указанием соответствующим им технологий и (или) протоколов",
    "Протокол (технология)",
    "Идентификаторы виртуальных локальных вычислительных сетей (VLAN ID)",
    "Названия виртуальных локальных вычислительных сетей (VLAN Name)",
    "Физические линии связи с указанием их типа (витая пара, волоконно-оптический кабель и др.)",
    "Сведения о назначении линий связи (передача данных или управление активами информационной системы, средствами защиты информации)",
    "Вид соседнего подключенного физического устройства, в соответствии с каждым физическим портом серверы, "
    "сетевое оборудование, средства защиты информации, рабочий ПК сиcтемного/сетевого администратора и   рабочий "
    "ПК, а также ПК пользователей",
    "Серийный номер соседнего физического устройства, в том числе ПК пользователей",
    "Системное имя соседнего физического устройства, если устройство является управлемым, в том числе ПК пользователей",
    "Наименование и версия операционной системы соседнего физического устройства",
    "IP-адрес порта соседнего физического устройства ХХХ.ХХХ.ХХХ.ХХХ/24",
]
HEADERS4 = [
    "Название виртуальной машины",
    "Наименование и версия операционной системы виртуальной машины",
    "Наименование контейнера",
    "Наименование физического устройства , на котором установлена виртуальная машина, согласно его системному имени",
    "Наименование среды виртуализации и ее версия",
    "Целевое использование (функциональное назначение ) виртуальной машины/контейнера",
    "IP-адрес виртуальной машины/контейнера",
    "Перечень открытых портов транспортного уровня с указанием соответствующим им IP-адресов технологий и (или) протоколов",
    "IP-адрес администрирования виртуальной машины/контейнера",
    "Какие программные активы развернуты: 1С, Web-сервер, файловый, AD и т.п.",
]


def join_values(values):
    result = []
    for value in values:
        if value is None:
            continue
        value = str(value).strip()
        if value and value not in result:
            result.append(value)
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


def _open_ports_by_number(ports, d: SimpleNamespace) -> list:
    """Открытые порты владельца по возрастанию номера порта (при равенстве — по транспорту), порты
    без записи справочника — в конце. Порядок записей в БД для этого использовать нельзя: порты ВМ
    обновляются на месте (sync_vm_open_ports), а не пересоздаются при каждом сохранении формы, так
    что порядок вставки перестал совпадать с порядком номеров."""

    def sort_key(p):
        cat = d.protocol_catalog.get(p.protocol_catalog_id)
        return (cat is None, cat.port if cat else 0, p.transport_protocol or "")

    return sorted(ports, key=sort_key)


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
    style_header(ws)
    ws.freeze_panes = "A2"


def finalize_sheet(ws):
    # Данные — по верхнему краю с переносом. Шапку (строка 1) не трогаем: раньше общий проход затирал её
    # выравнивание по центру, заданное в setup_sheet, и все шапки оказывались прижаты к левому верхнему углу.
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    # Ширина колонок — по данным, а не по заголовку (заголовки до 300 символов раздували каждую колонку до
    # максимума), высота шапки — по реальному числу строк переноса: заголовки не обрезаются. См. excel_layout.
    fit_sheet_size(ws)
    if ws.max_row > 1:
        ws.auto_filter.ref = ws.dimensions


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
    linked_devices = []
    linked_vms = []
    linked_containers = []
    for src in d.source_by_is[obj.id]:
        # owner_id хранит id устройства/ВМ/контейнера в зависимости от source_type (миграция
        # 944bd490d967, см. models.InformationSystemSource) — раньше это были три отдельные колонки.
        if src.source_type == "device" and src.owner_id in d.device_map:
            dev = d.device_map[src.owner_id]
            if dev not in linked_devices:
                linked_devices.append(dev)
        elif src.source_type == "vm" and src.owner_id in d.vm_map:
            v = d.vm_map[src.owner_id]
            if v not in linked_vms:
                linked_vms.append(v)
        elif src.source_type == "container" and src.owner_id in d.container_map:
            c = d.container_map[src.owner_id]
            if c not in linked_containers:
                linked_containers.append(c)
    return linked_devices, linked_vms, linked_containers


def _is_related_device_ids(obj, d: SimpleNamespace) -> set:
    """Physical device ids, связанные с ИС напрямую или как хост её ВМ/контейнера — используется
    для фильтрации листа 'Перечень ИС' по структурной единице: ИС попадает в отчёт, только если
    хотя бы один из этих id входит в allowed_device_ids (см. _allowed_device_ids_for_structural_units)."""
    linked_devices, linked_vms, linked_containers = _is_source_links(obj, d)
    ids = {dev.id for dev in linked_devices}
    for v in linked_vms:
        if v.physical_device_id:
            ids.add(v.physical_device_id)
    for c in linked_containers:
        if c.physical_device_id:
            ids.add(c.physical_device_id)
        elif c.virtual_machine_id and c.virtual_machine_id in d.vm_map:
            host_vm = d.vm_map[c.virtual_machine_id]
            if host_vm.physical_device_id:
                ids.add(host_vm.physical_device_id)
    return ids


def _by_id(rows) -> dict:
    return {x.id: x for x in rows}


def _group_by(rows, key) -> defaultdict:
    """defaultdict(list): листы читают его через [] и не должны падать на отсутствующем ключе."""
    grouped = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    return grouped


def _load_organization(session: Session, d: SimpleNamespace, only_is: Optional[str]) -> None:
    """Информационные системы (все или одна), подразделения и организации поддержки."""
    systems = select(InformationSystem).where(InformationSystem.id == only_is) if only_is else select(InformationSystem)
    d.systems = session.scalars(systems.order_by(InformationSystem.name)).all()
    d.departments = session.scalars(select(Department)).all()
    d.dep_map = _by_id(d.departments)
    d.support_orgs = session.scalars(select(SupportOrganization)).all()
    d.support_map = _by_id(d.support_orgs)


def _load_device_catalogs(session: Session, d: SimpleNamespace) -> None:
    """Устройства и справочники, на которые они ссылаются (тип, производитель, модель, место, ОС), а также
    справочники ИС (способ поддержки, СКЗИ, размещение) и типы интерфейсов."""
    # Устройства без системного имени — первыми: NULL в SQLite сортируется первым, в PostgreSQL последним, а порядок листов
    # должен быть одинаковым на обоих (отсюда явное «IS NULL DESC», а не полагание на умолчание СУБД).
    d.devices = session.scalars(
        select(PhysicalDevice).order_by(
            PhysicalDevice.system_name.is_(None).desc(), PhysicalDevice.system_name, PhysicalDevice.serial_number
        )
    ).all()
    d.device_map = _by_id(d.devices)
    d.device_types = _by_id(session.scalars(select(DeviceType)).all())
    d.manufacturers = _by_id(session.scalars(select(Manufacturer)).all())
    d.models = _by_id(session.scalars(select(DeviceModel)).all())
    d.buildings = _by_id(session.scalars(select(Building)).all())
    d.rooms = _by_id(session.scalars(select(Room)).all())
    d.structural_units = _by_id(session.scalars(select(StructuralUnit)).all())
    d.operating_systems = _by_id(session.scalars(select(OperatingSystem)).all())
    d.embedded_os = _by_id(session.scalars(select(EmbeddedOperatingSystem)).all())
    d.support_methods = _by_id(session.scalars(select(SupportMethod)).all())
    d.crypto_means = _by_id(session.scalars(select(CryptoProtectionMeans)).all())
    d.placement_assets = _by_id(session.scalars(select(PlacementAsset)).all())
    d.placement_by_is = _group_by(session.scalars(select(ISPlacementAsset)).all(), lambda x: x.information_system_id)
    d.interface_types = _by_id(session.scalars(select(InterfaceType)).all())


def _load_interfaces_and_addresses(session: Session, d: SimpleNamespace) -> None:
    """Порты, подинтерфейсы и IP-адреса по видам владельца (порт, подинтерфейс, ВМ, источник ИС); адреса других
    владельцев (например, «physical_device») в отчёт не попадают. Раскладка подинтерфейсов по портам и устройствам —
    в _arrange_subinterfaces, когда загружен справочник VLAN."""
    d.interfaces = session.scalars(select(DeviceInterface).order_by(DeviceInterface.name)).all()
    d.iface_map = _by_id(d.interfaces)
    d.interface_ips = session.scalars(
        select(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE).order_by(IPAddress.ip_address)
    ).all()
    d.ips_by_iface = _group_by(d.interface_ips, lambda x: x.owner_id)
    d.ifaces_by_device = _group_by(d.interfaces, lambda x: x.physical_device_id)
    # Подинтерфейсы портов (models.DeviceSubinterface) и их IP (owner_type='device_subinterface'); открытые порты
    # подинтерфейсов лежат в общем d.open_ports_by_owner под ключом ('device_subinterface', id).
    d.subinterfaces = session.scalars(select(DeviceSubinterface).order_by(DeviceSubinterface.name)).all()
    d.ips_by_sub = _group_by(
        session.scalars(
            select(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_SUBINTERFACE).order_by(IPAddress.ip_address)
        ).all(),
        lambda x: x.owner_id,
    )
    d.vmips = session.scalars(
        select(IPAddress).where(IPAddress.owner_type == OwnerType.VIRTUAL_MACHINE).order_by(IPAddress.ip_address)
    ).all()
    d.vmips_by_vm = _group_by(d.vmips, lambda x: x.owner_id)
    d.source_ips = session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.INFORMATION_SYSTEM_SOURCE)).all()
    d.ips_by_source = _group_by(d.source_ips, lambda x: x.owner_id)


def _load_virtualization_and_links(session: Session, d: SimpleNamespace) -> None:
    """ВМ, контейнеры, справочник протоколов, связи ИС (подразделения, протоколы, источники), подключения и открытые порты."""
    d.vms = session.scalars(select(VirtualMachine).order_by(VirtualMachine.name)).all()
    d.vm_map = _by_id(d.vms)
    d.containers = session.scalars(select(Container)).all()
    d.container_map = _by_id(d.containers)
    d.protocols = session.scalars(select(ProtocolPortCatalog)).all()
    d.protocol_catalog = _by_id(d.protocols)
    d.is_deps = session.scalars(select(ISDepartment)).all()
    d.is_protocols = session.scalars(select(ISProtocol)).all()
    d.is_sources = session.scalars(select(InformationSystemSource)).all()
    d.conns = session.scalars(select(Connection).order_by(Connection.created_at)).all()
    d.connection_types = _by_id(session.scalars(select(ConnectionType)).all())
    d.open_ports = session.scalars(select(OpenPort)).all()
    d.open_ports_by_owner = _group_by(d.open_ports, lambda x: (x.owner_type, x.owner_id))


def _load_vlans(session: Session, d: SimpleNamespace) -> None:
    """Справочник VLAN, VLAN устройств и VLAN портов."""
    d.vlans = session.scalars(select(VLAN)).all()
    d.vlan_map = _by_id(d.vlans)
    d.iface_vlans = session.scalars(select(InterfaceVLAN)).all()
    d.vlan_by_iface = defaultdict(list)
    d.device_vlan_rows = session.scalars(select(PhysicalDeviceVLAN)).all()
    d.device_vlan_by_device = _group_by(d.device_vlan_rows, lambda x: x.physical_device_id)
    # Порт с «Все VLAN» хранит только признак: его VLAN — все VLAN устройства (тип ∪ собственные), по номеру
    # (services/port_vlans.py). Связи такого порта (их быть не должно) игнорируются, у остальных — выбранные.
    all_vlans_ports = [x for x in d.interfaces if carries_all_vlans(x)]
    all_vlans_ids = {x.id for x in all_vlans_ports}
    for x in d.iface_vlans:
        if x.interface_id not in all_vlans_ids:
            d.vlan_by_iface[x.interface_id].append(d.vlan_map.get(x.vlan_id))
    if all_vlans_ports:
        derived = effective_vlan_ids(session, [x.id for x in all_vlans_ports])
        for x in all_vlans_ports:
            numbered = sorted((v for v in derived.get(x.id, ()) if v in d.vlan_map), key=lambda v: (d.vlan_map[v].vlan_id, v))
            d.vlan_by_iface[x.id] = [d.vlan_map[v] for v in numbered]


def _arrange_subinterfaces(d: SimpleNamespace) -> None:
    """Подинтерфейсы по портам (порядок: по номеру VLAN, затем по имени) и по устройствам (в порядке портов)."""

    def order(sub):
        vlan = d.vlan_map.get(sub.vlan_id)
        return (vlan.vlan_id if vlan else 0, (sub.name or "").casefold())

    d.subs_by_iface = _group_by(sorted(d.subinterfaces, key=order), lambda x: x.parent_interface_id)
    d.subs_by_device = defaultdict(list)
    for iface in d.interfaces:
        d.subs_by_device[iface.physical_device_id] += d.subs_by_iface.get(iface.id, [])


def _load_software(session: Session, d: SimpleNamespace) -> None:
    """ПО: на ВМ — в software_by_vm, на всём остальном (устройство, контейнер) — в software_by_device."""
    d.deployed_software = session.scalars(select(DeployedSoftware)).all()
    d.software = _by_id(session.scalars(select(SoftwareAsset)).all())
    d.software_by_vm = defaultdict(list)
    d.software_by_device = defaultdict(list)
    for link in d.deployed_software:
        if link.software_asset_id not in d.software:
            continue
        target = d.software_by_vm if link.owner_type == "virtual_machine" else d.software_by_device
        target[link.owner_id].append(d.software[link.software_asset_id])


def _group_information_system_links(d: SimpleNamespace) -> None:
    d.dep_by_is = _group_by(d.is_deps, lambda x: x.information_system_id)
    d.protocol_by_is = _group_by(d.is_protocols, lambda x: x.information_system_id)
    d.source_by_is = _group_by(d.is_sources, lambda x: x.information_system_id)


def _apply_structural_unit_filter(d: SimpleNamespace, structural_unit_ids: Optional[list]) -> None:
    """Фильтр по структурным единицам применяется В КОНЦЕ, когда все lookup-словари (device_map/
    vm_map/container_map/source_by_is/...) уже полностью загружены: _is_related_device_ids() и
    поиск соседних устройств на листе 3 должны видеть ПОЛНЫЙ реестр независимо от фильтра, сужаются
    только сами списки-перечисления (d.devices/d.vms/d.systems) и флаг d.allowed_device_ids."""
    d.allowed_device_ids = _allowed_device_ids_for_structural_units(d, structural_unit_ids)
    if d.allowed_device_ids is not None:
        d.devices = [x for x in d.devices if x.id in d.allowed_device_ids]
        d.vms = [x for x in d.vms if x.physical_device_id in d.allowed_device_ids]
        d.systems = [x for x in d.systems if _is_related_device_ids(x, d) & d.allowed_device_ids]


def _load_report_data(session: Session, only_is: Optional[str], structural_unit_ids: Optional[list] = None) -> SimpleNamespace:
    """Batch-load the whole registry needed to build all 4 sheets. Kept as one entry point (rather
    than one per sheet) because several lookups are shared across sheets (device_map, ifaces_by_device,
    embedded_os, etc.) and loading them once avoids redundant queries; внутри — шаги, каждый наполняет
    общий контейнер `d` (порядок важен: раскладка подинтерфейсов опирается на справочник VLAN, фильтр —
    на всё загруженное).

    structural_unit_ids — необязательный фильтр по структурным единицам (см.
    _allowed_device_ids_for_structural_units): если задан, d.devices/d.vms/d.systems в конце функции
    сужаются до записей, относящихся к выбранным единицам, а d.allowed_device_ids хранит набор
    допустимых id устройств (или None, если фильтр не активен) для листа 'Организация подключений'
    (см. _connection_row_values_list). d.device_map/d.vm_map/d.container_map остаются ПОЛНЫМИ
    (не сужаются) — они нужны для корректного поиска соседних устройств/хостов независимо от фильтра.

    Состав и содержимое `d` — контракт для листов Excel, конструктора отчётов и структурного приложения;
    закреплён tests/test_report_data_behaviour.py."""
    d = SimpleNamespace()
    _load_organization(session, d, only_is)
    _load_device_catalogs(session, d)
    _load_interfaces_and_addresses(session, d)
    _load_virtualization_and_links(session, d)
    _load_vlans(session, d)
    _arrange_subinterfaces(d)
    _load_software(session, d)
    _group_information_system_links(d)
    _apply_structural_unit_filter(d, structural_unit_ids)
    return d


def _yes_no(flag) -> str:
    return "Да" if flag else "Нет"


def _is_equipment_labels(linked_devices: list, linked_vms: list, linked_containers: list, placements: list, d: SimpleNamespace) -> list:
    """Оборудование ИС: устройства (каждое — с установленным ПО), ВМ, контейнеры и площадки размещения."""
    labels = []
    for dev in linked_devices:
        labels.append(device_label(dev))
        labels += [f"ПО: {s.name}" for s in d.software_by_device.get(dev.id, [])]
    labels += [f"VM: {v.name}" for v in linked_vms]
    labels += [f"Контейнер: {c.name}" for c in linked_containers]
    labels += [d.placement_assets[x.placement_asset_id].name for x in placements if x.placement_asset_id in d.placement_assets]
    return labels


def _is_protocol_label(protocol, d: SimpleNamespace) -> str:
    cat = d.protocol_catalog.get(protocol.protocol_catalog_id)
    proto = cat.protocol_type if cat else ""
    port = cat.port if cat else None
    desc = join_values([cat.description if cat else None, protocol.description])
    return join_values([f"{proto}/{port}" if port else proto, desc])


def _is_physical_devices(linked_devices: list, linked_vms: list, d: SimpleNamespace) -> list:
    """Физические устройства ИС: связанные напрямую, затем (без повторов) хосты её виртуальных машин."""
    devices = linked_devices[:]
    for v in linked_vms:
        host = d.device_map.get(v.physical_device_id)
        if host is not None and host not in devices:
            devices.append(host)
    return devices


def _management_ip_labels(devices: list, d: SimpleNamespace) -> list:
    """IP управления устройств: адреса портов с ролью «Управление», затем адреса управляющих подинтерфейсов."""
    labels = []
    for dev in devices:
        labels += [
            ip_label(ip) for iface in d.ifaces_by_device.get(dev.id, []) if iface.is_management for ip in d.ips_by_iface.get(iface.id, [])
        ]
        # Управление может висеть на подинтерфейсе порта (например, Gi0/0.99) — его IP это тоже IP управления устройства.
        labels += [ip_label(ip) for sub in d.subs_by_device.get(dev.id, []) if sub.is_management for ip in d.ips_by_sub.get(sub.id, [])]
    return labels


def _is_departments_text(obj, d: SimpleNamespace) -> str:
    return join_values([d.dep_map[x.department_id].name for x in d.dep_by_is[obj.id] if x.department_id in d.dep_map])


def _is_crypto_text(obj, d: SimpleNamespace) -> str:
    means = d.crypto_means.get(obj.crypto_protection_description_id)
    return join_values([_yes_no(obj.crypto_protection_enabled), means.name if means else None])


def _is_row_values(obj, d: SimpleNamespace) -> list:
    """Значения одной строки листа 'Перечень ИС' (без №) — вынесено из _populate_sheet1, чтобы эту
    же логику мог переиспользовать конструктор отчётов (services/report_registry_rows.py) без
    дублирования: расхождение между регламентированным отчётом и его "точной" заготовкой в
    конструкторе было бы куда хуже, чем общая функция.

    Столбцы не независимы (список ВМ и их IP входит сразу в несколько), поэтому строка собирается из общих
    промежуточных значений, а каждое составное значение — отдельной функцией выше."""
    source_rows = d.source_by_is[obj.id]
    linked_devices, linked_vms, linked_containers = _is_source_links(obj, d)
    physical_devices = _is_physical_devices(linked_devices, linked_vms, d)
    vm_ips = [ip_label(ip) for v in linked_vms for ip in d.vmips_by_vm.get(v.id, [])]
    source_ips = [x.ip_address for src in source_rows for x in d.ips_by_source.get(src.id, [])]
    equipment = _is_equipment_labels(linked_devices, linked_vms, linked_containers, d.placement_by_is[obj.id], d)
    support = d.support_map.get(obj.support_organization_id)
    support_method = d.support_methods.get(obj.support_method_id)
    return [
        obj.name,
        obj.description or "",
        obj.purpose or "",
        _is_departments_text(obj, d),
        obj.localization or "",
        join_values(equipment),
        join_values([_is_protocol_label(p, d) for p in d.protocol_by_is[obj.id]]),
        join_values(source_ips + vm_ips),
        _is_crypto_text(obj, d),
        _yes_no(obj.siem_enabled),
        support.name if support else "",
        support_method.name if support_method else "",
        obj.process_description or "",
        join_values([device_label(dev) for dev in physical_devices]),
        join_values(_management_ip_labels(physical_devices, d)),
        join_values([v.name for v in linked_vms] + [c.name for c in linked_containers]),
        join_values(vm_ips),
    ]


def _populate_sheet1(ws1, d: SimpleNamespace) -> None:
    """Лист 'Перечень ИС': все привязанные источники плюс детали протоколов/IP."""
    for n, obj in enumerate(d.systems, 1):
        append_safe_row(ws1, [n, *_is_row_values(obj, d)])


def _device_row_values(dev, d: SimpleNamespace) -> list:
    """Значения одной строки листа 'Инвентаризац. физ. устройств ИС' (без №) — см. _is_row_values
    про переиспользование в конструкторе отчётов."""
    all_ifaces = d.ifaces_by_device.get(dev.id, [])
    mgmt_ifaces = [i for i in all_ifaces if i.is_management]
    mgmt_vlan = [x for x in d.device_vlan_by_device.get(dev.id, []) if x.is_management]
    mgmt_subs = [x for x in d.subs_by_device.get(dev.id, []) if x.is_management]
    mgmt_port_names, mgmt_ip_values = device_management_ports_and_ips(
        mgmt_ifaces,
        d.ips_by_iface,
        mgmt_vlan,
        d.vlan_map,
        vlan_label_with_name=False,
        management_subinterfaces=mgmt_subs,
        ips_by_subinterface=d.ips_by_sub,
        port_name_by_id={i.id: i.name for i in all_ifaces},
    )
    mgmt_ports = join_values(mgmt_port_names)
    mgmt_ips = join_values(mgmt_ip_values)
    serial = dev.serial_number or ""
    sysname = dev.system_name or ""
    os_names = os_label(d.embedded_os.get(dev.embedded_os_id))
    manufacturer_names = d.manufacturers.get(dev.manufacturer_id).name if d.manufacturers.get(dev.manufacturer_id) else ""
    model_names = d.models.get(dev.model_id).model if d.models.get(dev.model_id) else ""
    addresses = d.buildings.get(dev.building_id).address if d.buildings.get(dev.building_id) else ""
    building_names = d.buildings.get(dev.building_id).name if d.buildings.get(dev.building_id) else ""
    room_names = d.rooms.get(dev.room_id).name if d.rooms.get(dev.room_id) else ""
    return [
        manufacturer_names,
        model_names,
        serial,
        sysname,
        os_names,
        mgmt_ports,
        mgmt_ips,
        "Да" if dev.siem_enabled else "Нет",
        interface_port_count_label(all_ifaces, d.interface_types),
        addresses,
        building_names,
        room_names,
    ]


def _populate_sheet2(ws2, d: SimpleNamespace) -> None:
    """Лист 'Инвентаризац. физ. устройств ИС': одна строка на физическое устройство."""
    for n, dev in enumerate(d.devices, 1):
        append_safe_row(ws2, [n, *_device_row_values(dev, d)])


class _ConnectionRows:
    """Сборщик строк листа 'Организация подключений' по загруженным данным `d`.

    Every physical port must appear — connected ports show both ends of the link (own device +
    neighbor), disconnected ports still get a row of their own, though ports on the same device
    with no connection that share an IP signature (including "no IP") may be grouped into a
    single row rather than one row each.

    Подинтерфейсы порта выводятся ВНУТРИ строки порта, а не отдельными строками: подпись порта, IP, открытые
    порты, VLAN и назначение собираются из самого порта и его подинтерфейсов (шапка колонки «Номер физического
    или логического порта» это допускает). Данные подинтерфейса помечаются его именем."""

    # Текст в колонках IP, когда у порта (или у соседа) адреса нет. Остальные пустые ячейки строки позже заменяются на «-».
    NO_ADDRESS = "не назначен"

    def __init__(self, d: SimpleNamespace):
        self.d = d
        self._open_info_cache: dict = {}

    # --- сведения о порте --------------------------------------------------------------------------------------

    def open_info(self, iface_ids) -> tuple:
        # п.1.4 (батч4): открытые порты теперь свойство КОНКРЕТНОГО интерфейса (порта), а не
        # всего устройства — раньше один и тот же список открытых портов устройства подставлялся
        # в КАЖДУЮ строку Листа 3 (на каждый порт), что было некорректно уже при более чем одном
        # порте на устройстве. iface_ids — кортеж id интерфейсов, формирующих одну строку отчёта
        # (обычно один, но для сгруппированных disconnected-строк — несколько, см.
        # disconnected_row). 'physical_device'-владение (см. OwnerType в constants.py) больше не
        # читается здесь намеренно — устаревшие записи, заведённые до этого фикса на устройствах
        # с несколькими портами, неоднозначны (неизвестно, какому порту принадлежат) и не
        # переносятся автоматически, см. докстринг миграции 20260911_ports_per_interface.
        key = tuple(sorted(iface_ids))
        if key in self._open_info_cache:
            return self._open_info_cache[key]
        d = self.d
        ports = [p for iid in iface_ids for p in d.open_ports_by_owner.get(("device_interface", iid), [])]
        # Подинтерфейсы порта выводятся внутри строки порта: открытые порты подинтерфейса — с его именем
        # («Gi0/0.10: TCP/443 HTTPS»), чтобы было видно, на каком логическом интерфейсе порт открыт.
        sub_ports = [
            (sub, p)
            for iid in iface_ids
            for sub in d.subs_by_iface.get(iid, [])
            for p in d.open_ports_by_owner.get(("device_subinterface", sub.id), [])
        ]
        open_text = join_values([_open_port_label(p, d) for p in ports] + [f"{sub.name}: {_open_port_label(p, d)}" for sub, p in sub_ports])
        proto_text = join_values(
            [
                d.protocol_catalog[p.protocol_catalog_id].protocol_type
                for p in ports + [p for _, p in sub_ports]
                if p.protocol_catalog_id in d.protocol_catalog
            ]
        )
        self._open_info_cache[key] = (open_text, proto_text)
        return open_text, proto_text

    def management_ips(self, device):
        """A device's management IPs: physical management interfaces plus VLAN-based management (incl. VLAN)."""
        d = self.d
        mgmt_ifaces = [i for i in d.ifaces_by_device.get(device.id, []) if i.is_management]
        mgmt_vlan = [x for x in d.device_vlan_by_device.get(device.id, []) if x.is_management]
        mgmt_subs = [x for x in d.subs_by_device.get(device.id, []) if x.is_management]
        _, ip_values = device_management_ports_and_ips(
            mgmt_ifaces, d.ips_by_iface, mgmt_vlan, d.vlan_map, management_subinterfaces=mgmt_subs, ips_by_subinterface=d.ips_by_sub
        )
        return ip_values

    def port_label(self, iface):
        return port_label_with_subinterfaces(iface.name, self.d.subs_by_iface.get(iface.id, []), self.d.vlan_map)

    def port_ip_values(self, iface):
        d = self.d
        return [ip_label(x) for x in d.ips_by_iface.get(iface.id, [])] + subinterface_ip_values(
            d.subs_by_iface.get(iface.id, []), d.ips_by_sub
        )

    def port_vlans(self, iface):
        """VLAN порта плюс VLAN его подинтерфейсов (без повторов): подинтерфейс на VLAN 10 — это VLAN 10 на линии."""
        d = self.d
        vlans = [v for v in d.vlan_by_iface.get(iface.id, []) if v]
        seen = {v.id for v in vlans}
        for sub in d.subs_by_iface.get(iface.id, []):
            vlan = d.vlan_map.get(sub.vlan_id)
            if vlan and vlan.id not in seen:
                seen.add(vlan.id)
                vlans.append(vlan)
        return vlans

    @staticmethod
    def link_purpose_label(iface):
        mgmt = bool(iface.is_management)
        data = bool(iface.is_data_transfer)
        if mgmt and data:
            return "Управление активами, передача данных"
        if mgmt:
            return "Управление активами"
        if data:
            return "Передача данных"
        return "-"

    def purpose_text(self, iface):
        """Назначение порта; роли его подинтерфейсов — с именем подинтерфейса («Gi0/0.99: Управление активами»)."""
        parts = [self.link_purpose_label(iface)] + [
            f"{sub.name}: {self.link_purpose_label(sub)}"
            for sub in self.d.subs_by_iface.get(iface.id, [])
            if self.link_purpose_label(sub) != "-"
        ]
        return join_values([x for x in parts if x != "-"]) or "-"

    # --- ячейки строки -----------------------------------------------------------------------------------------

    def device_cells(self, device) -> list:
        """Вид, серийный номер, системное имя и ОС устройства — одинаково для владельца строки и для соседа."""
        device_type = self.d.device_types.get(device.device_type_id)
        return [
            device_type.name if device_type else "",
            device.serial_number,
            device.system_name or "",
            os_label(self.d.embedded_os.get(device.embedded_os_id)),
        ]

    def connected_row(self, own_iface, own_device, neighbor_iface, neighbor_device, connection_type) -> list:
        own_ips = join_values(self.port_ip_values(own_iface))
        neighbor_mgmt_ips = self.management_ips(neighbor_device)
        neighbor_ips = join_values(neighbor_mgmt_ips if neighbor_mgmt_ips else self.port_ip_values(neighbor_iface))
        open_text, proto_text = self.open_info((own_iface.id,))
        own_vlans = self.port_vlans(own_iface)
        vlan_rows = own_vlans if own_vlans else self.port_vlans(neighbor_iface)
        return [
            0,
            *self.device_cells(own_device),
            self.port_label(own_iface),
            own_ips or self.NO_ADDRESS,
            open_text,
            proto_text,
            join_values([str(v.vlan_id) for v in vlan_rows]),
            join_values([v.name for v in vlan_rows]),
            connection_type.name if connection_type else "",
            self.purpose_text(own_iface),
            *self.device_cells(neighbor_device),
            neighbor_ips or self.NO_ADDRESS,
        ]

    def disconnected_row(self, own_device, iface_group) -> list:
        own_ips = join_values([x for i in iface_group for x in self.port_ip_values(i)])
        open_text, proto_text = self.open_info(tuple(i.id for i in iface_group))
        own_vlans = [v for i in iface_group for v in self.port_vlans(i)]
        purposes = join_values([self.purpose_text(i) for i in iface_group if self.purpose_text(i) != "-"]) or "-"
        return [
            0,
            *self.device_cells(own_device),
            join_values([self.port_label(i) for i in iface_group]),
            own_ips or self.NO_ADDRESS,
            open_text,
            proto_text,
            join_values([str(v.vlan_id) for v in own_vlans]),
            join_values([v.name for v in own_vlans]),
            "",
            purposes,
            "",
            "",
            "",
            "",
            "",
        ]

    # --- набор строк -------------------------------------------------------------------------------------------

    def connected_rows(self) -> tuple[list, set]:
        """Пары (устройство-владелец, строка) по подключениям и id портов, у которых есть подключение."""
        d = self.d
        pending: list = []
        connected_iface_ids: set = set()
        allowed = d.allowed_device_ids
        for c in d.conns:
            src = d.iface_map.get(c.source_interface_id)
            dst = d.iface_map.get(c.destination_interface_id)
            if not src or not dst:
                continue
            sd = d.device_map.get(src.physical_device_id)
            dd = d.device_map.get(dst.physical_device_id)
            if not sd or not dd:
                continue
            ct = d.connection_types.get(c.connection_type_id)
            connected_iface_ids.update((src.id, dst.id))
            # Каждая сторона связи попадает в отчёт независимо от другой: при активном фильтре по
            # структурным единицам сосед вне выбранных единиц по-прежнему показывается как контекст
            # порта устройства ИЗ единицы (см. d.allowed_device_ids), но не получает собственную строку.
            if allowed is None or sd.id in allowed:
                pending.append((sd, self.connected_row(src, sd, dst, dd, ct)))
            if allowed is None or dd.id in allowed:
                pending.append((dd, self.connected_row(dst, dd, src, sd, ct)))
        return pending, connected_iface_ids

    def disconnected_rows(self, connected_iface_ids: set) -> list:
        """Пары (устройство, строка) по портам без подключения; порты устройства с одинаковой «подписью IP» — одной строкой."""
        d = self.d
        pending: list = []
        for dev in d.devices:
            own_ifaces = [i for i in d.ifaces_by_device.get(dev.id, []) if i.id not in connected_iface_ids]
            groups = defaultdict(list)
            for i in own_ifaces:
                # Порт с подинтерфейсами не склеивается с другими портами по совпавшей «подписи IP»: у каждого свой набор
                # подинтерфейсов, и объединённая строка потеряла бы, чьи они.
                key = (i.id,) if d.subs_by_iface.get(i.id) else tuple(sorted(ip_label(x) for x in d.ips_by_iface.get(i.id, [])))
                groups[key].append(i)
            for iface_group in groups.values():
                pending.append((dev, self.disconnected_row(dev, iface_group)))
        return pending

    def numbered_rows(self) -> list:
        pending, connected_iface_ids = self.connected_rows()
        pending += self.disconnected_rows(connected_iface_ids)
        # Group consecutively by "own" device (stable sort preserves the connected-then-disconnected,
        # per-connection order within each device) instead of interleaving devices row by row.
        device_order = {dev.id: idx for idx, dev in enumerate(self.d.devices)}
        pending.sort(key=lambda pair: device_order.get(pair[0].id, len(self.d.devices)))
        numbered = []
        for i, (dev, row) in enumerate(pending, 1):
            row = [cell if cell not in (None, "") else "-" for cell in row]
            row[0] = i
            numbered.append((dev.id, row))
        return numbered


def _connection_rows_by_device(d: SimpleNamespace) -> list:
    """Пронумерованные строки листа 'Организация подключений' в виде пар (id устройства-владельца
    строки, строка); первый элемент каждой строки — №, как ждёт _populate_sheet3. Строки одного
    устройства идут подряд (см. сортировку в _ConnectionRows.numbered_rows), поэтому по id устройства
    _populate_sheet3 находит границы блока устройства на листе: сравнивать для этого значения колонок
    нельзя — пустые поля заменяются на "-", и два разных устройства без серийного номера и системного
    имени выглядели бы одним. Вынесено из _populate_sheet3, см. _is_row_values про переиспользование в
    конструкторе отчётов (он берёт строки без id устройства через _connection_row_values_list)."""
    return _ConnectionRows(d).numbered_rows()


def _connection_row_values_list(d: SimpleNamespace) -> list:
    """Пронумерованные строки листа 'Организация подключений' (первый элемент каждой строки — №)
    без привязки к устройству — контракт, на который опирается конструктор отчётов
    (services/report_registry_rows.py), поэтому форму результата менять нельзя."""
    return [row for _, row in _connection_rows_by_device(d)]


# Колонки листа 'Организация подключений' (номера с 1), описывающие само устройство-владельца строки:
# вид, серийный номер, системное имя, ОС. У устройства с несколькими портами они повторяются в каждой
# строке порта, и в отчёте объединяются по вертикали на весь блок устройства.
SHEET3_DEVICE_COLUMNS = (2, 3, 4, 5)


def _populate_sheet3(ws3, d: SimpleNamespace) -> list:
    """Лист 'Организация подключений': по строке на порт. Возвращает блоки строк листа — по одному
    на устройство, в виде (первая строка, последняя строка): по ним build_report объединяет данные
    устройства и обводит блок рамкой."""
    spans = []
    previous = object()
    for device_id, row in _connection_rows_by_device(d):
        append_safe_row(ws3, row)
        if device_id == previous:
            spans[-1] = (spans[-1][0], ws3.max_row)
        else:
            spans.append((ws3.max_row, ws3.max_row))
            previous = device_id
    return spans


def _vm_row_values(v, d: SimpleNamespace) -> list:
    """Значения одной строки листа 'Организация управления ВМ' — см. _is_row_values про
    переиспользование в конструкторе отчётов. Хост/гипервизор берётся из ОС физического хоста;
    IP администрирования — все management-IP ВМ."""
    host = d.device_map.get(v.physical_device_id)
    hyp = (
        d.operating_systems.get(host.operating_system_id)
        if host and host.operating_system_id
        else d.operating_systems.get(v.hypervisor_os_id)
    )
    ips = d.vmips_by_vm.get(v.id, [])
    containers_for_vm = [c for c in d.containers if c.virtual_machine_id == v.id]
    openp = _open_ports_by_number(d.open_ports_by_owner.get(("virtual_machine", v.id), []), d)
    admin_ips = join_values([ip_label(x) for x in ips if x.is_management])
    return [
        v.name,
        os_label(d.operating_systems.get(v.operating_system_id)),
        join_values([c.name for c in containers_for_vm]),
        device_label(host),
        os_label(hyp),
        v.purpose or "",
        join_values([ip_label(x) for x in ips]),
        join_values([_open_port_label(p, d) for p in openp]),
        admin_ips,
        join_values([s.name for s in d.software_by_vm.get(v.id, [])]),
    ]


def _populate_sheet4(ws4, d: SimpleNamespace) -> None:
    """Лист 'Организация управления ВМ': хост/гипервизор берётся из ОС физического хоста;
    IP администрирования — все management-IP ВМ."""
    for v in d.vms:
        append_safe_row(ws4, _vm_row_values(v, d))


def build_report(session: Session, report_dir: Path, only_is: Optional[str] = None, structural_unit_ids: Optional[list] = None) -> Path:
    """structural_unit_ids — необязательный список id структурных единиц (см. models.StructuralUnit):
    если задан, все 4 листа ограничиваются оборудованием, размещённым в этих единицах (и их
    вложенных, см. _expand_structural_unit_ids) — устройствами (лист 2), их портами/связями (лист 3,
    сосед показывается как контекст, даже если сам вне выбранных единиц), размещёнными на них ВМ
    (лист 4) и информационными системами, у которых есть хотя бы один такой физический источник
    (лист 1, см. _is_related_device_ids). None или пустой список — без ограничения (все устройства),
    как и раньше."""
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Перечень ИС"
    setup_sheet(ws1, HEADERS1)
    ws2 = wb.create_sheet("Инвентаризац. физ. устройств ИС")
    setup_sheet(ws2, HEADERS2)
    ws3 = wb.create_sheet("Организация подключений")
    setup_sheet(ws3, HEADERS3)
    ws4 = wb.create_sheet("Организация управления ВМ")
    setup_sheet(ws4, HEADERS4)

    # Load the registry in batches. This avoids the old N+1 pattern and guarantees that
    # information entered in the UI is represented in the report.
    data = _load_report_data(session, only_is, structural_unit_ids)

    _populate_sheet1(ws1, data)
    _populate_sheet2(ws2, data)
    device_spans = _populate_sheet3(ws3, data)
    _populate_sheet4(ws4, data)

    for ws in wb.worksheets:
        finalize_sheet(ws)

    # Оформление (см. services/excel_layout.py): шапка и каждая запись — ИС (лист 1), устройство
    # (лист 2), ВМ (лист 4) — обведены рамкой, шапка закреплена. На листе 3 запись — устройство с
    # несколькими строками портов: рамка вокруг всего блока устройства, данные самого устройства
    # (вид, серийный номер, имя, ОС) объединены по строкам блока. Оформление накладывается после
    # finalize_sheet: тот перебирает ячейки готового листа для выравнивания и ширины колонок.
    apply_sheet_layout(ws1)
    apply_sheet_layout(ws2)
    apply_sheet_layout(ws3, spans=device_spans, merge_columns=SHEET3_DEVICE_COLUMNS)
    apply_sheet_layout(ws4)
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"Инвентаризация_ИС_{local_timestamp_suffix()}.xlsx"
    wb.save(path)
    return path
