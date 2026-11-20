"""Экспорт .vsdx: быстрое копирование фигур, размер шрифта подписей, засечки портов.

Три ограничения из README («Известные ограничения»), снятые вместе:
  • медленный экспорт (A-06): библиотека vsdx при каждом копировании фигуры обходила всю страницу — n копий стоили n² обходов;
  • размер шрифта подписей не совпадал с .svg/.drawio: у шаблонных фигур нет секции Character, а vsdx не умеет создавать её с нуля;
  • у .vsdx не было фигур-засечек портов (коннектор целился в точку на грани, но самой отметки там не было).

Здесь проверяется то, что видно в XML страницы; как это рисует LibreOffice — смотрели глазами, автоматически это не проверить
(Visio в среде тестов нет).
Запуск: pytest backend/tests/test_diagram_export_vsdx_details.py -v
"""

from __future__ import annotations

import copy
import io
import os
import shutil
import xml.etree.ElementTree as ET
import zipfile

import pytest
import vsdx

from app.services.diagram_export import NODE_HEIGHT, NODE_WIDTH, export_vsdx
from app.services.diagram_export._common import DIAGRAM_EDGE_FONT_SIZE, DIAGRAM_NODE_FONT_SIZE, PORT_TICK_HEIGHT, PORT_TICK_WIDTH
from test_diagram_export import CUSTOM_SVG, _custom_graph, _sample_graph


SCALE = 100.0  # VSDX_SCALE: пиксели графа -> дюймы Visio


