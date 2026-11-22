"""Экспорт графа диаграммы в .svg — строковый шаблон, без внешних зависимостей (см. docstring пакета)."""

from __future__ import annotations

import base64
from xml.sax.saxutils import escape  # nosec B406 # escape только экранирует исходящий текст, XML не разбирает; разбор — через SafeET

from ._common import (
    DIAGRAM_EDGE_FONT_SIZE,
    DIAGRAM_FONT_FAMILY,
    DIAGRAM_NODE_FONT_SIZE,
    GLYPH_DISPLAY_SIZE,
    GLYPH_TOP_MARGIN,
    GROUP_FILL_COLOR,
    NODE_HEIGHT,
    NODE_WIDTH,
    PORT_TICK_COLOR,
    PORT_TICK_HEIGHT,
    PORT_TICK_WIDTH,
    _icon_color,
    _port_anchor_fraction,
    _port_ticks_of,
    _vlan_label,
)
from ._icons import (
    _standalone_custom_svg,
)

# --------------------------------------------------------------------------------------
# .svg
# --------------------------------------------------------------------------------------


_ATTR_ENTITIES = {'"': "&quot;", "'": "&apos;"}


def _esc(value) -> str:
    """Экранирование для текста И для значений атрибутов (data-node-id, fill…): в отличие от saxutils.escape по умолчанию, кавычки тоже.

    Без кавычек значение с `"` выходило бы из атрибута, и первый же id или цвет из пользовательского ввода дал бы XSS в скачанном .svg.
    Пустое значение (None, "") — пустая строка."""
    return escape(str(value), _ATTR_ENTITIES) if value not in (None, "") else ""


def _svg_port_ticks(x: float, y: float, width: float, height: float, ticks: int) -> str:
    if ticks <= 0:
        return ""
    spacing = width / (ticks + 1)
    return "".join(
        f'<rect class="port-tick" x="{x + spacing * (i + 1) - PORT_TICK_WIDTH / 2:.1f}" y="{y + height - PORT_TICK_HEIGHT:.1f}" width="{PORT_TICK_WIDTH}" height="{PORT_TICK_HEIGHT}" fill="{PORT_TICK_COLOR}"/>' for i in range(ticks)
    )


def _svg_node(node: dict, x: float, y: float) -> str:
    if node["type"] == "group":
        return (
            f'<g class="diagram-node diagram-group" data-node-id="{_esc(node["id"])}">'
            f'<rect x="{x}" y="{y}" width="{NODE_WIDTH}" height="{NODE_HEIGHT}" rx="8" '
            f'fill="{GROUP_FILL_COLOR}" stroke="#333333" stroke-width="1.5" stroke-dasharray="4,3"/>'
            f'<text x="{x + NODE_WIDTH / 2}" y="{y + NODE_HEIGHT / 2}" text-anchor="middle" '
            f'font-size="{DIAGRAM_NODE_FONT_SIZE}" font-family="{DIAGRAM_FONT_FAMILY}" fill="#222222">{_esc(node["label"])}</text>'
            f"</g>"
        )

    icon = node["icon"]
    parts = [f'<g class="diagram-node" data-node-id="{_esc(node["id"])}">']
    custom_svg = _standalone_custom_svg(icon)
    if custom_svg:
        # Пользовательская разметка попадает в документ ТОЛЬКО как вложенное изображение (data URI), а не
        # как есть: так же, как в .drawio и .vsdx. Браузер обрабатывает такое изображение без скриптов и
        # без внешних запросов, поэтому открытый в браузере .svg не выполняет код из каталога иконок
        # (остаточный риск .svg-экспорта).
        encoded = base64.b64encode(custom_svg.encode("utf-8")).decode("ascii")
        parts.append(f'<image x="{x}" y="{y}" width="{NODE_WIDTH}" height="{NODE_HEIGHT}" preserveAspectRatio="xMidYMid meet" xlink:href="data:image/svg+xml;base64,{encoded}"/>')
    else:
        # Два слоя: _icon_color — значение должно быть HEX-цветом, _esc — разметка не собирается из данных ни при каких
        # обстоятельствах.
        color = _icon_color(icon)
        parts.append(f'<rect x="{x}" y="{y}" width="{NODE_WIDTH}" height="{NODE_HEIGHT}" rx="8" fill="{_esc(color)}" stroke="#333333" stroke-width="1.5"/>')
        # Находка №5 отчёта (Фаза 3, п.5): полноценная узнаваемая иконка категории (не мелкий
        # угловой акцент, как в Фазе 2, п.2) по центру верхней части узла — та же разметка
        # (viewBox "0 0 24 24"), что рисует канвас (DiagramDeviceNode.vue), приходит готовой в
        # дескрипторе (icon["glyph"], см. diagram_icons.py:SHAPE_GLYPHS) как фрагмент SVG-разметки
        # (rect/circle/path) БЕЗ жёсткого fill/stroke на дочерних элементах — оба наследуются от
        # обёртки <g>, поэтому один и тот же фрагмент одинаково работает и здесь (белым по цветной
        # заливке узла), и в легенде (Фаза 3, п.1, тёмным по светлому фону).
        glyph = icon.get("glyph")
        if glyph:
            glyph_x = x + (NODE_WIDTH - GLYPH_DISPLAY_SIZE) / 2
            parts.append(f'<svg x="{glyph_x}" y="{y + GLYPH_TOP_MARGIN}" width="{GLYPH_DISPLAY_SIZE}" height="{GLYPH_DISPLAY_SIZE}" viewBox="0 0 24 24"><g fill="rgba(255,255,255,0.9)" color="rgba(255,255,255,0.9)">{glyph}</g></svg>')
        # Раньше засечки рисовались только при icon["shape"].startswith("switch"): backend уже
        # считает port_ticks для ЛЮБОЙ сгенерированной иконки (см. diagram_graph.py, п.5 —
        # раньше это тоже было ограничено только switch), а видимость в canvas (см.
        # DiagramDeviceNode.vue) завязана просто на "port_ticks > 0", без проверки формы —
        # сервер с несколькими NIC или файрвол с WAN/LAN/DMZ получают засечки точно так же, как
        # коммутатор. Проверка по shape была рассинхронизирована с этим и без явной привязки
        # ребра к засечке (см. _svg_edge ниже) была просто "лишним" рисунком у одной формы —
        # теперь, когда ребро реально целится в конкретную засечку, рисовать её нужно везде, где
        # она есть, иначе привязка у остальных форм будет указывать в пустое место.
        parts.append(_svg_port_ticks(x, y, NODE_WIDTH, NODE_HEIGHT, icon.get("port_ticks", 0)))
    parts.append(f'<text x="{x + NODE_WIDTH / 2}" y="{y + NODE_HEIGHT - 8}" text-anchor="middle" font-size="{DIAGRAM_NODE_FONT_SIZE}" font-family="{DIAGRAM_FONT_FAMILY}" fill="#ffffff">{_esc(node["label"])}</text>')
    parts.append("</g>")
    return "".join(parts)


