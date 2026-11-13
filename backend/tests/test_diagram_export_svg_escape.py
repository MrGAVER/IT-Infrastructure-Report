"""
Код-ревью r3, ИА-02: `_esc` в svg.py экранирует и кавычки — значения атрибутов (`data-node-id`, `data-edge-id`, `fill`) подставляются тем же вызовом.

`xml.sax.saxutils.escape` без второго аргумента трогает только `& < >`. Сегодня id узлов — UUID, и внедрить атрибут нельзя, но функция названа
универсально: первый же id или цвет из пользовательского ввода превратил бы её в XSS в скачанном автономном .svg (атрибут события на `<g>` срабатывает).

Запуск: pytest backend/tests/test_diagram_export_svg_escape.py -v
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from app.services.diagram_export import export_svg
from app.services.diagram_export.svg import _esc

HOSTILE = 'x" onmouseover="alert(1)'
SVG_NS = "{http://www.w3.org/2000/svg}"


def _graph(node_id: str = "n1", edge_id: str = "e1", label: str = "sw-1") -> dict:
    def node(identifier: str, x: int) -> dict:
        icon = {"mode": "generated", "shape": "switch", "color": "#4f7cff", "glyph": '<rect x="2" y="6" width="20" height="9"/>', "port_ticks": 0}
        return {"id": identifier, "type": "device", "label": label, "x": x, "y": 0, "icon": icon}

    return {
        "nodes": [node(node_id, 0), node("n2", 300)],
        "edges": [{"id": edge_id, "source_node_id": node_id, "target_node_id": "n2", "connection_type": "Витая пара", "is_active": True, "vlans": []}],
    }


def test_esc_escapes_quotes_as_well_as_the_xml_specials():
    assert _esc("a\"b'c<d&e") == "a&quot;b&apos;c&lt;d&amp;e"


@pytest.mark.parametrize("empty", [None, ""])
def test_esc_keeps_returning_an_empty_string_for_missing_values(empty):
    assert _esc(empty) == ""


def test_esc_converts_non_strings():
    assert _esc(42) == "42"


def test_a_hostile_node_id_cannot_inject_an_attribute():
    svg = export_svg(_graph(node_id=HOSTILE))
    root = ET.fromstring(svg)  # документ остаётся корректным XML
    nodes = [g for g in root.iter(f"{SVG_NS}g") if g.get("class") == "diagram-node"]
    assert any(g.get("data-node-id") == HOSTILE for g in nodes), "значение должно сохраниться целиком — внутри атрибута"
    assert not [g for g in root.iter() if "onmouseover" in g.attrib], "на элементе не должно появиться атрибута события"


def test_a_hostile_edge_id_cannot_inject_an_attribute():
    svg = export_svg(_graph(edge_id=HOSTILE))
    root = ET.fromstring(svg)
    assert not [g for g in root.iter() if "onmouseover" in g.attrib]
    assert any(g.get("data-edge-id") == HOSTILE for g in root.iter(f"{SVG_NS}g"))


def test_a_hostile_label_stays_text():
    root = ET.fromstring(export_svg(_graph(label=HOSTILE + "'><script>alert(1)</script>")))
    assert not list(root.iter(f"{SVG_NS}script"))
    assert not [element for element in root.iter() if "onmouseover" in element.attrib]


def test_a_hostile_color_cannot_inject_an_attribute():
    graph = _graph()
    graph["nodes"][0]["icon"]["color"] = '#fff" onload="alert(1)'
    root = ET.fromstring(export_svg(graph))
    assert not [element for element in root.iter() if "onload" in element.attrib]
