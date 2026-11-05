"""
Построение графа диаграммы топологии сети из данных реестра (ТЗ, разделы 4.4, 6-8).

Решения по недосказанным в ТЗ деталям (раздел 16 говорит "нет открытых вопросов", но это
относится к категориям/иконкам/портам — ниже то, что ТЗ оставляет на усмотрение реализации):

1. Формат SavedDiagram.scope_filter (JSON, поле есть в модели, схема не задана):
   {"structural_unit_ids": [...], "building_ids": [...], "vlan_ids": [...],
    "device_category_ids": [...]}
   Пустой/отсутствующий фильтр — без ограничений (вся инфраструктура реестра). Между РАЗНЫМИ
   измерениями — AND, внутри одного измерения — OR. structural_unit_ids расширяется вложенными
   единицами через reporting.py:_expand_structural_unit_ids (раздел 7 ТЗ требует переиспользовать
   именно её, не дублировать).

2. group_by="vlan" для устройства в НЕСКОЛЬКИХ VLAN одновременно (транковый порт): группируется
   по VLAN, отмеченному как управляющий (PhysicalDeviceVLAN.is_management=True), если такой есть,
   иначе по VLAN с наименьшим числовым vlan_id — раздел 8 ТЗ этот случай не оговаривает.

3. Устройство без значения измерения (напр. без здания при group_by="building") получает
   group_key "<dimension>:none" с меткой "Без <измерения>" — попадает в свою группу, а не
   выпадает из диаграммы молча.

4. Раскладка узла, для которого ещё нет записи в DiagramLayout.node_positions (первая генерация
   диаграммы, DiagramLayout ещё не сохранён) — простая сеточная раскладка по индексу узла, а не
   полноценный иерархический алгоритм (DiagramLayout.auto_layout_algorithm="hierarchical" —
   поле-задел под будущее улучшение, не реализуется этим коммитом).

5. Порядковая позиция интерфейса среди интерфейсов устройства (раздел 4.4 — "каждый интерфейс
   получает порядковую позицию... ребро визуально подключается к засечке конкретного порта")
   передаётся полем port_index внутри source_interface/target_interface объекта ребра — единственное
   место контракта, где участвует конкретный интерфейс. Присутствует, когда ОДНОВРЕМЕННО: (а) узел
   на этом конце устройства сгенерирован автоматически (icon.mode == "generated" — у custom-значка
   нет вычисляемых засечек, анкерить не к чему), (б) этот конец ребра фактически отрисован как узел
   самого устройства, а не свёрнут в узел-группу (у узла-группы нет собственных засечек порта — см.
   GraphContext.device_supports_port_index) и (в) индекс интерфейса < MAX_PORT_TICKS (иначе интерфейс
   лежит за пределами отрисовываемых засечек — см. services/diagram_icons.MAX_PORT_TICKS). Раньше
   это было ограничено только shape="switch" — из-за этого многопортовые устройства других форм
   (сервер с несколькими сетевыми картами, файрвол с WAN/LAN/DMZ) на канвасе получали все свои рёбра
   в одной и той же точке узла.

Рёбра, у которых устройство хотя бы одного конца не входит в текущий scope_filter, не строятся —
на диаграмме физически нет второго узла, к которому их подключить.
"""
from __future__ import annotations

import json
import math
import uuid
from collections import defaultdict
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Building, Connection, ConnectionType, DeviceCategory, DeviceInterface, DeviceModel, DeviceSubinterface, DeviceType,
    DiagramGroupState, DiagramIcon, IPAddress, InterfaceVLAN, Manufacturer, PhysicalDevice,
    PhysicalDeviceVLAN, SavedDiagram, StructuralUnit, VLAN,
)
from ..constants import OwnerType
from .timeutil import utcnow_naive
from ..reporting import _expand_structural_unit_ids, device_label
from ..services.computed import ip_label
from .diagram_icons import MAX_PORT_TICKS, IconLookups, build_device_icon
from .port_config import DEFAULT_VLAN_MODE, VLAN_MODE_TRUNK
from .port_vlans import carries_all_vlans, effective_vlan_ids

