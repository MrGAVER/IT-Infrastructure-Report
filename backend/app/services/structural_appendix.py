"""
Данные для Word-документа «Приложение к структурной схеме» (ЕАИС) — три таблицы по образцу
регламентированного документа заказчика:

1. «Сведения о назначении линий связи» — по строке на каждое действующее подключение
   (устройство (порт) — устройство (порт)); назначение линии — общее для группы подряд идущих строк.
2. «Перечень виртуальных локальных вычислительных сетей (VLAN)» — VLAN, сгруппированные под
   строкой-заголовком устройства; устройства одного стека — одна группа с перечнем серийных номеров.
3. «Перечень телекоммуникационного оборудования» — все физические устройства реестра, место
   размещения у подряд идущих устройств в одном помещении общее.

Модуль только собирает данные (без python-docx): отрисовка — structural_appendix_docx.py. Разделение
нужно, чтобы правила отбора и подписей проверялись тестами без разбора docx-файла.

Источник данных — тот же загрузчик реестра, что у регламентированного Excel-отчёта
(reporting._load_report_data), поэтому фильтр по структурным единицам и состав устройств не могут
разойтись с ним: при активном фильтре в документ попадают устройства выбранных единиц, а подключение
— если хотя бы один его конец принадлежит этим устройствам (второй конец остаётся контекстом линии).

Правила, не очевидные из образца:

- Назначение линии — объединение ролей обоих портов (и их подинтерфейсов): «управление активами»
  (is_management), «передача данных» (is_data_transfer) либо обе роли. Порядок групп в таблице 1 —
  управление, передача данных, оба назначения, без назначения; внутри группы — порядок создания
  подключений. Неактивные подключения (is_active = false) в документ не попадают.
- Наименование оборудования — «производитель модель» (производитель не дублируется, если модель
  уже начинается с него); у устройства без модели — тип устройства, без типа — серийный номер.
  В заголовке группы VLAN перед наименованием стоит тип устройства («Коммутатор Cisco WS-C3750X-48»).
- В таблице VLAN показывается только то, что заведено на устройстве (PhysicalDeviceVLAN): адресация
  — «IP/префикс» как введено; устройства без VLAN в таблицу не попадают. У стека VLAN объединяются по
  участникам без дублей (при общей настройке стека у всех участников одинаковые копии).
- IP-адреса управления показываются без префикса, по одному на строку ячейки (как у СХД с
  несколькими контроллерами в образце).
- Порядок устройств — порядок создания в реестре; участники одного стека идут подряд.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DeviceStackMember
from ..reporting import _load_report_data
from .computed import device_management_ports_and_ips

PURPOSE_MANAGEMENT = "управление активами"
PURPOSE_DATA = "передача данных"
PURPOSE_BOTH = "передача данных и управление активами"

# Порядок групп таблицы 1: (набор ролей, подпись). Группа без ролей — последняя, подпись пустая.
_PURPOSE_GROUPS: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"management"}), PURPOSE_MANAGEMENT),
    (frozenset({"data"}), PURPOSE_DATA),
    (frozenset({"management", "data"}), PURPOSE_BOTH),
    (frozenset(), ""),
)


@dataclass(frozen=True)
class LinkRow:
    left: str
    right: str
    purpose: str


@dataclass(frozen=True)
class VlanRow:
    vlan_id: str
    name: str
    addressing: str


@dataclass(frozen=True)
class VlanGroup:
    title: str
    rows: list[VlanRow]


@dataclass(frozen=True)
class EquipmentRow:
    name: str
    serial_number: str
    system_name: str
    management_ips: list[str]
    placement: str
    # Ключ слияния ячейки «Место размещения»: одинаковые подписи в разных зданиях не склеиваются.
    placement_key: tuple[Optional[str], Optional[str]]


@dataclass(frozen=True)
class AppendixData:
    links: list[LinkRow] = field(default_factory=list)
    vlan_groups: list[VlanGroup] = field(default_factory=list)
    equipment: list[EquipmentRow] = field(default_factory=list)


def _naive(moment: Optional[datetime]) -> datetime:
    """Момент создания без часового пояса — значения из разных СУБД/сессий иначе нельзя сравнивать."""
    return moment.replace(tzinfo=None) if moment else datetime.min


def _natural(text: str) -> tuple[Any, ...]:
    """Ключ «естественной» сортировки строки: Gi1/0/2 раньше Gi1/0/10."""
    parts: list[Any] = []
    digits = ""
    for char in text.casefold():
        if char.isdigit():
            digits += char
            continue
        if digits:
            parts.append((0, int(digits)))
            digits = ""
        parts.append((1, char))
    if digits:
        parts.append((0, int(digits)))
    return tuple(parts)


def equipment_name(dev: Any, d: SimpleNamespace) -> str:
    """«Производитель модель»; без модели — тип устройства, без типа — серийный номер."""
    model = d.models.get(dev.model_id)
    # Производитель устройства необязателен, а у модели обязателен — без своего берём производителя модели.
    manufacturer = d.manufacturers.get(dev.manufacturer_id) or (d.manufacturers.get(model.manufacturer_id) if model else None)
    maker = (manufacturer.name if manufacturer else "").strip()
    model_name = (model.model if model else "").strip()
    if maker and model_name and not model_name.casefold().startswith(maker.casefold()):
        return f"{maker} {model_name}"
    if model_name or maker:
        return model_name or maker
    device_type = d.device_types.get(dev.device_type_id)
    return (device_type.name if device_type else "").strip() or dev.serial_number


def _device_label(dev: Any) -> str:
    return (dev.system_name or "").strip() or dev.serial_number


def _port_roles(iface: Any, d: SimpleNamespace) -> set[str]:
    """Роли порта и его подинтерфейсов: управление может висеть на подинтерфейсе (Gi0/0.99), но линия
    связи при этом физически одна — порт."""
    roles: set[str] = set()
    for item in [iface, *d.subs_by_iface.get(iface.id, [])]:
        if item.is_management:
            roles.add("management")
        if item.is_data_transfer:
            roles.add("data")
    return roles


def _purpose_rank(roles: set[str]) -> int:
    for rank, (group_roles, _label) in enumerate(_PURPOSE_GROUPS):
        if group_roles == roles:
            return rank
    return len(_PURPOSE_GROUPS) - 1


def _link_rows(d: SimpleNamespace) -> list[LinkRow]:
    allowed = d.allowed_device_ids
    ranked: list[tuple[int, LinkRow]] = []
    for conn in d.conns:  # уже в порядке создания
        if conn.is_active is False:
            continue
        src = d.iface_map.get(conn.source_interface_id)
        dst = d.iface_map.get(conn.destination_interface_id)
        if not src or not dst:
            continue
        src_dev = d.device_map.get(src.physical_device_id)
        dst_dev = d.device_map.get(dst.physical_device_id)
        if not src_dev or not dst_dev:
            continue
        if allowed is not None and src_dev.id not in allowed and dst_dev.id not in allowed:
            continue
        rank = _purpose_rank(_port_roles(src, d) | _port_roles(dst, d))
        ranked.append((rank, LinkRow(
            left=f"{equipment_name(src_dev, d)} ({_device_label(src_dev)}) ({src.name})",
            right=f"{equipment_name(dst_dev, d)} ({_device_label(dst_dev)}) ({dst.name})",
            purpose=_PURPOSE_GROUPS[rank][1],
        )))
    ranked.sort(key=lambda pair: pair[0])  # сортировка устойчива: внутри группы порядок создания
    return [row for _rank, row in ranked]


def _stack_membership(session: Session) -> tuple[dict[str, str], dict[str, int]]:
    """(id устройства -> id стека, id устройства -> позиция в стеке)."""
    stack_of: dict[str, str] = {}
    position_of: dict[str, int] = {}
    for member in session.scalars(select(DeviceStackMember)).all():
        stack_of[member.physical_device_id] = member.stack_id
        position_of[member.physical_device_id] = member.position
    return stack_of, position_of


def _ordered_devices(devices: Iterable[Any], stack_of: dict[str, str], position_of: dict[str, int]) -> list[Any]:
    """Порядок создания; участники стека идут подряд на месте самого раннего из них."""
    devices = list(devices)
    anchor: dict[str, datetime] = {}
    for dev in devices:
        cluster = stack_of.get(dev.id, dev.id)
        created = _naive(dev.created_at)
        anchor[cluster] = min(anchor.get(cluster, created), created)
    return sorted(devices, key=lambda dev: (
        anchor[stack_of.get(dev.id, dev.id)], stack_of.get(dev.id, dev.id), position_of.get(dev.id, 0),
        _naive(dev.created_at), _device_label(dev).casefold(), dev.serial_number,
    ))


def _vlan_groups(devices: list[Any], stack_of: dict[str, str], d: SimpleNamespace) -> list[VlanGroup]:
    clusters: dict[str, list[Any]] = {}
    for dev in devices:  # devices уже упорядочены: стек остаётся на месте первого участника
        clusters.setdefault(stack_of.get(dev.id, dev.id), []).append(dev)

    groups: list[VlanGroup] = []
    for members in clusters.values():
        rows: dict[tuple[int, str, str], VlanRow] = {}
        for dev in members:
            for link in d.device_vlan_by_device.get(dev.id, []):
                vlan = d.vlan_map.get(link.vlan_id)
                if not vlan:
                    continue
                addressing = ""
                if link.ip_address:
                    addressing = f"{link.ip_address}/{link.prefix_length}" if link.prefix_length is not None else link.ip_address
                rows.setdefault((vlan.vlan_id, vlan.name, addressing), VlanRow(str(vlan.vlan_id), vlan.name, addressing))
        if not rows:
            continue
        first = members[0]
        device_type = d.device_types.get(first.device_type_id)
        names = list(dict.fromkeys(_device_label(m) for m in members if (m.system_name or "").strip()))
        serials = ", ".join(dict.fromkeys(m.serial_number for m in members))
        base_name = equipment_name(first, d)
        type_name = device_type.name if device_type else ""
        if type_name and base_name.casefold().startswith(type_name.casefold()):
            type_name = ""  # тип уже вписан в наименование («Маршрутизатор, Huawei AR651»)
        title = " ".join(part for part in (type_name, base_name) if part)
        if names:
            title += f" ({', '.join(names)})"
        title += f" ({serials})"
        ordered_rows = [rows[key] for key in sorted(rows, key=lambda k: (k[0], _natural(k[2]), k[1]))]
        groups.append(VlanGroup(title=title, rows=ordered_rows))
    return groups


def _management_ips(dev: Any, d: SimpleNamespace) -> list[str]:
    mgmt_ifaces = [i for i in d.ifaces_by_device.get(dev.id, []) if i.is_management]
    mgmt_vlans = [x for x in d.device_vlan_by_device.get(dev.id, []) if x.is_management]
    mgmt_subs = [x for x in d.subs_by_device.get(dev.id, []) if x.is_management]
    _ports, ips = device_management_ports_and_ips(
        mgmt_ifaces, d.ips_by_iface, mgmt_vlans, d.vlan_map,
        management_subinterfaces=mgmt_subs, ips_by_subinterface=d.ips_by_sub,
    )
    return list(dict.fromkeys(ip.split("/", 1)[0] for ip in ips))


def _equipment_rows(devices: list[Any], d: SimpleNamespace) -> list[EquipmentRow]:
    def placement_of(dev: Any) -> tuple[str, tuple[Optional[str], Optional[str]]]:
        room = d.rooms.get(dev.room_id)
        building = d.buildings.get(dev.building_id)
        label = (room.name if room else "") or (building.name if building else "")
        return label, (dev.building_id, dev.room_id)

    # Устройства одного помещения — подряд (иначе ячейку «Место размещения» не объединить), помещения
    # идут в порядке первого появления.
    first_seen: dict[tuple[Optional[str], Optional[str]], int] = {}
    for dev in devices:
        first_seen.setdefault(placement_of(dev)[1], len(first_seen))
    grouped = sorted(devices, key=lambda dev: first_seen[placement_of(dev)[1]])

    rows = []
    for dev in grouped:
        label, key = placement_of(dev)
        rows.append(EquipmentRow(
            name=equipment_name(dev, d), serial_number=dev.serial_number, system_name=(dev.system_name or "").strip(),
            management_ips=_management_ips(dev, d), placement=label, placement_key=key,
        ))
    return rows


def collect_structural_appendix(session: Session, structural_unit_ids: Optional[list[str]] = None) -> AppendixData:
    """Собирает данные трёх таблиц приложения. structural_unit_ids — тот же необязательный фильтр по
    структурным единицам, что и у регламентированного отчёта."""
    d = _load_report_data(session, None, structural_unit_ids)
    stack_of, position_of = _stack_membership(session)
    devices = _ordered_devices(d.devices, stack_of, position_of)
    return AppendixData(
        links=_link_rows(d),
        vlan_groups=_vlan_groups(devices, stack_of, d),
        equipment=_equipment_rows(devices, d),
    )
