"""
Дескриптор иконки узла диаграммы топологии сети (ТЗ, раздел 4.3). Иконка ВЫЧИСЛЯЕТСЯ, а не
выбирается из готового набора — так автоматически покрывается любое сочетание категории/
производителя/модели/числа портов без необходимости рисовать иконку под каждую новую модель
оборудования вручную. Дескриптор — единственный источник правды для всех четырёх мест отрисовки
(интерактивный канвас на фронтенде, экспорт .svg/.drawio/.vsdx на бэкенде).

Реальные товарные знаки/логотипы не воспроизводятся — только текстовая подпись производителя/
модели и цвет категории (см. manufacturer_label/model_label ниже).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models import DeviceCategory, DeviceModel, DeviceType, DiagramIcon, Manufacturer, PhysicalDevice

MAX_PORT_TICKS = 32
DEFAULT_SHAPE = "generic"
DEFAULT_COLOR = "#9aa0a6"  # "default нейтральный серый" (раздел 4.3 ТЗ)


@dataclass(frozen=True)
class IconLookups:
    """Общие словари подстановки id -> объект, единожды собранные вызывающим кодом (сервис
    построения графа, см. services/diagram_graph.py) для ВСЕХ узлов диаграммы разом — без
    N+1 запроса на каждое устройство при построении графа."""
    device_types_by_id: dict[str, DeviceType] = field(default_factory=dict)
    categories_by_id: dict[str, DeviceCategory] = field(default_factory=dict)
    manufacturers_by_id: dict[str, Manufacturer] = field(default_factory=dict)
    models_by_id: dict[str, DeviceModel] = field(default_factory=dict)
    icons_by_id: dict[str, DiagramIcon] = field(default_factory=dict)


def resolve_category_style(category: Optional[DeviceCategory], categories_by_id: dict[str, DeviceCategory]) -> tuple[str, str]:
    """Подъём по иерархии DeviceCategory.parent_id до ближайшего предка (включительно) с
    непустым diagram_shape/diagram_color (раздел 4.1/4.3 ТЗ). shape и color разрешаются
    НЕЗАВИСИМО друг от друга — у промежуточной категории может быть задан только один из двух
    (напр. "Коммутаторы" задаёт shape, а color наследует от родителя "Сетевая инфраструктура").
    `seen` защищает от зацикливания на случай повреждённых данных (parent_id по кругу)."""
    shape: Optional[str] = None
    color: Optional[str] = None
    node = category
    seen: set[str] = set()
    while node is not None and node.id not in seen:
        seen.add(node.id)
        if shape is None and node.diagram_shape:
            shape = node.diagram_shape
        if color is None and node.diagram_color:
            color = node.diagram_color
        if shape is not None and color is not None:
            break
        node = categories_by_id.get(node.parent_id) if node.parent_id else None
    return shape or DEFAULT_SHAPE, color or DEFAULT_COLOR


def port_ticks_for_count(interface_count: int) -> tuple[int, Optional[int]]:
    """Раздел 4.3 ТЗ: при количестве интерфейсов больше MAX_PORT_TICKS отрисовываются
    MAX_PORT_TICKS засечек и общее число — числовым бейджем +N рядом (чтобы SVG не раздувался на
    устройствах с сотнями портов). Возвращает (число засечек к отрисовке, overflow либо None)."""
    if interface_count < 0:
        raise ValueError("interface_count не может быть отрицательным")
    if interface_count <= MAX_PORT_TICKS:
        return interface_count, None
    return MAX_PORT_TICKS, interface_count - MAX_PORT_TICKS


def resolve_custom_icon(device: PhysicalDevice, model: Optional[DeviceModel], icons_by_id: dict[str, DiagramIcon]) -> Optional[DiagramIcon]:
    """Раздел 4.3 ТЗ, приоритет ручного переопределения по убыванию:
    1. PhysicalDevice.diagram_icon_id — своя иконка для конкретного устройства.
    2. DeviceModel.diagram_icon_id — своя иконка сразу для всех устройств этой модели.
    Ссылка на несуществующую/удалённую иконку молча игнорируется (падать в дескрипторе иконки
    не тот уровень, где стоит валить построение всего графа) — итог просто откатывается на
    автогенерацию, как если бы переопределения не было."""
    if device.diagram_icon_id and device.diagram_icon_id in icons_by_id:
        return icons_by_id[device.diagram_icon_id]
    if model is not None and model.diagram_icon_id and model.diagram_icon_id in icons_by_id:
        return icons_by_id[model.diagram_icon_id]
    return None


def build_device_icon(device: PhysicalDevice, interface_count: int, lookups: IconLookups) -> dict:
    """Собирает icon-часть контракта узла-устройства (раздел 4.4 ТЗ): либо
    {"mode": "custom", "svg_markup": ...}, либо
    {"mode": "generated", "shape":..., "color":..., "port_ticks":..., "manufacturer_label":...,
    "model_label":...}.

    Пример вызова (lookups собирает services/diagram_graph.py одним проходом по всем узлам):
        icon = build_device_icon(device, interface_count=len(device_interfaces), lookups=lookups)
    """
    model = lookups.models_by_id.get(device.model_id) if device.model_id else None
    custom_icon = resolve_custom_icon(device, model, lookups.icons_by_id)
    if custom_icon is not None:
        return {"mode": "custom", "svg_markup": custom_icon.svg_markup}

    device_type = lookups.device_types_by_id.get(device.device_type_id)
    category = lookups.categories_by_id.get(device_type.category_id) if device_type else None
    shape, color = resolve_category_style(category, lookups.categories_by_id)

    descriptor = {"mode": "generated", "shape": shape, "color": color}
    if shape == "switch":
        port_ticks, port_overflow = port_ticks_for_count(interface_count)
        descriptor["port_ticks"] = port_ticks
        if port_overflow:
            descriptor["port_overflow"] = port_overflow

    manufacturer = lookups.manufacturers_by_id.get(device.manufacturer_id) if device.manufacturer_id else None
    descriptor["manufacturer_label"] = manufacturer.name if manufacturer else ""
    descriptor["model_label"] = model.model if model else ""
    return descriptor