GROUP_DIMENSIONS = ("structural_unit", "vlan", "building", "device_category")
UNASSIGNED_DIMENSION_VALUE = "none"
# Раскладка приходит от клиента (PUT /diagrams/{id}/layout) и хранится как JSON, поэтому при сборке графа ей нельзя
# доверять: одна запись вида {"id": "строка"} раньше роняла GET, пересборку и экспорт (500) до перезаписи раскладки.
# Позиция допустима, только если это объект с конечными числами x и y (bool — не число, NaN/Infinity из json.loads — не
# конечные); всё остальное при чтении молча заменяется сеточной позицией.
MAX_LAYOUT_NODES = 5000
MAX_LAYOUT_KEY_LENGTH = 200


def finite_number(value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # целое из сотен цифр не приводится к float: это не «конечное число» раскладки, а некорректное значение
        return False


def clean_position(raw) -> Optional[dict]:
    """{"x": число, "y": число} либо None, если позиция некорректна (лишние ключи отбрасываются)."""
    if not isinstance(raw, dict):
        return None
    x, y = raw.get("x"), raw.get("y")
    return {"x": x, "y": y} if finite_number(x) and finite_number(y) else None


def clean_positions_lenient(raw) -> dict[str, dict]:
    """Уже сохранённая раскладка: некорректные элементы отбрасываются, а не приводят к ошибке (для проверки входящих
    данных есть строгая api/diagrams.py:_clean_positions)."""
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, dict] = {}
    for key, position in raw.items():
        clean = clean_position(position)
        if isinstance(key, str) and clean is not None:
            cleaned[key] = clean
    return cleaned


GRID_COLUMNS = 6
GRID_STEP_X = 220
GRID_STEP_Y = 160

_DIMENSION_EMPTY_LABEL = {
    "structural_unit": "Без структурной единицы",
    "vlan": "Без VLAN",
    "building": "Без здания",
    "device_category": "Без категории",
}


def parse_scope_filter(raw: str) -> dict:
    try:
        data = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        data = {}
    return data if isinstance(data, dict) else {}


def _load_all(session: Session, model) -> dict:
    return {row.id: row for row in session.scalars(select(model)).all()}


