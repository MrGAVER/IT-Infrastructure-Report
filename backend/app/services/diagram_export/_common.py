"""Общее для всех трёх экспортёров диаграммы: геометрия и стиль узла/иконки (константы) и вспомогательные функции, которые читают
дескрипторы графа одинаково для .svg, .drawio и .vsdx (цвет, засечки портов, привязка ребра к порту, подпись VLAN).

Ничего не знает ни об одном формате: зависимости идут только вниз (`_common` → `_icons` → `svg`/`drawio`/`vsdx`), циклов нет.
"""
from __future__ import annotations

import re

from ..diagram_icons import safe_color

NODE_WIDTH = 160
NODE_HEIGHT = 70
CUSTOM_ICON_FALLBACK_COLOR = "#cccccc"
GROUP_FILL_COLOR = "#dddddd"
VSDX_SCALE = 100.0  # пиксели графа -> дюймы Visio (чисто визуальный масштаб)

# Находка №4 отчёта об экспорте диаграмм (Фаза 2, п.4): раньше каждый формат подписывал узлы и
# рёбра шрифтом по умолчанию своего движка рендеринга (браузер для .svg, draw.io/Visio — своим),
# так что один и тот же граф визуально "звучал" по-разному в каждом формате. Calibri — не
# призвольный выбор: это единственный шрифт, который уже фигурирует в таблице шрифтов
# (FaceNames) шаблона media.vsdx, использованного в export_vsdx (см. находку №1, Фаза 1) — то
# есть .vsdx им и так пользуется неявно по умолчанию, без единой правки. Задав то же имя явно в
# .svg/.drawio, приводим все три формата к одному и тому же шрифту, ничем не рискуя в .vsdx.
# Возможности задать per-shape размер шрифта в .vsdx без риска нет — см. README, раздел
# «Известные ограничения»: у библиотеки vsdx нет API для создания Section "Character" с нуля, а
# у шаблонных фигур такой секции нет вовсе, так что 11pt/9pt ниже относятся только к .svg/.drawio.
DIAGRAM_FONT_FAMILY = "Calibri"
DIAGRAM_NODE_FONT_SIZE = 11
DIAGRAM_EDGE_FONT_SIZE = 9

# Находка №5 отчёта (Фаза 3, п.5 "кастомные SVG-иконки"): иконка категории раньше была мелким
# угловым акцентом (14x13, см. историю в diagram_icons.py), теперь — полноценный узнаваемый
# значок по центру верхней части узла, тем же viewBox "0 0 24 24", что и SHAPE_GLYPHS.
GLYPH_DISPLAY_SIZE = 32
GLYPH_TOP_MARGIN = 4

# Пользовательские (загруженные) иконки в .drawio/.vsdx (Фаза 3, п.5, «свои иконки»). На канвасе
# custom-иконка занимает весь бокс узла (inset: 0) на тёмном фоне, а подпись рисуется поверх неё
# белым цветом. В .drawio/.vsdx так повторить нельзя: цвет шрифта в .vsdx задать нечем (у
# шаблонных фигур нет секции Character, см. README «Известные ограничения»), а картинка-оверлей
# перекрывает подпись самой фигуры. Поэтому подпись всегда остаётся читаемой чёрным по светлой
# заливке в полосе CUSTOM_ICON_LABEL_HEIGHT внизу узла, а иконка занимает всё остальное.
CUSTOM_ICON_LABEL_HEIGHT = 24
CUSTOM_ICON_TILE_HEIGHT = NODE_HEIGHT - CUSTOM_ICON_LABEL_HEIGHT
CUSTOM_ICON_TILE_RADIUS = 8  # как rx у узла в .svg — скругляем верхние углы плитки
CUSTOM_ICON_TILE_PADDING = 4
CUSTOM_ICON_BACKGROUND_COLOR = "#1e2c3b"  # --surface-2 канваса (DiagramDeviceNode.vue)
CUSTOM_ICON_PNG_SCALE = 4  # растр для .vsdx в 4x от размера в пикселях графа — иначе мыльно
# svg_markup — пользовательский ввод без ограничения длины на уровне БД; в .drawio он попадает в
# data URI стиля, в .vsdx — в растеризатор. Слишком большую разметку пропускаем (иконка узла
# откатывается на серую заливку), а не раздуваем файл и не тратим на неё время.
MAX_CUSTOM_ICON_SVG_LENGTH = 256 * 1024