def _page_shapes(data: bytes) -> list[dict]:
    """Фигуры страницы: {ячейка: значение V, "_el": элемент, "_text": текст}; ячейки читаются из самого XML, без библиотеки vsdx."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        root = ET.fromstring(zf.read("visio/pages/page1.xml"))
    shapes = []
    for el in root.iter():
        if not el.tag.endswith("}Shape"):
            continue
        cells = {c.get("N"): c.get("V") for c in el if c.tag.endswith("}Cell")}
        text = next((t.text or "" for t in el if t.tag.endswith("}Text")), "")
        shapes.append({**cells, "_el": el, "_text": text.strip()})
    return shapes


def _ticks(shapes: list[dict]) -> list[dict]:
    """Фигуры-засечки: размер PORT_TICK_WIDTH x PORT_TICK_HEIGHT (в дюймах) — другого такого размера на странице нет."""
    return [s for s in shapes if s.get("Width") and abs(float(s["Width"]) - PORT_TICK_WIDTH / SCALE) < 1e-9 and abs(float(s["Height"]) - PORT_TICK_HEIGHT / SCALE) < 1e-9]


def _character_size(shape: dict) -> float | None:
    for section in shape["_el"]:
        if section.tag.endswith("}Section") and section.get("N") == "Character":
            return float(next(c.get("V") for c in section.iter() if c.tag.endswith("}Cell") and c.get("N") == "Size"))
    return None


# ----- быстрое копирование фигур -------------------------------------------------------------------------------------------


def _fresh_template_page(tmp_path, name: str):
    template_path = os.path.join(os.path.dirname(vsdx.__file__), "media", "media.vsdx")
    path = tmp_path / name
    shutil.copy(template_path, path)
    vf = vsdx.VisioFile(str(path))
    return vf, vf.get_page(0)


def test_shape_template_copy_is_identical_to_library_copy(tmp_path):
    """_ShapeTemplate.copy() — это Shape.copy() без обхода страницы на каждую копию: XML и назначенный ID обязаны совпадать.
    Тест же — страж при обновлении vsdx: метод опирается на VisioFile.increment_shape_ids/update_ids и Page.set_max_ids."""
    from app.services.diagram_export.vsdx import _ShapeTemplate

    def rectangle(page):
        return next(s for s in page.child_shapes if "RECTANGLE" in (s.text or ""))

    fast_vf, fast_page = _fresh_template_page(tmp_path, "fast.vsdx")
    slow_vf, slow_page = _fresh_template_page(tmp_path, "slow.vsdx")
    try:
        template = _ShapeTemplate(rectangle(fast_page))
        fast = [template.copy() for _ in range(3)]
        slow = [rectangle(slow_page).copy() for _ in range(3)]
        for new, library in zip(fast, slow):
            assert new.ID == library.ID
            assert ET.tostring(new.xml) == ET.tostring(library.xml)
        assert len({s.ID for s in fast}) == 3
    finally:
        fast_vf.close_vsdx()
        slow_vf.close_vsdx()


def test_export_vsdx_walks_the_page_a_constant_number_of_times(monkeypatch):
    """Регрессия A-06: число обходов страницы не должно расти с числом фигур (раньше — по обходу на каждую копию, то есть n² работы).
    Считаем вызовы Page.set_max_ids: по одному на шаблон, независимо от размера графа."""
    from vsdx import Page

    calls = []
    original = Page.set_max_ids

    def counting(self):
        calls.append(1)
        return original(self)

    monkeypatch.setattr(Page, "set_max_ids", counting)
    base = _sample_graph(6)["nodes"][0]
    nodes = [{**copy.deepcopy(base), "id": f"n{i}", "x": (i % 8) * 200, "y": (i // 8) * 100} for i in range(40)]
    edges = [{"id": f"e{i}", "source_node_id": f"n{i}", "target_node_id": f"n{i + 1}", "source_interface": {"port_index": 2}, "target_interface": None, "is_active": True, "vlans": []} for i in range(39)]
    export_vsdx({"nodes": nodes, "edges": edges})
    assert len(calls) <= 2  # шаблон узла и шаблон коннектора; при 40 узлах, 240 засечках и 39 рёбрах


def test_export_vsdx_shape_ids_stay_unique_with_ticks():
    base = _sample_graph(8)["nodes"][0]
    nodes = [{**copy.deepcopy(base), "id": f"n{i}", "x": i * 200, "y": 0} for i in range(5)]
    ids = [int(el["_el"].get("ID")) for el in _page_shapes(export_vsdx({"nodes": nodes, "edges": []}))]
    assert len(ids) == len(set(ids)) and len(ids) >= 5 * (1 + 8)


# ----- засечки портов ------------------------------------------------------------------------------------------------------


def test_export_vsdx_draws_one_tick_shape_per_port_tick():
    shapes = _page_shapes(export_vsdx(_sample_graph(port_ticks=6)))
    assert len(_ticks(shapes)) == 6


def test_export_vsdx_ticks_sit_on_the_bottom_edge_evenly_spread():
    """Центр засечки i — на доле (i+1)/(n+1) ширины узла, а её нижний край — на нижней грани узла (в осях Visio «низ» — меньший Y)."""
    n = 5
    shapes = _page_shapes(export_vsdx(_sample_graph(port_ticks=n)))
    node = next(s for s in shapes if s["_text"] == "sw-01")
    left = float(node["PinX"]) - float(node["Width"]) / 2
    bottom = float(node["PinY"]) - float(node["Height"]) / 2
    ticks = sorted(_ticks(shapes), key=lambda s: float(s["PinX"]))
    assert len(ticks) == n
    for i, tick in enumerate(ticks):
        assert float(tick["PinX"]) == pytest.approx(left + float(node["Width"]) * (i + 1) / (n + 1))
        assert float(tick["PinY"]) - float(tick["Height"]) / 2 == pytest.approx(bottom)
    assert float(node["Width"]) == pytest.approx(NODE_WIDTH / SCALE) and float(node["Height"]) == pytest.approx(NODE_HEIGHT / SCALE)


def test_export_vsdx_connector_starts_at_the_tick_it_is_bound_to():
    """_sample_graph: ребро выходит из порта port_index=0 коммутатора — коннектор должен начинаться над первой засечкой (теперь она видна)."""
    shapes = _page_shapes(export_vsdx(_sample_graph(port_ticks=6)))
    first_tick = min(_ticks(shapes), key=lambda s: float(s["PinX"]))
    connector = next(s for s in shapes if "BeginX" in s)
    assert float(connector["BeginX"]) == pytest.approx(float(first_tick["PinX"]))


def test_export_vsdx_tick_shapes_are_lean_and_unlabelled():
    shapes = _page_shapes(export_vsdx(_sample_graph(port_ticks=3)))
    for tick in _ticks(shapes):
        assert tick["_text"] == ""
        assert tick["FillForegnd"].lower() == "#222222"
        assert not any(section.get("N") == "Property" for section in tick["_el"] if section.tag.endswith("}Section"))  # без шаблонных «property value»


@pytest.mark.parametrize("ticks", [0, None])
def test_export_vsdx_without_port_ticks_draws_none(ticks):
    graph = _sample_graph(port_ticks=0)
    if ticks is None:
        del graph["nodes"][0]["icon"]["port_ticks"]
    assert _ticks(_page_shapes(export_vsdx(graph))) == []


def test_export_vsdx_group_and_custom_icon_nodes_get_no_ticks():
    """Как в .svg: у группы своих портов нет, а у плитки custom-иконки засечки не рисуются, даже если дескриптор несёт port_ticks."""
    graph = _custom_graph(CUSTOM_SVG)
    graph["nodes"][0]["icon"]["port_ticks"] = 4
    graph["nodes"].append({"id": "g", "type": "group", "label": "Группа", "device_count": 1, "x": 400, "y": 0})
    assert _ticks(_page_shapes(export_vsdx(graph))) == []


# ----- размер шрифта -------------------------------------------------------------------------------------------------------


def test_export_vsdx_node_labels_use_the_same_font_size_as_svg_and_drawio():
    """Размер подписи узла и группы — DIAGRAM_NODE_FONT_SIZE, переведённый в дюймы тем же масштабом, что и размеры фигур."""
    shapes = _page_shapes(export_vsdx(_sample_graph(port_ticks=2)))
    labelled = {s["_text"]: s for s in shapes if s["_text"] in ("sw-01", "srv-01", "Без здания (5)")}
    assert set(labelled) == {"sw-01", "srv-01", "Без здания (5)"}
    for shape in labelled.values():
        assert _character_size(shape) == pytest.approx(DIAGRAM_NODE_FONT_SIZE / SCALE)


def test_export_vsdx_edge_label_uses_the_edge_font_size_and_empty_label_adds_nothing():
    graph = _sample_graph(port_ticks=2)  # у единственного ребра есть VLAN, то есть подпись
    with_label = next(s for s in _page_shapes(export_vsdx(graph)) if "BeginX" in s)
    assert with_label["_text"] and _character_size(with_label) == pytest.approx(DIAGRAM_EDGE_FONT_SIZE / SCALE)

    graph["edges"][0]["vlans"] = []
    without_label = next(s for s in _page_shapes(export_vsdx(graph)) if "BeginX" in s)
    assert without_label["_text"] == "" and _character_size(without_label) is None


def test_export_vsdx_character_section_precedes_geometry():
    """Section Character — перед Geometry, как пишет сам Visio; обе в виде одного экземпляра на фигуру."""
    node = next(s for s in _page_shapes(export_vsdx(_sample_graph(port_ticks=2))) if s["_text"] == "sw-01")
    names = [section.get("N") for section in node["_el"] if section.tag.endswith("}Section")]
    assert names.count("Character") == 1 and names.count("Geometry") == 1
    assert names.index("Character") < names.index("Geometry")


def test_export_vsdx_with_ticks_and_font_sections_reads_back_with_the_library(tmp_path):
    """Файл остаётся корректным пакетом: открывается самой vsdx, фигуры на месте (без «xmlns:nsN» — см. _finalize_vsdx_package)."""
    path = tmp_path / "ticks.vsdx"
    data = export_vsdx(_sample_graph(port_ticks=6))
    path.write_bytes(data)
    with zipfile.ZipFile(path) as zf:
        assert b"xmlns:ns" not in zf.read("visio/pages/page1.xml")
    vf = vsdx.VisioFile(str(path))
    try:
        texts = [(s.text or "").strip() for s in vf.get_page(0).child_shapes]
    finally:
        vf.close_vsdx()
    assert {"sw-01", "srv-01", "Без здания (5)"} <= set(texts)