class GraphContext:
    """Все справочники реестра, загруженные ОДНИМ проходом (без N+1 запроса на устройство) —
    переиспользуются на всех этапах построения графа: фильтрация охвата, узлы, рёбра, группировка."""

    def __init__(self, session: Session):
        self.devices = _load_all(session, PhysicalDevice)
        self.device_types = _load_all(session, DeviceType)
        self.categories = _load_all(session, DeviceCategory)
        self.manufacturers = _load_all(session, Manufacturer)
        self.models = _load_all(session, DeviceModel)
        self.icons = _load_all(session, DiagramIcon)
        self.buildings = _load_all(session, Building)
        self.structural_units = _load_all(session, StructuralUnit)
        self.vlans = _load_all(session, VLAN)
        self.connection_types = _load_all(session, ConnectionType)

        self.interfaces_by_device: dict[str, list[DeviceInterface]] = defaultdict(list)
        for iface in session.scalars(select(DeviceInterface).order_by(DeviceInterface.created_at, DeviceInterface.id)).all():
            self.interfaces_by_device[iface.physical_device_id].append(iface)
        self.interfaces_by_id = {i.id: i for ifaces in self.interfaces_by_device.values() for i in ifaces}

        self.interface_ips_by_interface: dict[str, list[IPAddress]] = defaultdict(list)
        for ip in session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE)).all():
            self.interface_ips_by_interface[ip.owner_id].append(ip)

        # Подинтерфейсы портов: их IP попадают в IP узла устройства, а VLAN — во VLAN ребра порта-родителя
        # (подинтерфейс на VLAN 10 — это VLAN 10 на линии). Порядок — по номеру VLAN, затем по имени.
        self.subinterfaces_by_interface: dict[str, list[DeviceSubinterface]] = defaultdict(list)
        subinterfaces = session.scalars(select(DeviceSubinterface)).all()
        subinterfaces.sort(key=lambda sub: (self.vlans[sub.vlan_id].vlan_id if sub.vlan_id in self.vlans else 0, sub.name.casefold(), sub.id))
        for sub in subinterfaces:
            self.subinterfaces_by_interface[sub.parent_interface_id].append(sub)
        self.subinterface_ips_by_subinterface: dict[str, list[IPAddress]] = defaultdict(list)
        for ip in session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_SUBINTERFACE)).all():
            self.subinterface_ips_by_subinterface[ip.owner_id].append(ip)

        self.device_vlans_by_device: dict[str, list[PhysicalDeviceVLAN]] = defaultdict(list)
        for link in session.scalars(select(PhysicalDeviceVLAN)).all():
            self.device_vlans_by_device[link.physical_device_id].append(link)

        # VLAN порта: выбранные (interface_vlans) или, у порта с «Все VLAN», — все VLAN его устройства (services/port_vlans.py).
        self.interface_vlan_ids_by_interface: dict[str, list[str]] = defaultdict(list)
        all_vlans_ids = {i.id for i in self.interfaces_by_id.values() if carries_all_vlans(i)}
        for link in session.scalars(select(InterfaceVLAN)).all():
            if link.interface_id not in all_vlans_ids:
                self.interface_vlan_ids_by_interface[link.interface_id].append(link.vlan_id)
        if all_vlans_ids:
            for interface_id, vlan_ids in effective_vlan_ids(session, all_vlans_ids).items():
                self.interface_vlan_ids_by_interface[interface_id] = sorted(vlan_ids, key=lambda v: (self.vlans[v].vlan_id if v in self.vlans else 0, v))

        self.connections = list(session.scalars(select(Connection)).all())

        self.icon_lookups = IconLookups(
            device_types_by_id=self.device_types,
            categories_by_id=self.categories,
            manufacturers_by_id=self.manufacturers,
            models_by_id=self.models,
            icons_by_id=self.icons,
        )

    def interface_count(self, device_id: str) -> int:
        return len(self.interfaces_by_device.get(device_id, []))

    def interface_index(self, interface: DeviceInterface) -> int:
        """Порядковая позиция (с нуля) интерфейса среди интерфейсов его устройства, по порядку
        создания записи — см. пункт 5 в docstring модуля."""
        return self.interfaces_by_device.get(interface.physical_device_id, []).index(interface)

    def device_vlan_ids(self, device_id: str) -> set[str]:
        ids = {link.vlan_id for link in self.device_vlans_by_device.get(device_id, [])}
        for iface in self.interfaces_by_device.get(device_id, []):
            ids.update(self.interface_vlan_ids_by_interface.get(iface.id, []))
        return ids

    def management_vlan_id(self, device_id: str) -> Optional[str]:
        for link in self.device_vlans_by_device.get(device_id, []):
            if link.is_management:
                return link.vlan_id
        return None

    def device_supports_port_index(self, device: PhysicalDevice) -> bool:
        """Есть ли у устройства вычисляемые засечки порта, к которым на канвасе можно анкерить
        Handle (см. пункт 5 в docstring модуля). Верно для ЛЮБОЙ формы сгенерированного значка —
        единственное, что исключает анкеринг, это custom-значок (произвольный SVG администратора,
        для которого нет вычисляемой геометрии засечек)."""
        icon = build_device_icon(device, self.interface_count(device.id), self.icon_lookups)
        return icon.get("mode") == "generated"


def _filter_device_ids(ctx: GraphContext, scope_filter: dict) -> set[str]:
    """Устройство проходит фильтр, если удовлетворяет ВСЕМ измерениям, заданным в scope_filter
    (AND между измерениями заданными одновременно); внутри одного измерения — попадание в ЛЮБОЙ
    из перечисленных id (OR). Ни одно измерение не задано — фильтр не активен, разрешены все."""
    allowed = set(ctx.devices.keys())

    structural_unit_ids = scope_filter.get("structural_unit_ids")
    if structural_unit_ids:
        expanded = _expand_structural_unit_ids(ctx.structural_units, structural_unit_ids)
        allowed_building_ids = {b.id for b in ctx.buildings.values() if b.structural_unit_id in expanded}
        allowed &= {d.id for d in ctx.devices.values() if d.building_id in allowed_building_ids}

    building_ids = scope_filter.get("building_ids")
    if building_ids:
        wanted = set(building_ids)
        allowed &= {d.id for d in ctx.devices.values() if d.building_id in wanted}

    device_category_ids = scope_filter.get("device_category_ids")
    if device_category_ids:
        wanted = set(device_category_ids)
        matching: set[str] = set()
        for d in ctx.devices.values():
            device_type = ctx.device_types.get(d.device_type_id)
            if device_type and device_type.category_id in wanted:
                matching.add(d.id)
        allowed &= matching

    vlan_ids = scope_filter.get("vlan_ids")
    if vlan_ids:
        wanted = set(vlan_ids)
        allowed &= {d.id for d in ctx.devices.values() if ctx.device_vlan_ids(d.id) & wanted}

    return allowed


