"""
Тесты на backend/app/services/diagram_icons.py — раздел 13 ТЗ диаграммы топологии сети:
"подъём по иерархии категорий корректно находит первый непустой diagram_shape/diagram_color;
при 40 интерфейсах — 32 засечки и +8 в дескрипторе; ручное переопределение на PhysicalDevice
побеждает переопределение на DeviceModel, оба побеждают автогенерацию."

Чистые unit-тесты без БД: функции сервиса читают только атрибуты переданных ORM-объектов,
поэтому объекты создаются напрямую (без session.add/flush) — быстрее и не зависит от схемы.

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_diagram_icons.py -v
"""

from __future__ import annotations

import pytest

from fastapi import HTTPException

from app.models import DeviceCategory, DeviceModel, DeviceType, DiagramIcon, Manufacturer, PhysicalDevice
from app.services.diagram_icons import (
    DEFAULT_COLOR,
    DEFAULT_SHAPE,
    SHAPE_GLYPHS,
    IconLookups,
    MAX_PORT_TICKS,
    build_device_icon,
    is_hex_color,
    port_ticks_for_count,
    resolve_category_style,
    resolve_custom_icon,
    safe_color,
    safe_shape,
    validate_svg_markup,
)


def _category(id_, parent_id=None, shape=None, color=None):
    return DeviceCategory(id=id_, name=id_, parent_id=parent_id, diagram_shape=shape, diagram_color=color)


def test_resolve_category_style_inherits_from_nearest_ancestor():
    root = _category("net", shape="generic", color="#2fa86a")
    switches = _category("switches", parent_id="net", shape="switch", color=None)
    categories = {"net": root, "switches": switches}
    shape, color = resolve_category_style(switches, categories)
    assert shape == "switch"  # задан на самой подкатегории
    assert color == "#2fa86a"  # унаследован от родителя


def test_resolve_category_style_defaults_when_nothing_set_in_chain():
    orphan = _category("mystery", parent_id=None, shape=None, color=None)
    shape, color = resolve_category_style(orphan, {})
    assert shape == DEFAULT_SHAPE
    assert color == DEFAULT_COLOR


def test_resolve_category_style_handles_none_category():
    shape, color = resolve_category_style(None, {})
    assert shape == DEFAULT_SHAPE
    assert color == DEFAULT_COLOR


def test_resolve_category_style_does_not_loop_forever_on_cyclic_parent_id():
    a = _category("a", parent_id="b")
    b = _category("b", parent_id="a")
    # Не должно упасть в бесконечный цикл — защита through `seen`.
    shape, color = resolve_category_style(a, {"a": a, "b": b})
    assert shape == DEFAULT_SHAPE
    assert color == DEFAULT_COLOR


@pytest.mark.parametrize(
    "count,expected_ticks,expected_overflow",
    [
        (0, 0, None),
        (1, 1, None),
        (MAX_PORT_TICKS, MAX_PORT_TICKS, None),
        (40, MAX_PORT_TICKS, 8),  # сценарий из раздела 13 ТЗ дословно
        (100, MAX_PORT_TICKS, 68),
    ],
)
def test_port_ticks_for_count(count, expected_ticks, expected_overflow):
    ticks, overflow = port_ticks_for_count(count)
    assert ticks == expected_ticks
    assert overflow == expected_overflow


def test_port_ticks_for_count_rejects_negative():
    with pytest.raises(ValueError):
        port_ticks_for_count(-1)


def test_build_device_icon_generated_switch_with_port_overflow():
    net = _category("net", shape="generic", color="#2fa86a")
    switches = _category("switches", parent_id="net", shape="switch", color=None)
    device_type = DeviceType(id="dt-switch", name="Коммутатор L2", category_id="switches")
    manufacturer = Manufacturer(id="mf-1", name="Cisco")
    device = PhysicalDevice(id="dev-1", device_type_id="dt-switch", manufacturer_id="mf-1", serial_number="SN-1")
    lookups = IconLookups(
        device_types_by_id={"dt-switch": device_type},
        categories_by_id={"net": net, "switches": switches},
        manufacturers_by_id={"mf-1": manufacturer},
    )
    icon = build_device_icon(device, interface_count=40, lookups=lookups)
    assert icon == {
        "mode": "generated",
        "shape": "switch",
        "color": "#2fa86a",
        "glyph": SHAPE_GLYPHS["switch"],
        "port_ticks": 32,
        "port_overflow": 8,
        "manufacturer_label": "Cisco",
        "model_label": "",
    }


