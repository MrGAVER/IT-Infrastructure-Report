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

import re
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException

from ..models import DeviceCategory, DeviceModel, DeviceType, DiagramIcon, Manufacturer, PhysicalDevice

MAX_PORT_TICKS = 32
DEFAULT_SHAPE = "generic"
DEFAULT_COLOR = "#9aa0a6"  # "default нейтральный серый" (раздел 4.3 ТЗ)

# Иконка категории поверх прямоугольника узла — не силуэт конкретного устройства/бренда (раздел
# 4.3 ТЗ: "реальные товарные знаки/логотипы не воспроизводятся"), а обобщённый, отраслевой символ
# того типа, каким его рисуют сетевые инженеры на любой схеме топологии (коммутатор — корпус с
# портами, маршрутизатор — компас из стрелок, файрвол — кирпичная стена и т.д.) — не оригинальная
# иконка конкретного производителя. Раньше это был один плоский <path> малого размера (Фаза 2, п.2
# плана доработок экспорта диаграмм) — по итогам Фазы 3 (находка №5, "кастомные SVG-иконки")
# переработан в полноценный, узнаваемый значок: несколько примитивов (rect/circle/path) БЕЗ
# жёсткого fill/stroke на дочерних элементах — оба наследуются от обёртки (тот же приём, что и у
# custom-иконок, см. svg_markup ниже), чтобы один и тот же фрагмент разметки одинаково работал и
# белым по цветной заливке узла, и тёмным на светлом фоне легенды (Фаза 3, п.1). Координаты — в
# системе viewBox "0 0 24 24" (см. GLYPH_VIEWBOX); фронтенд отрисовывает эту же разметку без
# изменений (см. DiagramDeviceNode.vue).
SHAPE_GLYPHS: dict[str, str] = {
    "server": (
        '<rect x="4" y="2" width="16" height="20" rx="1.4" fill="none" stroke="currentColor" stroke-width="1.6"/>'
        '<path d="M4 9h16M4 16h16" stroke="currentColor" stroke-width="1.4"/>'
        '<circle cx="7.2" cy="5.5" r="1"/><circle cx="7.2" cy="12.5" r="1"/><circle cx="7.2" cy="19.2" r="1"/>'
        '<path d="M11 5.5h6M11 12.5h6M11 19.2h6" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>'
    ),
    # switch_l2/switch_l3/router появились позже (см. диаграмма-графа "Пункт 5 правки"): до этого
    # L2/L3-коммутаторы получали общий 'switch' (три порта), маршрутизатор — 'generic' (ромб)
    # вместе с точками Wi-Fi/GSM-модемами. 'switch' — общий сейчас неиспользуемый (не назначается
    # ни одной категорией напрямую, см. resolve_category_style) фолбэк-алиас на switch_l2, на
    # случай если какая-то будущая категория укажет ровно "switch": корпус с портами и стрелками
    # переключения кадров — тот же символ, что и у switch_l2. switch_l3 — то же самое плюс
    # треугольная "крыша" сверху (маршрутизация поверх коммутации). router — круг со спицами-
    # стрелками на все 4 стороны (компас) — устоявшийся в сетевых схемах символ маршрутизатора,
    # визуально не похожий ни на один из значков коммутаторов.
    "switch_l2": (
        '<rect x="2" y="6" width="20" height="9" rx="1.4" fill="none" stroke="currentColor" stroke-width="1.6"/>'
        '<path d="M5.5 15v3.2M9.5 15v3.2M14.5 15v3.2M18.5 15v3.2" stroke="currentColor" stroke-width="1.4"/>'
        '<path d="M6.5 10.5h4.5M9.5 8.8l1.7 1.7-1.7 1.7" stroke="currentColor" stroke-width="1.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M17.5 10.5h-4.5M14.5 8.8l-1.7 1.7 1.7 1.7" stroke="currentColor" stroke-width="1.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "switch_l3": (
        '<rect x="2" y="9" width="20" height="9" rx="1.4" fill="none" stroke="currentColor" stroke-width="1.6"/>'
        '<path d="M5.5 18v3.2M9.5 18v3.2M14.5 18v3.2M18.5 18v3.2" stroke="currentColor" stroke-width="1.4"/>'
        '<path d="M6.5 13.5h4.5M9.5 11.8l1.7 1.7-1.7 1.7" stroke="currentColor" stroke-width="1.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M17.5 13.5h-4.5M14.5 11.8l-1.7 1.7 1.7 1.7" stroke="currentColor" stroke-width="1.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M12 1.5 15 6.5H9z"/>'
    ),
    "router": (
        '<circle cx="12" cy="12" r="6.5" fill="none" stroke="currentColor" stroke-width="1.6"/>'
        '<path d="M12 2.2v3.3M12 18.5v3.3M2.2 12h3.3M18.5 12h3.3" stroke="currentColor" stroke-width="1.6" fill="none"/>'
        '<path d="M12 1.2 10.6 4h2.8zM12 22.8 10.6 20h2.8zM1.2 12 4 10.6v2.8zM22.8 12 20 10.6v2.8z"/>'
    ),
    "firewall": (
        '<rect x="2" y="3" width="20" height="18" rx="1" fill="none" stroke="currentColor" stroke-width="1.6"/>'
        '<path d="M2 8h20M2 13h20M2 18h20M7 3v5M12 8v5M17 3v5M7 13v5M17 13v5M12 18v3" stroke="currentColor" stroke-width="1.3"/>'
    ),
    "workstation": (
        '<rect x="2" y="3" width="20" height="13" rx="1.2" fill="none" stroke="currentColor" stroke-width="1.6"/>'
        '<path d="M9 20.5h6M12 16v4.5M6 19.5h12" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" fill="none"/>'
    ),
    "peripheral": (
        '<rect x="3" y="8" width="18" height="9" rx="1.2" fill="none" stroke="currentColor" stroke-width="1.6"/>'
        '<path d="M6 8V4h12v4" fill="none" stroke="currentColor" stroke-width="1.6"/>'
        '<rect x="7" y="17" width="10" height="5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
        '<circle cx="17.5" cy="11" r="0.9"/>'
    ),
    "generic": '<path d="M12 2 22 12 12 22 2 12z" fill="none" stroke="currentColor" stroke-width="1.6"/>',
}
# "switch" (без L2/L3) — для обратной совместимости со старыми записями категорий (тип
# DiagramIconShape на фронтенде до сих пор допускает это значение) — тот же символ, что и у
# switch_l2, см. комментарий выше про происхождение switch_l2/switch_l3/router.
SHAPE_GLYPHS["switch"] = SHAPE_GLYPHS["switch_l2"]
GLYPH_VIEWBOX = (24, 24)  # ширина, высота системы координат SHAPE_GLYPHS-разметки