def _group_dimension_value(device: PhysicalDevice, group_by: str, ctx: GraphContext) -> Optional[str]:
    if group_by == "building":
        return device.building_id
    if group_by == "structural_unit":
        building = ctx.buildings.get(device.building_id) if device.building_id else None
        return building.structural_unit_id if building else None
    if group_by == "device_category":
        device_type = ctx.device_types.get(device.device_type_id)
        return device_type.category_id if device_type else None
    if group_by == "vlan":
        management_vlan = ctx.management_vlan_id(device.id)
        if management_vlan:
            return management_vlan
        vlan_ids = ctx.device_vlan_ids(device.id)
        if not vlan_ids:
            return None
        return min(vlan_ids, key=lambda vid: ctx.vlans[vid].vlan_id if vid in ctx.vlans else 0)
    raise ValueError(f"Неизвестное измерение группировки: {group_by!r}")


def group_key_for_device(device: PhysicalDevice, group_by: str, ctx: GraphContext) -> str:
    value = _group_dimension_value(device, group_by, ctx)
    return f"{group_by}:{value if value is not None else UNASSIGNED_DIMENSION_VALUE}"


def _group_label(group_by: str, dimension_id: str, ctx: GraphContext, device_count: int) -> str:
    if dimension_id == UNASSIGNED_DIMENSION_VALUE:
        name = _DIMENSION_EMPTY_LABEL.get(group_by, "Без группы")
    elif group_by == "structural_unit":
        name = ctx.structural_units[dimension_id].name if dimension_id in ctx.structural_units else "?"
    elif group_by == "building":
        name = ctx.buildings[dimension_id].name if dimension_id in ctx.buildings else "?"
    elif group_by == "device_category":
        name = ctx.categories[dimension_id].name if dimension_id in ctx.categories else "?"
    elif group_by == "vlan":
        vlan = ctx.vlans.get(dimension_id)
        name = f"VLAN {vlan.vlan_id} {vlan.name}" if vlan else "?"
    else:
        name = "?"
    return f"{name} ({device_count})"


def _insert_missing_group_states(session: Session, states: list[DiagramGroupState]) -> None:
    """Вставляет новые состояния групп, не падая при гонке: параллельный regenerate/создание, успевший вставить ту же пару
    (saved_diagram_id, group_key), даёт нарушение uq_diagram_group_state, и «проверить, затем вставить» через session.add
    заканчивалось необработанным IntegrityError (500). ``INSERT … ON CONFLICT DO NOTHING`` оставляет строку победителя; для
    остальных СУБД — прежний session.add. Состояния после вставки нужно перечитать (core-вставка не заполняет сессию)."""
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    elif dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        session.add_all(states)
        return
    now = utcnow_naive()
    rows = [
        {
            "id": state.id or str(uuid.uuid4()),
            "saved_diagram_id": state.saved_diagram_id,
            "group_key": state.group_key,
            "is_collapsed": state.is_collapsed,
            "device_count": state.device_count,
            "custom_threshold": None,
            "created_at": now,
            "updated_at": now,
        }
        for state in states
    ]
    session.execute(dialect_insert(DiagramGroupState).on_conflict_do_nothing(index_elements=["saved_diagram_id", "group_key"]), rows)