_SVG_NS_URI = "http://www.w3.org/2000/svg"
_XLINK_NS_URI = "http://www.w3.org/1999/xlink"
_SVG_ROOT_TAG = re.compile(r"<svg\b[^>]*>", re.IGNORECASE)


TRUNK_EDGE_LABEL = "trunk"


def _vlan_label(edge: dict) -> str:
    """Подпись ребра: у trunk-подключения с VLAN — просто «trunk» (полный список VLAN на линии не читается), иначе
    список VLAN. Должна совпадать с edgeMidLabel во frontend-vue/src/utils/diagramFlow.ts."""
    vlans = edge.get("vlans", [])
    if vlans and edge.get("is_trunk"):
        return TRUNK_EDGE_LABEL
    return ", ".join(f"VLAN {v['vlan_id']}" for v in vlans)


def _icon_color(icon: dict) -> str:
    """Цвет сгенерированной иконки для разметки экспорта. Ключа нет — нейтральный откат экспорта; ключ есть, но значение
    не HEX-цвет (граф строится из resolve_category_style, где это уже исключено, но функции экспорта принимают и готовые
    словари) — DEFAULT_COLOR. Так в стиль .drawio (`fillColor=…;`, «;» подставил бы чужие параметры), .vsdx и атрибут
    fill в .svg не попадает ничего, кроме #RGB/#RRGGBB."""
    if "color" not in icon:
        return CUSTOM_ICON_FALLBACK_COLOR
    return safe_color(icon["color"])


def _device_fill_color(icon: dict) -> str:
    """Общая для .drawio и .vsdx логика цвета узла-устройства (группы красятся отдельно, см.
    вызывающий код): цвет категории берём только у сгенерированных иконок — у custom-иконок
    (icon["mode"] == "custom") ключа "color" нет вовсе, там для внешнего вида отвечает
    svg_markup (см. diagram_icons.build_device_icon). В .drawio/.vsdx иконка кладётся отдельной
    картинкой-плиткой поверх верхней части узла (см. _custom_icon_tile_svg), а сама фигура узла
    остаётся нейтральной CUSTOM_ICON_FALLBACK_COLOR — под подпись и как откат, если иконку не
    удалось нарисовать (пустая/битая/слишком большая разметка)."""
    if icon.get("mode") == "generated":
        return _icon_color(icon)
    return CUSTOM_ICON_FALLBACK_COLOR


def _port_ticks_of(node: dict) -> int:
    """Число засечек порта у узла — 0 для группы (своих портов не имеет, см.
    diagram_graph.build_group_node) и для узла-устройства без известных интерфейсов."""
    if node["type"] != "device":
        return 0
    return node["icon"].get("port_ticks", 0)


def _port_anchor_fraction(interface_ref: dict | None, port_ticks: int) -> float | None:
    """Доля (0..1) по ширине узла, куда должен упираться конец ребра — тот же расчёт, что и
    _svg_port_ticks/frontend DiagramDeviceNode.vue:tickX (см. находку №2 отчёта об экспорте
    диаграмм, Фаза 2 п.1: "точная привязка ребра к засечке порта"). None означает "у этого конца
    порт не резолвится (группа, custom-иконка или устройство без интерфейсов) — анкерить в центр
    узла, как раньше", а не "порт с индексом 0", поэтому проверяем именно на None, а не на falsy.
    port_index уже гарантированно < port_ticks на уровне графа (см. diagram_graph.GraphContext.
    interface_index) — здесь это не перепроверяется."""
    if not interface_ref or port_ticks <= 0:
        return None
    port_index = interface_ref.get("port_index")
    if port_index is None:
        return None
    return (port_index + 1) / (port_ticks + 1)