def test_build_device_icon_non_switch_shape_also_gets_port_ticks():
    """Раньше засечки считались только при shape == "switch" — из-за этого многопортовый сервер/
    файрвол на канвасе анкерил ВСЕ свои связи в одну точку узла (нет отдельных Handle на порт).
    Засечка — это факт о числе интерфейсов устройства, а не о его форме."""
    servers = _category("servers", shape="server", color="#4f7cff")
    device_type = DeviceType(id="dt-server", name="Сервер", category_id="servers")
    device = PhysicalDevice(id="dev-2", device_type_id="dt-server", serial_number="SN-2")
    lookups = IconLookups(device_types_by_id={"dt-server": device_type}, categories_by_id={"servers": servers})
    icon = build_device_icon(device, interface_count=4, lookups=lookups)
    assert icon["shape"] == "server"
    assert icon["port_ticks"] == 4
    assert "port_overflow" not in icon


def test_build_device_icon_non_switch_shape_with_overflow():
    servers = _category("servers", shape="server", color="#4f7cff")
    device_type = DeviceType(id="dt-server", name="Сервер", category_id="servers")
    device = PhysicalDevice(id="dev-2b", device_type_id="dt-server", serial_number="SN-2b")
    lookups = IconLookups(device_types_by_id={"dt-server": device_type}, categories_by_id={"servers": servers})
    icon = build_device_icon(device, interface_count=40, lookups=lookups)
    assert icon["port_ticks"] == MAX_PORT_TICKS
    assert icon["port_overflow"] == 8


def test_build_device_icon_custom_mode_has_no_port_ticks():
    """Custom-значок (свой SVG) — единственный случай без вычисляемых засечек: у произвольной
    пользовательской картинки нет геометрии, к которой можно было бы их привязать."""
    device_icon = DiagramIcon(id="icon-custom", name="Своя иконка", svg_markup="<svg/>")
    device = PhysicalDevice(id="dev-2c", device_type_id="dt-x", diagram_icon_id="icon-custom", serial_number="SN-2c")
    lookups = IconLookups(icons_by_id={"icon-custom": device_icon})
    icon = build_device_icon(device, interface_count=4, lookups=lookups)
    assert icon == {"mode": "custom", "svg_markup": "<svg/>"}


def test_manual_override_on_physical_device_wins_over_model_and_autogeneration():
    device_icon = DiagramIcon(id="icon-device", name="Своя иконка устройства", svg_markup="<svg/>")
    model_icon = DiagramIcon(id="icon-model", name="Своя иконка модели", svg_markup="<svg model/>")
    model = DeviceModel(id="model-1", diagram_icon_id="icon-model", model="Catalyst 2960")
    device = PhysicalDevice(id="dev-3", device_type_id="dt-x", model_id="model-1", diagram_icon_id="icon-device", serial_number="SN-3")
    lookups = IconLookups(models_by_id={"model-1": model}, icons_by_id={"icon-device": device_icon, "icon-model": model_icon})
    icon = build_device_icon(device, interface_count=0, lookups=lookups)
    assert icon == {"mode": "custom", "svg_markup": "<svg/>"}


def test_manual_override_on_model_wins_over_autogeneration_when_device_has_none():
    model_icon = DiagramIcon(id="icon-model", name="Своя иконка модели", svg_markup="<svg model/>")
    model = DeviceModel(id="model-1", diagram_icon_id="icon-model", model="Catalyst 2960")
    device = PhysicalDevice(id="dev-4", device_type_id="dt-x", model_id="model-1", serial_number="SN-4")
    lookups = IconLookups(models_by_id={"model-1": model}, icons_by_id={"icon-model": model_icon})
    icon = build_device_icon(device, interface_count=0, lookups=lookups)
    assert icon == {"mode": "custom", "svg_markup": "<svg model/>"}


def test_resolve_custom_icon_falls_back_to_autogeneration_when_referenced_icon_is_missing():
    """Ссылка на удалённую/несуществующую иконку не должна валить построение графа — просто
    откатывается на автогенерацию, как будто переопределения не было."""
    device = PhysicalDevice(id="dev-5", device_type_id="dt-x", diagram_icon_id="icon-does-not-exist", serial_number="SN-5")
    assert resolve_custom_icon(device, model=None, icons_by_id={}) is None