def apply_grouping(
    session: Session, saved_diagram: SavedDiagram, group_counts: dict[str, int], *, persist: bool = True
) -> dict[str, DiagramGroupState]:
    """Раздел 8 ТЗ. Группа НИЖЕ порога без существующей записи не получает DiagramGroupState вообще —
    отсутствие записи трактуется как "не свёрнута" (см. build_graph). Существующая запись никогда не получает
    переписанный is_collapsed/custom_threshold — только device_count обновляется при каждом regenerate.

    ``persist=True`` (создание и regenerate диаграммы): создаёт недостающие и обновляет device_count существующих состояний в
    переданной сессии (commit — забота вызывающего кода); одновременное создание той же записи другим запросом не
    приводит к ошибке (см. _insert_missing_group_states).

    ``persist=False`` (чтение диаграммы и экспорт): сессия не изменяется. Для группы выше порога без записи возвращается
    несохранённое состояние ``is_collapsed=True`` — результат тот же, что дала бы запись, но безопасный метод GET не
    меняет данные (в том числе от имени роли viewer) и не конкурирует с другими запросами; device_count у существующих
    записей не обновляется (граф берёт число устройств из текущего расчёта, а не из записи)."""
    existing = {
        s.group_key: s
        for s in session.scalars(select(DiagramGroupState).where(DiagramGroupState.saved_diagram_id == saved_diagram.id)).all()
    }
    result: dict[str, DiagramGroupState] = {}
    created: list[DiagramGroupState] = []
    for group_key, device_count in group_counts.items():
        state = existing.get(group_key)
        if state is not None:
            if persist:
                state.device_count = device_count
            result[group_key] = state
            continue
        threshold = saved_diagram.collapse_threshold
        if device_count >= threshold:
            # Только внешний ключ, без relationship: иначе backref-каскад добавил бы объект в сессию даже при persist=False.
            state = DiagramGroupState(
                id=str(uuid.uuid4()), saved_diagram_id=saved_diagram.id, group_key=group_key, is_collapsed=True, device_count=device_count
            )
            created.append(state)
            result[group_key] = state
    if persist and created:
        session.flush()  # отложенные изменения (device_count существующих записей) — до core-вставки
        _insert_missing_group_states(session, created)
        stored = {
            s.group_key: s
            for s in session.scalars(
                select(DiagramGroupState).where(
                    DiagramGroupState.saved_diagram_id == saved_diagram.id, DiagramGroupState.group_key.in_([s.group_key for s in created])
                )
            ).all()
        }
        for state in created:
            result[state.group_key] = stored.get(state.group_key, state)  # победитель гонки, если вставила другая транзакция
    return result


def _build_ip_addresses(device: PhysicalDevice, ctx: GraphContext) -> list[dict]:
    """Раздел 4.4 ТЗ: объединение IPAddress (owner_type="device_interface") всех интерфейсов
    устройства и PhysicalDeviceVLAN.ip_address, без дублей (по итоговому отформатированному адресу)."""
    addresses: list[dict] = []
    seen: set[str] = set()
    for iface in ctx.interfaces_by_device.get(device.id, []):
        for ip in ctx.interface_ips_by_interface.get(iface.id, []):
            address = ip_label(ip)
            if address in seen:
                continue
            seen.add(address)
            addresses.append({"address": address, "purpose": ip.purpose, "is_management": ip.is_management})
        # IP подинтерфейсов порта — тем же списком; назначение начинается с имени подинтерфейса
        # («Gi0/0.10: Шлюз»), иначе на узле не видно, на каком логическом интерфейсе адрес.
        for sub in ctx.subinterfaces_by_interface.get(iface.id, []):
            for ip in ctx.subinterface_ips_by_subinterface.get(sub.id, []):
                address = ip_label(ip)
                if address in seen:
                    continue
                seen.add(address)
                addresses.append({"address": address, "purpose": f"{sub.name}: {ip.purpose}" if ip.purpose else sub.name, "is_management": ip.is_management})
    for link in ctx.device_vlans_by_device.get(device.id, []):
        if not link.ip_address:
            continue
        address = ip_label(link)
        if address in seen:
            continue
        seen.add(address)
        addresses.append({"address": address, "purpose": None, "is_management": link.is_management})
    return addresses


