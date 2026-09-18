"""
Экспорт диаграммы топологии сети в редактируемые внешние форматы (ТЗ, раздел 9). Все три
экспортёра читают ОДИН и тот же граф (dict вида {"nodes": [...], "edges": [...]}, как возвращает
services.diagram_graph.build_graph) и воспроизводят одну и ту же геометрию (прямоугольник узла,
цвет по дескриптору иконки, засечки портов для shape="switch", подписи) каждый своими средствами
— строковый SVG-шаблон, объектная модель drawpyo, копирование шаблонных фигур vsdx — а не через
сетевые стенсилы конкретного формата (раздел 4.3 ТЗ: "одинаковый вид во всех форматах").

Порядок фактической РЕАЛИЗАЦИИ ниже — .svg, затем .drawio, затем .vsdx, а не .drawio -> .vsdx ->
.svg, как перечислено в разделе 9 ТЗ (drawio там назван основным форматом для первой демонстрации
— этот приоритет не изменился, просто .svg было быстрее и безопаснее реализовать первым, чтобы
сразу проверить геометрию без внешних зависимостей). .vsdx устроен ощутимо иначе, чем ожидалось:
библиотека vsdx — это низкоуровневая работа с XML Element поверх уже СУЩЕСТВУЮЩЕГО файла
(редактирование, а не построение с нуля), без объектной модели уровня drawpyo. Раздел 14 ТЗ уже
заранее допускал ограничения именно у этого формата, поэтому .vsdx ниже воспроизводит геометрию
копированием и перемещением готовых фигур из шаблона (media.vsdx, поставляется вместе с пакетом)
— прямоугольник и прямой соединитель — без отдельных фигур-засечек портов (в отличие от .svg/
.drawio, где каждая засечка — самостоятельный примитив).
"""
from __future__ import annotations

import os
import shutil
import tempfile
from xml.sax.saxutils import escape

NODE_WIDTH = 160
NODE_HEIGHT = 70
CUSTOM_ICON_FALLBACK_COLOR = "#cccccc"
GROUP_FILL_COLOR = "#dddddd"
VSDX_SCALE = 100.0  # пиксели графа -> дюймы Visio (чисто визуальный масштаб)


def _vlan_label(edge: dict) -> str:
    return ", ".join(f"VLAN {v['vlan_id']}" for v in edge.get("vlans", []))


# --------------------------------------------------------------------------------------
# .svg
# --------------------------------------------------------------------------------------

def _esc(value) -> str:
    return escape(str(value)) if value not in (None, "") else ""


def _svg_port_ticks(x: float, y: float, width: float, height: float, ticks: int) -> str:
    if ticks <= 0:
        return ""
    spacing = width / (ticks + 1)
    return "".join(
        f'<rect class="port-tick" x="{x + spacing * (i + 1) - 2:.1f}" y="{y + height - 6:.1f}" width="4" height="6" fill="#222222"/>'
        for i in range(ticks)
    )


def _svg_node(node: dict, x: float, y: float) -> str:
    if node["type"] == "group":
        return (
            f'<g class="diagram-node diagram-group" data-node-id="{_esc(node["id"])}">'
            f'<rect x="{x}" y="{y}" width="{NODE_WIDTH}" height="{NODE_HEIGHT}" rx="8" '
            f'fill="{GROUP_FILL_COLOR}" stroke="#333333" stroke-width="1.5" stroke-dasharray="4,3"/>'
            f'<text x="{x + NODE_WIDTH / 2}" y="{y + NODE_HEIGHT / 2}" text-anchor="middle" '
            f'font-size="11" fill="#222222">{_esc(node["label"])}</text>'
            f"</g>"
        )

    icon = node["icon"]
    parts = [f'<g class="diagram-node" data-node-id="{_esc(node["id"])}">']
    if icon.get("mode") == "custom" and icon.get("svg_markup"):
        parts.append(f'<g transform="translate({x},{y})">{icon["svg_markup"]}</g>')
    else:
        color = icon.get("color", CUSTOM_ICON_FALLBACK_COLOR)
        parts.append(f'<rect x="{x}" y="{y}" width="{NODE_WIDTH}" height="{NODE_HEIGHT}" rx="8" fill="{color}" stroke="#333333" stroke-width="1.5"/>')
        # startswith, а не точное сравнение — 'switch' (общий fallback категории "Коммутаторы"
        # без более точной L2/L3 подкатегории), 'switch_l2' и 'switch_l3' одинаково рисуются с
        # засечками портов, различаются только заливкой формы значка (см. DiagramDeviceNode.vue).
        if icon.get("shape", "").startswith("switch"):
            parts.append(_svg_port_ticks(x, y, NODE_WIDTH, NODE_HEIGHT, icon.get("port_ticks", 0)))
    parts.append(
        f'<text x="{x + NODE_WIDTH / 2}" y="{y + NODE_HEIGHT - 8}" text-anchor="middle" '
        f'font-size="11" fill="#ffffff">{_esc(node["label"])}</text>'
    )
    parts.append("</g>")
    return "".join(parts)