def test_build_device_icon_defaults_manufacturer_and_model_labels_to_empty_string():
    servers = _category("servers", shape="server", color="#4f7cff")
    device_type = DeviceType(id="dt-server", name="Сервер", category_id="servers")
    device = PhysicalDevice(id="dev-6", device_type_id="dt-server", serial_number="SN-6")
    lookups = IconLookups(device_types_by_id={"dt-server": device_type}, categories_by_id={"servers": servers})
    icon = build_device_icon(device, interface_count=1, lookups=lookups)
    assert icon["manufacturer_label"] == ""
    assert icon["model_label"] == ""


# Код-ревью п.3.1 (критичная уязвимость): DiagramIcon.svg_markup рендерится через v-html на
# фронтенде и вставляется дословно в экспортируемый .svg на бэкенде — без этой валидации
# сохранённый в каталоге payload выполнялся бы в браузере каждого, кто открыл диаграмму.
@pytest.mark.parametrize(
    "svg_markup",
    [
        '<svg onload="alert(1)"></svg>',
        "<svg><script>alert(1)</script></svg>",
        '<svg ONLOAD="alert(1)"></svg>',  # регистронезависимость
        '<svg><foreignObject><body onload="alert(1)"/></foreignObject></svg>',
        '<svg><a href="javascript:alert(1)">кликни</a></svg>',
        '<svg><image href="javascript:alert(1)"/></svg>',
    ],
)
def test_validate_svg_markup_rejects_executable_content(svg_markup):
    with pytest.raises(HTTPException) as exc_info:
        validate_svg_markup(svg_markup)
    assert exc_info.value.status_code == 422


@pytest.mark.parametrize(
    "svg_markup",
    [
        None,
        "",
        '<svg viewBox="0 0 24 24"><rect width="24" height="24" fill="#4f7cff"/></svg>',
        '<svg><circle cx="5" cy="5" r="5" class="on-hover"/></svg>',  # "on" внутри имени класса — не обработчик события
    ],
)
def test_validate_svg_markup_allows_plain_shapes(svg_markup):
    validate_svg_markup(svg_markup)  # не должно бросить исключение


# --- A-04: цвет и форма категории не доходят до разметки как есть ---------------------------------------------------

DIRTY_COLOR = 'x" onload="alert(1)'


@pytest.mark.parametrize("value", ["#fff", "#FFF", "#4f7cff", "#4F7CFF", "#000000"])
def test_hex_colors_are_accepted(value):
    assert is_hex_color(value)
    assert safe_color(value) == value


@pytest.mark.parametrize("value", [DIRTY_COLOR, "", "red", "#ff", "#ffff", "#fffff", "#fffffff", "#12345g", "4f7cff", "#fff\n", " #fff", "#fff;stroke:red", None, 123, ["#fff"]])
def test_non_hex_colors_fall_back_to_default(value):
    assert not is_hex_color(value)
    assert safe_color(value) == DEFAULT_COLOR


def test_safe_color_uses_explicit_default():
    assert safe_color("nope", "#cccccc") == "#cccccc"


@pytest.mark.parametrize("shape", sorted(SHAPE_GLYPHS))
def test_known_shapes_are_kept(shape):
    assert safe_shape(shape) == shape


@pytest.mark.parametrize("shape", ["", "hexagon", 'server" onload="x', None, 5, "Server"])
def test_unknown_shapes_fall_back_to_default(shape):
    assert safe_shape(shape) == DEFAULT_SHAPE


def test_resolve_category_style_replaces_dirty_color_and_shape_with_defaults():
    dirty = _category("dirty", shape="<script>", color=DIRTY_COLOR)
    assert resolve_category_style(dirty, {"dirty": dirty}) == (DEFAULT_SHAPE, DEFAULT_COLOR)


def test_resolve_category_style_keeps_valid_inherited_values_next_to_dirty_ones():
    parent = _category("parent", shape="server", color="#4f7cff")
    child = _category("child", parent_id="parent", shape=None, color=None)
    assert resolve_category_style(child, {"parent": parent, "child": child}) == ("server", "#4f7cff")


def test_build_device_icon_never_puts_dirty_category_values_into_the_descriptor():
    dirty = _category("cat", shape="nope", color=DIRTY_COLOR)
    device_type = DeviceType(id="dt", name="Тип", category_id="cat")
    device = PhysicalDevice(id="dev", device_type_id="dt", serial_number="SN-1")
    lookups = IconLookups(categories_by_id={"cat": dirty}, device_types_by_id={"dt": device_type})
    descriptor = build_device_icon(device, interface_count=0, lookups=lookups)
    assert descriptor["color"] == DEFAULT_COLOR
    assert descriptor["shape"] == DEFAULT_SHAPE
    assert "onload" not in repr(descriptor)