# Код-ревью п.3.1 (критичная уязвимость): DiagramIcon.svg_markup попадает без изменений и в
# экспортируемый .svg (services/diagram_export.py), и во фронтенд через v-html
# (DiagramDeviceNode.vue, DeviceIconPicker.vue). SVG — исполняемый формат: <script>,
# <foreignObject> (может содержать произвольный HTML) и обработчики событий (onload, onerror и
# т.п.) выполняются в браузере при рендеринге. Пользователь с правом на управление каталогом
# иконок мог бы разместить payload, который выполнится в браузере ЛЮБОГО, кто откроет диаграмму
# — включая администратора — и похитить токен сессии из localStorage.
#
# Это allow-list по СИМПТОМАМ (запрещённые конструкции), а не по тегам/атрибутам — сознательный
# компромисс: полноценный allow-list тегов SVG (path/circle/rect/g/...) потребовал бы разбора
# XML и легко ломался бы на легитимной разметке (иконки — это готовый SVG из внешних редакторов,
# не рукописный минимальный набор фигур). Основные вектора исполнения кода в SVG перечислены
# явно; остаётся компромисс между удобством ввода и полнотой защиты — см. README, раздел
# «Известные ограничения».
_FORBIDDEN_SVG_PATTERN = re.compile(
    r"<\s*script|<\s*foreignobject|on\w+\s*=|javascript\s*:", re.IGNORECASE
)


def validate_svg_markup(svg_markup: str | None) -> None:
    """Бросает HTTPException(422), если svg_markup содержит конструкции, способные выполнить
    код в браузере (см. комментарий у _FORBIDDEN_SVG_PATTERN). Вызывается при создании/
    обновлении DiagramIcon через generic CRUD (services/crud.py:_RESOURCE_VALIDATORS) — до
    сохранения в БД, а не только на фронтенде, где проверку легко обойти прямым запросом к API.

    Пример вызова:
        validate_svg_markup('<svg><rect width="10" height="10"/></svg>')  # OK, не бросает
        validate_svg_markup('<svg onload="alert(1)"></svg>')  # HTTPException(422)
    """
    if svg_markup and _FORBIDDEN_SVG_PATTERN.search(svg_markup):
        raise HTTPException(422, "Недопустимое содержимое SVG: скрипты и обработчики событий запрещены")


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
    descriptor["glyph"] = SHAPE_GLYPHS.get(shape, SHAPE_GLYPHS[DEFAULT_SHAPE])
    # Раньше засечки считались только при shape == "switch" — на канвасе от этого страдали
    # многопортовые устройства ЛЮБОЙ другой формы (сервер с несколькими NIC, файрвол с WAN/LAN/
    # DMZ): все их подключения анкерились к единственному Handle узла и визуально сливались в
    # одну точку. Засечка — это факт о числе интерфейсов устройства, а не о его форме, поэтому
    # считаем её для любого сгенерированного значка (см. GraphContext.device_supports_port_index
    # в services/diagram_graph.py, где это используется при построении рёбер).
    port_ticks, port_overflow = port_ticks_for_count(interface_count)
    descriptor["port_ticks"] = port_ticks
    if port_overflow:
        descriptor["port_overflow"] = port_overflow

    manufacturer = lookups.manufacturers_by_id.get(device.manufacturer_id) if device.manufacturer_id else None
    descriptor["manufacturer_label"] = manufacturer.name if manufacturer else ""
    descriptor["model_label"] = model.model if model else ""
    return descriptor
