"""Экспорт графа диаграммы в .drawio (XML draw.io) через объектную модель drawpyo (см. docstring пакета)."""
from __future__ import annotations

from ._common import (
    CUSTOM_ICON_TILE_HEIGHT,
    DIAGRAM_EDGE_FONT_SIZE,
    DIAGRAM_FONT_FAMILY,
    DIAGRAM_NODE_FONT_SIZE,
    GLYPH_DISPLAY_SIZE,
    GLYPH_TOP_MARGIN,
    GROUP_FILL_COLOR,
    NODE_HEIGHT,
    NODE_WIDTH,
    _device_fill_color,
    _port_anchor_fraction,
    _port_ticks_of,
    _vlan_label,
)
from ._icons import (
    _custom_icon_data_uri,
    _glyph_data_uri,
    _standalone_custom_svg,
)

# --------------------------------------------------------------------------------------
# .drawio (drawpyo)
# --------------------------------------------------------------------------------------

def _drawio_image_object(page, position: tuple[float, float], width: float, height: float, data_uri: str):
    """Отдельный объект shape=image поверх узла (глиф категории, плитка custom-иконки).

    apply_style_string() режет по первому "=" — для data URI использовать нельзя (см. docstring _glyph_data_uri), поэтому атрибуты стиля
    выставляются напрямую тем же способом, каким это делает сама apply_style_string."""
    import drawpyo

    image_obj = drawpyo.diagram.Object(page=page, value="")
    image_obj.position = position
    image_obj.width = width
    image_obj.height = height
    image_obj._add_and_set_style_attrib("shape", "image")
    image_obj._add_and_set_style_attrib("image", data_uri)
    return image_obj


def _drawio_add_port_ticks(page, node: dict, ticks: int) -> None:
    """Засечки портов вдоль нижнего края узла: чёрные штрихи 4x6, равномерно по ширине (как port-tick в .svg)."""
    import drawpyo

    spacing = NODE_WIDTH / (ticks + 1)
    for i in range(ticks):
        tick = drawpyo.diagram.Object(page=page, value="")
        tick.position = (node["x"] + spacing * (i + 1) - 2, node["y"] + NODE_HEIGHT - 6)
        tick.width = 4
        tick.height = 6
        tick.fillColor = "#222222"


def _drawio_add_generated_icon(page, node: dict, icon: dict) -> None:
    """Сгенерированная иконка: глиф категории по центру верхней части узла и засечки портов."""
    glyph = icon.get("glyph")
    if glyph:
        # Находка №5 отчёта (Фаза 3, п.5): полноценная узнаваемая иконка по центру
        # верхней части узла (не мелкий угловой акцент 14x13 из Фазы 2, п.2) — та же
        # позиция/размер, что и в .svg (_svg_node) и на канвасе (DiagramDeviceNode.vue).
        _drawio_image_object(
            page,
            (node["x"] + (NODE_WIDTH - GLYPH_DISPLAY_SIZE) / 2, node["y"] + GLYPH_TOP_MARGIN),
            GLYPH_DISPLAY_SIZE,
            GLYPH_DISPLAY_SIZE,
            _glyph_data_uri(glyph),
        )

    ticks = icon.get("port_ticks", 0)
    if ticks:
        _drawio_add_port_ticks(page, node, ticks)


def _drawio_add_custom_icon(page, node: dict, icon: dict) -> None:
    """Пользовательская иконка — плитка над полосой подписи (см. константы CUSTOM_ICON_*): отдельный объект поверх узла, тем же приёмом,
    что и глиф категории (shape=image + data URI)."""
    custom_svg = _standalone_custom_svg(icon)
    if custom_svg:
        _drawio_image_object(page, (node["x"], node["y"]), NODE_WIDTH, CUSTOM_ICON_TILE_HEIGHT, _custom_icon_data_uri(custom_svg))