def _svg_edge_anchor(node: dict, interface_ref: dict | None) -> tuple[float, float]:
    """Точка на этом конце ребра: если для узла резолвится конкретная засечка порта (находка №2
    отчёта об экспорте) — её координата (та же формула, что _svg_port_ticks), иначе (группа,
    custom-иконка, устройство без интерфейсов) — прежнее поведение, центр узла."""
    x, y = node["x"], node["y"]
    fraction = _port_anchor_fraction(interface_ref, _port_ticks_of(node))
    if fraction is None:
        return (x + NODE_WIDTH / 2, y + NODE_HEIGHT / 2)
    return (x + NODE_WIDTH * fraction, y + NODE_HEIGHT)


def _svg_edge(edge: dict, nodes_by_id: dict) -> str:
    x1, y1 = _svg_edge_anchor(nodes_by_id[edge["source_node_id"]], edge.get("source_interface"))
    x2, y2 = _svg_edge_anchor(nodes_by_id[edge["target_node_id"]], edge.get("target_interface"))
    dash = "" if edge.get("is_active", True) else ' stroke-dasharray="6,4"'
    label_text = _vlan_label(edge)
    label = f'<text x="{(x1 + x2) / 2}" y="{(y1 + y2) / 2}" text-anchor="middle" font-size="{DIAGRAM_EDGE_FONT_SIZE}" font-family="{DIAGRAM_FONT_FAMILY}" fill="#555555">{_esc(label_text)}</text>' if label_text else ""
    return f'<g class="diagram-edge" data-edge-id="{_esc(edge["id"])}"><line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#666666" stroke-width="1.5"{dash}/>{label}</g>'


def export_svg(graph: dict) -> str:
    """Раздел 9 ТЗ: собирается напрямую из графовой модели строковым шаблоном — без
    растеризации и без headless-рендерера, тем же способом, каким drawpyo формирует свой XML."""
    nodes_by_id: dict[str, dict] = {n["id"]: n for n in graph["nodes"]}
    nodes_svg = [_svg_node(node, node["x"], node["y"]) for node in graph["nodes"]]

    edges_svg = [_svg_edge(e, nodes_by_id) for e in graph["edges"] if e["source_node_id"] in nodes_by_id and e["target_node_id"] in nodes_by_id]

    max_x = max((n["x"] for n in graph["nodes"]), default=0) + NODE_WIDTH + 40
    max_y = max((n["y"] for n in graph["nodes"]), default=0) + NODE_HEIGHT + 40
    body = "".join(edges_svg) + "".join(nodes_svg)
    return f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {max_x} {max_y}" width="{max_x}" height="{max_y}"><rect width="100%" height="100%" fill="#ffffff"/>{body}</svg>'
