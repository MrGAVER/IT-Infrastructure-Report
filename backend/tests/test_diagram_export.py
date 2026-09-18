"""
Тесты на backend/app/services/diagram_export.py — раздел 13 ТЗ диаграммы топологии сети:
".drawio/.vsdx — файл парсится обратно соответствующей библиотекой, число узлов совпадает с
ответом API; .svg — валидный XML, число узловых элементов совпадает с числом узлов графа, число
засечек порта на коммутаторе — с port_ticks дескриптора."

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_diagram_export.py -v
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from app.services.diagram_export import export_drawio, export_svg, export_vsdx


def _sample_graph(port_ticks: int = 24) -> dict:
    return {
        "nodes": [
            {
                "id": "dev-switch",
                "type": "device",
                "label": "sw-01",
                "x": 0,
                "y": 0,
                "icon": {"mode": "generated", "shape": "switch", "color": "#4f7cff", "port_ticks": port_ticks},
            },
            {
                "id": "dev-server",
                "type": "device",
                "label": "srv-01",
                "x": 300,
                "y": 0,
                "icon": {"mode": "generated", "shape": "server", "color": "#8a8f98"},
            },
            {"id": "group:building:none", "type": "group", "label": "Без здания (5)", "device_count": 5, "x": 600, "y": 0},
        ],
        "edges": [
            {
                "id": "conn-1",
                "source_node_id": "dev-switch",
                "target_node_id": "dev-server",
                "source_interface": {"id": "iface-1", "name": "Gi0/1", "port_index": 0},
                "target_interface": {"id": "iface-2", "name": "eth0"},
                "connection_type": "Витая пара",
                "is_active": True,
                "vlans": [{"id": "vlan-1", "vlan_id": 10, "name": "data"}],
            }
        ],
    }


def _empty_graph() -> dict:
    return {"nodes": [], "edges": []}


# --------------------------------------------------------------------------------------
# .svg
# --------------------------------------------------------------------------------------

def test_export_svg_is_valid_xml_with_matching_node_count():
    graph = _sample_graph()
    svg = export_svg(graph)
    root = ET.fromstring(svg)  # падает, если XML невалиден
    assert root.tag.endswith("svg")
    node_groups = [el for el in root.iter() if el.tag.endswith("g") and el.get("class", "").startswith("diagram-node")]
    assert len(node_groups) == len(graph["nodes"])


def test_export_svg_switch_port_ticks_count_matches_descriptor():
    graph = _sample_graph(port_ticks=24)
    svg = export_svg(graph)
    assert svg.count("port-tick") == 24


def test_export_svg_zero_port_ticks_renders_no_tick_elements():
    graph = _sample_graph(port_ticks=0)
    svg = export_svg(graph)
    assert svg.count("port-tick") == 0


@pytest.mark.parametrize("shape", ["switch", "switch_l2", "switch_l3"])
def test_export_svg_port_ticks_render_for_every_switch_variant(shape):
    """Пункт 5 правки "диаграмма топологии сети": раньше засечки рисовались только при
    shape == "switch" точным сравнением — после разделения на switch_l2/switch_l3
    (services/catalogs.py) это исключило бы обе новые формы. Регрессия на .startswith("switch")
    в _svg_node."""
    graph = _sample_graph(port_ticks=6)
    graph["nodes"][0]["icon"]["shape"] = shape
    svg = export_svg(graph)
    assert svg.count("port-tick") == 6


def test_export_svg_escapes_special_characters_in_label():
    graph = _sample_graph()
    graph["nodes"][0]["label"] = 'sw<01>&"test"'
    svg = export_svg(graph)
    ET.fromstring(svg)  # не должно падать на невалидном XML из-за спецсимволов
    assert "<01>" not in svg  # экранировано, не подставлено как сырой тег


def test_export_svg_handles_empty_graph():
    svg = export_svg(_empty_graph())
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")


def test_export_svg_custom_icon_embeds_svg_markup_verbatim():
    graph = _sample_graph()
    graph["nodes"][0]["icon"] = {"mode": "custom", "svg_markup": '<circle r="5" class="custom-mark"/>'}
    svg = export_svg(graph)
    assert "custom-mark" in svg


# --------------------------------------------------------------------------------------
# .drawio
# --------------------------------------------------------------------------------------

def _drawio_vertex_cells(xml_text: str):
    root = ET.fromstring(xml_text)
    return [cell for cell in root.iter("mxCell") if cell.get("vertex") == "1"]


def test_export_drawio_is_valid_xml_and_parses_back_with_matching_node_count():
    graph = _sample_graph()
    xml_text = export_drawio(graph)
    vertices = _drawio_vertex_cells(xml_text)
    # Значимые узлы (непустой value) — засечки портов тоже vertex-объекты, но с value="".
    named_vertices = [v for v in vertices if v.get("value")]
    assert len(named_vertices) == len(graph["nodes"])


def test_export_drawio_switch_port_ticks_rendered_as_separate_objects():
    graph = _sample_graph(port_ticks=24)
    xml_text = export_drawio(graph)
    vertices = _drawio_vertex_cells(xml_text)
    tick_objects = [v for v in vertices if not v.get("value")]
    assert len(tick_objects) == 24


@pytest.mark.parametrize("shape", ["switch", "switch_l2", "switch_l3"])
def test_export_drawio_port_ticks_render_for_every_switch_variant(shape):
    graph = _sample_graph(port_ticks=6)
    graph["nodes"][0]["icon"]["shape"] = shape
    xml_text = export_drawio(graph)
    vertices = _drawio_vertex_cells(xml_text)
    tick_objects = [v for v in vertices if not v.get("value")]
    assert len(tick_objects) == 6


def test_export_drawio_edge_count_matches_graph():
    graph = _sample_graph()
    xml_text = export_drawio(graph)
    root = ET.fromstring(xml_text)
    edges = [cell for cell in root.iter("mxCell") if cell.get("edge") == "1"]
    assert len(edges) == len(graph["edges"])


def test_export_drawio_handles_empty_graph():
    xml_text = export_drawio(_empty_graph())
    ET.fromstring(xml_text)


# --------------------------------------------------------------------------------------
# .vsdx
# --------------------------------------------------------------------------------------

def test_export_vsdx_parses_back_with_matching_node_count(tmp_path):
    vsdx = pytest.importorskip("vsdx")
    graph = _sample_graph()
    data = export_vsdx(graph)
    out_path = tmp_path / "diagram.vsdx"
    out_path.write_bytes(data)

    vf = vsdx.VisioFile(str(out_path))
    try:
        page = vf.get_page(0)
        shapes = list(page.child_shapes)
    finally:
        vf.close_vsdx()
    # Каждый узел графа -> одна скопированная фигура с его подписью; засечки портов не
    # воспроизводятся в .vsdx отдельными фигурами (ограничение библиотеки, см. docstring модуля).
    labels = {node["label"] for node in graph["nodes"]}
    matching = [s for s in shapes if (s.text or "").strip() in labels]
    assert len(matching) == len(graph["nodes"])


def test_export_vsdx_edge_connector_present(tmp_path):
    vsdx = pytest.importorskip("vsdx")
    graph = _sample_graph()
    data = export_vsdx(graph)
    out_path = tmp_path / "diagram_edge.vsdx"
    out_path.write_bytes(data)

    vf = vsdx.VisioFile(str(out_path))
    try:
        page = vf.get_page(0)
        shapes = list(page.child_shapes)
    finally:
        vf.close_vsdx()
    vlan_labelled = [s for s in shapes if "VLAN 10" in (s.text or "")]
    assert len(vlan_labelled) == 1