def _drawio_add_node(page, node: dict):
    """Объект узла и, для устройства, поверх него иконка (глиф/засечки либо плитка custom-иконки). Возвращает объект узла для связей."""
    import drawpyo

    obj = drawpyo.diagram.Object(page=page, value=node["label"])
    obj.position = (node["x"], node["y"])
    obj.width = NODE_WIDTH
    obj.height = NODE_HEIGHT
    # Визуальный паритет с .svg/канвасом, где у узла и группы rx="8" (скруглённые углы) —
    # без этого .drawio-узлы рисовались строго прямоугольными.
    obj.rounded = 1
    # Находка №4 отчёта (Фаза 2, п.4): явный шрифт вместо дефолтного шрифта draw.io — та же
    # пара family/size, что и в .svg (см. DIAGRAM_FONT_FAMILY выше). text_format — штатный
    # (не самодельный) способ: drawpyo.diagram.Object уже создаёт TextFormat() по умолчанию,
    # и в отличие от style_attributes (которым для Edge приходится подделывать конкретные
    # именованные kwargs) это работает одинаково что для Object, что для Edge.
    obj.text_format.fontFamily = DIAGRAM_FONT_FAMILY
    obj.text_format.fontSize = DIAGRAM_NODE_FONT_SIZE
    if node["type"] == "group":
        obj.fillColor = GROUP_FILL_COLOR
        obj.dashed = 1
        return obj

    icon = node["icon"]
    obj.fillColor = _device_fill_color(icon)
    # Подпись у нижнего края узла, как на канвасе/в .svg: по умолчанию draw.io ставит её
    # по центру, где теперь иконка (32x32 у сгенерированных, плитка у custom-иконок).
    obj.text_format.verticalAlign = "bottom"
    # Раньше — только icon["shape"].startswith("switch"), см. тот же комментарий у
    # _svg_node про рассинхронизацию с port_ticks, который backend считает для ЛЮБОЙ
    # сгенерированной иконки: без этого у остальных форм ребро (см. _drawio_edge_anchors
    # exitX/entryX) целилось бы в засечку, которой на самой фигуре не видно.
    if icon.get("mode") == "generated":
        _drawio_add_generated_icon(page, node, icon)
    else:
        _drawio_add_custom_icon(page, node, icon)
    return obj


def _drawio_edge_anchors(edge: dict, nodes_by_id: dict) -> dict:
    """exitX/exitY и entryX/entryY ребра — точная привязка к засечке порта.

    Находка №2 отчёта об экспорте (Фаза 2, п.1): "точная привязка ребра к засечке порта" —
    entryX/entryY (и exitX/exitY) как доля 0-1 от габарита фигуры, mxGraph-конвенция
    (0,0)=левый верхний угол, (1,1)=правый нижний. Если для конца ребра порт не резолвится
    (группа/custom-иконка/устройство без интерфейсов) — оставляем как раньше, без entry/exit,
    drawio.js сам выберет точку автоматической маршрутизации."""
    anchors: dict[str, float] = {}
    exit_fraction = _port_anchor_fraction(edge.get("source_interface"), _port_ticks_of(nodes_by_id[edge["source_node_id"]]))
    if exit_fraction is not None:
        anchors["exitX"] = exit_fraction
        anchors["exitY"] = 1.0
    entry_fraction = _port_anchor_fraction(edge.get("target_interface"), _port_ticks_of(nodes_by_id[edge["target_node_id"]]))
    if entry_fraction is not None:
        anchors["entryX"] = entry_fraction
        anchors["entryY"] = 1.0
    return anchors


def _drawio_add_edge(page, edge: dict, source, target, nodes_by_id: dict) -> None:
    import drawpyo

    # line_end_*="none" — связь между устройствами не имеет "направления" (в отличие от
    # потока данных), а без явного none drawio.js подставляет свою стрелку по умолчанию;
    # .svg/.vsdx стрелок не рисуют вовсе, этим достигается параллель между форматами.
    # pattern="dashed_medium" — та же семантика, что и stroke-dasharray в .svg для
    # is_active=False (раздел 4.4 ТЗ: неактивная связь размечается визуально, не только
    # цветом в интерактивном канвасе).
    edge_kwargs = {
        "line_end_source": "none",
        "line_end_target": "none",
        "pattern": None if edge.get("is_active", True) else "dashed_medium",
        **_drawio_edge_anchors(edge, nodes_by_id),
    }
    edge_obj = drawpyo.diagram.Edge(page=page, source=source, target=target, label=_vlan_label(edge), **edge_kwargs)
    # Находка №4 отчёта (Фаза 2, п.4): тот же явный шрифт, что и у узлов, — для метки связи.
    edge_obj.text_format.fontFamily = DIAGRAM_FONT_FAMILY
    edge_obj.text_format.fontSize = DIAGRAM_EDGE_FONT_SIZE


def export_drawio(graph: dict) -> str:
    """Граф диаграммы → .drawio (XML draw.io). Шаги: страница → узлы (объект узла и иконка поверх него) → рёбра между созданными узлами.

    Пример:
        xml = export_drawio({"nodes": [...], "edges": [...]})
    """
    import drawpyo

    file = drawpyo.File()
    file.file_name = "diagram.drawio"
    page = drawpyo.Page(file=file)

    objects_by_node_id = {node["id"]: _drawio_add_node(page, node) for node in graph["nodes"]}

    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    for edge in graph["edges"]:
        source = objects_by_node_id.get(edge["source_node_id"])
        target = objects_by_node_id.get(edge["target_node_id"])
        if source is None or target is None:
            continue
        _drawio_add_edge(page, edge, source, target, nodes_by_id)

    return file.xml