def build_device_node(device: PhysicalDevice, ctx: GraphContext, position: dict) -> dict:
    device_type = ctx.device_types.get(device.device_type_id)
    manufacturer = ctx.manufacturers.get(device.manufacturer_id) if device.manufacturer_id else None
    model = ctx.models.get(device.model_id) if device.model_id else None
    return {
        "id": device.id,
        "type": "device",
        "label": device_label(device),
        "serial_number": device.serial_number,
        "system_name": device.system_name,
        "category_id": device_type.category_id if device_type else None,
        "manufacturer": manufacturer.name if manufacturer else None,
        "model": model.model if model else None,
        "ip_addresses": _build_ip_addresses(device, ctx),
        "icon": build_device_icon(device, ctx.interface_count(device.id), ctx.icon_lookups),
        "x": position.get("x", 0),
        "y": position.get("y", 0),
    }


def build_group_node(group_key: str, label: str, device_count: int, position: dict) -> dict:
    return {
        "id": f"group:{group_key}",
        "type": "group",
        "label": label,
        "device_count": device_count,
        "x": position.get("x", 0),
        "y": position.get("y", 0),
    }


def _interface_ref(interface: Optional[DeviceInterface], supports_port_index: bool, ctx: GraphContext) -> Optional[dict]:
    if interface is None:
        return None
    ref = {"id": interface.id, "name": interface.name}
    if supports_port_index:
        index = ctx.interface_index(interface)
        if index < MAX_PORT_TICKS:
            ref["port_index"] = index
    return ref


def _is_trunk_connection(*interfaces: Optional[DeviceInterface]) -> bool:
    """Подключение — trunk, если все известные его концы в режиме trunk (порт без явного режима тоже trunk, как
    у колонки DeviceInterface.vlan_mode). Если режимы концов разошлись (access ↔ trunk — это отдельная
    ошибка конфигурации, см. services/port_config.py), подключение trunk не считается: на диаграмме остаётся
    список VLAN, из которого расхождение видно. Нет ни одного известного конца — не trunk."""
    known = [iface for iface in interfaces if iface is not None]
    return bool(known) and all((iface.vlan_mode or DEFAULT_VLAN_MODE) == VLAN_MODE_TRUNK for iface in known)


def build_edge(connection: Connection, ctx: GraphContext, source_node_id: str, target_node_id: str) -> dict:
    """Раздел 4.4 ТЗ. `source_node_id`/`target_node_id` уже разрешены вызывающим кодом
    (build_graph) на устройство или на границу свёрнутой группы — сама эта функция приоритет
    группировки не выбирает, только собирает контракт ребра."""
    source_iface = ctx.interfaces_by_id.get(connection.source_interface_id)
    target_iface = ctx.interfaces_by_id.get(connection.destination_interface_id)
    source_device = ctx.devices.get(source_iface.physical_device_id) if source_iface else None
    target_device = ctx.devices.get(target_iface.physical_device_id) if target_iface else None
    # `source_node_id == source_device.id` проверяет, что этот конец ребра отрисован как узел
    # САМОГО устройства, а не свёрнут в узел-группу (build_graph.resolve_node_id) — у узла-группы
    # нет своих засечек порта, анкерить туда конкретный port_index было бы некуда (см. пункт 5
    # docstring модуля).
    source_supports_port_index = bool(
        source_device is not None and source_node_id == source_device.id and ctx.device_supports_port_index(source_device)
    )
    target_supports_port_index = bool(
        target_device is not None and target_node_id == target_device.id and ctx.device_supports_port_index(target_device)
    )

    vlans: dict[str, dict] = {}
    for iface in (source_iface, target_iface):
        if iface is None:
            continue
        for vlan_id in ctx.interface_vlan_ids_by_interface.get(iface.id, []):
            vlan = ctx.vlans.get(vlan_id)
            if vlan and vlan.id not in vlans:
                vlans[vlan.id] = {"id": vlan.id, "vlan_id": vlan.vlan_id, "name": vlan.name}
        # VLAN подинтерфейсов порта: тегированный трафик подинтерфейса идёт по той же линии.
        for sub in ctx.subinterfaces_by_interface.get(iface.id, []):
            vlan = ctx.vlans.get(sub.vlan_id)
            if vlan and vlan.id not in vlans:
                vlans[vlan.id] = {"id": vlan.id, "vlan_id": vlan.vlan_id, "name": vlan.name}

    connection_type = ctx.connection_types.get(connection.connection_type_id)
    return {
        "id": connection.id,
        "source_node_id": source_node_id,
        "source_interface": _interface_ref(source_iface, source_supports_port_index, ctx),
        "target_node_id": target_node_id,
        "target_interface": _interface_ref(target_iface, target_supports_port_index, ctx),
        "connection_type": connection_type.name if connection_type else None,
        "is_active": connection.is_active,
        "is_trunk": _is_trunk_connection(source_iface, target_iface),
        "vlans": list(vlans.values()),
    }