def _svg_edge(edge: dict, centers: dict) -> str:
    x1, y1 = centers[edge["source_node_id"]]
    x2, y2 = centers[edge["target_node_id"]]
    dash = "" if edge.get("is_active", True) else ' stroke-dasharray="6,4"'
    label_text = _vlan_label(edge)
    label = (
        f'<text x="{(x1 + x2) / 2}" y="{(y1 + y2) / 2}" text-anchor="middle" font-size="9" fill="#555555">{_esc(label_text)}</text>'
        if label_text
        else ""
    )
    return (
        f'<g class="diagram-edge" data-edge-id="{_esc(edge["id"])}">'
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#666666" stroke-width="1.5"{dash}/>'
        f"{label}</g>"
    )


def export_svg(graph: dict) -> str:
    """Раздел 9 ТЗ: собирается напрямую из графовой модели строковым шаблоном — без
    растеризации и без headless-рендерера, тем же способом, каким drawpyo формирует свой XML."""
    centers: dict[str, tuple[float, float]] = {}
    nodes_svg = []
    for node in graph["nodes"]:
        x, y = node["x"], node["y"]
        centers[node["id"]] = (x + NODE_WIDTH / 2, y + NODE_HEIGHT / 2)
        nodes_svg.append(_svg_node(node, x, y))

    edges_svg = [_svg_edge(e, centers) for e in graph["edges"] if e["source_node_id"] in centers and e["target_node_id"] in centers]

    max_x = max((n["x"] for n in graph["nodes"]), default=0) + NODE_WIDTH + 40
    max_y = max((n["y"] for n in graph["nodes"]), default=0) + NODE_HEIGHT + 40
    body = "".join(edges_svg) + "".join(nodes_svg)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {max_x} {max_y}" width="{max_x}" height="{max_y}">'
        f'<rect width="100%" height="100%" fill="#ffffff"/>{body}</svg>'
    )


# --------------------------------------------------------------------------------------
# .drawio (drawpyo)
# --------------------------------------------------------------------------------------

def export_drawio(graph: dict) -> str:
    import drawpyo

    file = drawpyo.File()
    file.file_name = "diagram.drawio"
    page = drawpyo.Page(file=file)

    objects_by_node_id = {}
    for node in graph["nodes"]:
        obj = drawpyo.diagram.Object(page=page, value=node["label"])
        obj.position = (node["x"], node["y"])
        obj.width = NODE_WIDTH
        obj.height = NODE_HEIGHT
        if node["type"] == "group":
            obj.fillColor = GROUP_FILL_COLOR
            obj.dashed = 1
        else:
            icon = node["icon"]
            obj.fillColor = icon.get("color", CUSTOM_ICON_FALLBACK_COLOR) if icon.get("mode") == "generated" else CUSTOM_ICON_FALLBACK_COLOR
            if icon.get("mode") == "generated" and icon.get("shape", "").startswith("switch"):
                ticks = icon.get("port_ticks", 0)
                if ticks:
                    spacing = NODE_WIDTH / (ticks + 1)
                    for i in range(ticks):
                        tick = drawpyo.diagram.Object(page=page, value="")
                        tick.position = (node["x"] + spacing * (i + 1) - 2, node["y"] + NODE_HEIGHT - 6)
                        tick.width = 4
                        tick.height = 6
                        tick.fillColor = "#222222"
        objects_by_node_id[node["id"]] = obj

    for edge in graph["edges"]:
        source = objects_by_node_id.get(edge["source_node_id"])
        target = objects_by_node_id.get(edge["target_node_id"])
        if source is None or target is None:
            continue
        drawpyo.diagram.Edge(page=page, source=source, target=target, label=_vlan_label(edge))

    return file.xml


# --------------------------------------------------------------------------------------
# .vsdx (vsdx) — копирование шаблонных фигур, см. docstring модуля
# --------------------------------------------------------------------------------------

def export_vsdx(graph: dict) -> bytes:
    import vsdx

    template_path = os.path.join(os.path.dirname(vsdx.__file__), "media", "media.vsdx")

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = os.path.join(tmp_dir, "diagram.vsdx")
        shutil.copy(template_path, out_path)

        vf = vsdx.VisioFile(out_path)
        try:
            page = vf.get_page(0)
            template_shapes = list(page.child_shapes)
            template_ids = {s.ID for s in template_shapes}
            rect_template = next(s for s in template_shapes if "RECTANGLE" in (s.text or ""))
            connector_template = next(s for s in template_shapes if "STRAIGHT_CONNECTOR" in (s.text or ""))

            shapes_by_node_id = {}
            for node in graph["nodes"]:
                shape = rect_template.copy()
                shape.text = node["label"]
                target_x, target_y = node["x"] / VSDX_SCALE, -(node["y"] / VSDX_SCALE)
                shape.move(target_x - shape.x, target_y - shape.y)
                shapes_by_node_id[node["id"]] = shape

            for edge in graph["edges"]:
                source = shapes_by_node_id.get(edge["source_node_id"])
                target = shapes_by_node_id.get(edge["target_node_id"])
                if source is None or target is None:
                    continue
                connector = connector_template.copy()
                connector.set_start_and_finish(source.center_x_y, target.center_x_y)
                connector.text = _vlan_label(edge)

            for shape in list(page.child_shapes):
                if shape.ID in template_ids:
                    shape.remove()

            vf.save_vsdx(out_path)
        finally:
            vf.close_vsdx()

        with open(out_path, "rb") as fh:
            return fh.read()