def _grid_position(index: int) -> dict:
    return {"x": (index % GRID_COLUMNS) * GRID_STEP_X, "y": (index // GRID_COLUMNS) * GRID_STEP_Y}


def build_graph(
    session: Session, saved_diagram: SavedDiagram, *, node_positions: Optional[dict] = None, persist: bool = True
) -> dict:
    """Точка входа: собирает {"nodes": [...], "edges": [...]} для GET /diagrams/{id} (раздел 4.4/7
    ТЗ). `node_positions` — уже распарсенный DiagramLayout.node_positions текущей диаграммы (пусто при первой генерации).

    ``persist=True`` (создание, regenerate): сохраняет состояния групп (см. apply_grouping) — вызывающий код (роутер)
    отвечает за commit. ``persist=False`` (GET диаграммы, экспорт): ничего не пишет в сессию; свёрнутость групп выше порога
    считается в памяти, результат графа тот же."""
    ctx = GraphContext(session)
    node_positions = clean_positions_lenient(node_positions)
    scope_filter = parse_scope_filter(saved_diagram.scope_filter)
    device_ids = _filter_device_ids(ctx, scope_filter)

    group_key_by_device: dict[str, str] = {}
    devices_by_group: dict[str, list[str]] = defaultdict(list)
    for device_id in device_ids:
        device = ctx.devices[device_id]
        key = group_key_for_device(device, saved_diagram.group_by, ctx)
        group_key_by_device[device_id] = key
        devices_by_group[key].append(device_id)

    group_states = apply_grouping(session, saved_diagram, {k: len(v) for k, v in devices_by_group.items()}, persist=persist)
    collapsed_keys = {key for key, state in group_states.items() if state.is_collapsed}

    nodes: list[dict] = []
    node_index = 0
    for device_id in sorted(device_ids):
        key = group_key_by_device[device_id]
        if key in collapsed_keys:
            continue
        device = ctx.devices[device_id]
        position = node_positions.get(device_id) or _grid_position(node_index)  # node_positions уже очищены (clean_positions_lenient)
        nodes.append(build_device_node(device, ctx, position))
        node_index += 1

    for key in sorted(collapsed_keys):
        group_by, _, dimension_id = key.partition(":")
        node_id = f"group:{key}"
        position = node_positions.get(node_id) or _grid_position(node_index)
        label = _group_label(group_by, dimension_id, ctx, len(devices_by_group[key]))
        nodes.append(build_group_node(key, label, len(devices_by_group[key]), position))
        node_index += 1

    def resolve_node_id(device_id: str) -> str:
        key = group_key_by_device[device_id]
        return f"group:{key}" if key in collapsed_keys else device_id

    edges: list[dict] = []
    for connection in ctx.connections:
        source_iface = ctx.interfaces_by_id.get(connection.source_interface_id)
        target_iface = ctx.interfaces_by_id.get(connection.destination_interface_id)
        if source_iface is None or target_iface is None:
            continue
        source_device_id = source_iface.physical_device_id
        target_device_id = target_iface.physical_device_id
        if source_device_id not in device_ids or target_device_id not in device_ids:
            continue  # другой конец не входит в текущий охват диаграммы
        source_node_id = resolve_node_id(source_device_id)
        target_node_id = resolve_node_id(target_device_id)
        if source_node_id == target_node_id and source_node_id.startswith("group:"):
            continue  # внутригрупповое ребро — не рисуется (раздел 4.4 ТЗ)
        edges.append(build_edge(connection, ctx, source_node_id, target_node_id))

    return {"nodes": nodes, "edges": edges}
