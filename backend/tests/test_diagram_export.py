"""
Тесты на backend/app/services/diagram_export.py — раздел 13 ТЗ диаграммы топологии сети:
".drawio/.vsdx — файл парсится обратно соответствующей библиотекой, число узлов совпадает с
ответом API; .svg — валидный XML, число узловых элементов совпадает с числом узлов графа, число
засечек порта на коммутаторе — с port_ticks дескриптора."

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_diagram_export.py -v
"""
from __future__ import annotations

import base64
import io
import logging
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import quote, unquote

import pytest

from app.services.diagram_export import (
    CUSTOM_ICON_TILE_HEIGHT,
    GROUP_FILL_COLOR,
    DIAGRAM_FONT_FAMILY,
    MAX_CUSTOM_ICON_SVG_LENGTH,
    NODE_HEIGHT,
    NODE_WIDTH,
    _custom_icon_tile_svg,
    _device_fill_color,
    _rasterize_custom_icon_png,
    _standalone_custom_svg,
    export_drawio,
    export_svg,
    export_vsdx,
)


def _sample_graph(port_ticks: int = 24) -> dict:
    return {
        "nodes": [
            {
                "id": "dev-switch",
                "type": "device",
                "label": "sw-01",
                "x": 0,
                "y": 0,
                "icon": {"mode": "generated", "shape": "switch", "color": "#4f7cff", "glyph": '<rect x="2" y="6" width="20" height="9"/>', "port_ticks": port_ticks},
            },
            {
                "id": "dev-server",
                "type": "device",
                "label": "srv-01",
                "x": 300,
                "y": 0,
                "icon": {"mode": "generated", "shape": "server", "color": "#8a8f98", "glyph": '<rect x="4" y="2" width="16" height="20"/>'},
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


def test_export_svg_custom_icon_is_embedded_as_a_nested_image():
    """Код-ревью п. 4: разметка иконки не вставляется в документ как есть, а кладётся вложенным
    изображением (data URI) — содержимое при этом сохраняется целиком (см. также test_code_review_security)."""
    graph = _sample_graph()
    graph["nodes"][0]["icon"] = {"mode": "custom", "svg_markup": '<circle r="5" class="custom-mark"/>'}
    svg = export_svg(graph)
    ET.fromstring(svg)  # документ остаётся корректным XML
    match = re.search(r'href="data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)"', svg)
    assert match and "custom-mark" in base64.b64decode(match.group(1)).decode("utf-8")
    assert 'class="custom-mark"' not in svg


def test_export_svg_renders_category_glyph_path_from_descriptor():
    """Находка №3 отчёта (Фаза 2, п.2): путь глифа берётся из icon["glyph"] (единый источник —
    diagram_icons.py:SHAPE_GLYPHS), а не вычисляется самим экспортёром по имени формы."""
    graph = _sample_graph()
    svg = export_svg(graph)
    switch_glyph = graph["nodes"][0]["icon"]["glyph"]
    assert switch_glyph in svg


def test_export_svg_edge_anchors_to_resolved_port_tick_not_center():
    """Находка №2 отчёта об экспорте (Фаза 2, п.1): ребро с известным port_index должно
    целиться в конкретную засечку порта (x + spacing*(port_index+1), y + height), а не в центр
    узла. _sample_graph(): switch (x=0,y=0), source_interface.port_index=0, port_ticks=24 по
    умолчанию -> fraction=1/25, ожидаемый x = 160*1/25 = 6.4, y = 70 (нижняя грань)."""
    graph = _sample_graph()
    svg = export_svg(graph)
    root = ET.fromstring(svg)
    line = next(el for el in root.iter() if el.tag.endswith("line"))
    assert float(line.get("x1")) == pytest.approx(6.4)
    assert float(line.get("y1")) == pytest.approx(70.0)
    # Целевая сторона (dev-server) интерфейса без port_index — прежнее поведение, центр узла.
    assert float(line.get("x2")) == pytest.approx(300 + NODE_WIDTH / 2)


def test_export_svg_edge_falls_back_to_center_without_port_index():
    graph = _sample_graph()
    graph["nodes"][0]["icon"]["port_ticks"] = 0
    del graph["edges"][0]["source_interface"]["port_index"]
    svg = export_svg(graph)
    root = ET.fromstring(svg)
    line = next(el for el in root.iter() if el.tag.endswith("line"))
    assert float(line.get("x1")) == pytest.approx(0 + NODE_WIDTH / 2)
    assert float(line.get("y1")) == pytest.approx(0 + NODE_HEIGHT / 2)


def test_export_svg_uses_explicit_font_for_every_text_element():
    """Находка №4 отчёта (Фаза 2, п.4): единый явный шрифт вместо дефолта браузера/движка —
    у КАЖДОГО <text> (подписи узла, группы, ребра), а не только у части."""
    graph = _sample_graph()
    svg = export_svg(graph)
    root = ET.fromstring(svg)
    texts = list(root.iter("{http://www.w3.org/2000/svg}text"))
    assert texts, "ожидался хотя бы один <text> элемент"
    assert all(t.get("font-family") == DIAGRAM_FONT_FAMILY for t in texts)


# --------------------------------------------------------------------------------------
# .drawio
# --------------------------------------------------------------------------------------

def _drawio_vertex_cells(xml_text: str):
    root = ET.fromstring(xml_text)
    return [cell for cell in root.iter("mxCell") if cell.get("vertex") == "1"]


def _drawio_tick_cells(vertices):
    """Засечки порта — vertex-объекты с пустым value, КРОМЕ глифа категории (Фаза 2, п.2), у
    которого value тоже пусто, но стиль — shape=image (см. _glyph_data_uri), а не заливка."""
    return [v for v in vertices if not v.get("value") and "shape=image" not in v.get("style", "")]


def test_export_drawio_is_valid_xml_and_parses_back_with_matching_node_count():
    graph = _sample_graph()
    xml_text = export_drawio(graph)
    vertices = _drawio_vertex_cells(xml_text)
    # Значимые узлы (непустой value) — засечки портов и глиф категории тоже vertex-объекты, но
    # с value="".
    named_vertices = [v for v in vertices if v.get("value")]
    assert len(named_vertices) == len(graph["nodes"])


def test_export_drawio_switch_port_ticks_rendered_as_separate_objects():
    graph = _sample_graph(port_ticks=24)
    xml_text = export_drawio(graph)
    vertices = _drawio_vertex_cells(xml_text)
    tick_objects = _drawio_tick_cells(vertices)
    assert len(tick_objects) == 24


@pytest.mark.parametrize("shape", ["switch", "switch_l2", "switch_l3"])
def test_export_drawio_port_ticks_render_for_every_switch_variant(shape):
    graph = _sample_graph(port_ticks=6)
    graph["nodes"][0]["icon"]["shape"] = shape
    xml_text = export_drawio(graph)
    vertices = _drawio_vertex_cells(xml_text)
    tick_objects = _drawio_tick_cells(vertices)
    assert len(tick_objects) == 6


def test_export_drawio_category_glyph_rendered_as_image_shape():
    """Находка №3 отчёта (Фаза 2, п.2): глиф категории — отдельный vertex со style=shape=image
    и data URI, содержащим тот же path, что icon["glyph"] (единый источник — diagram_icons.py:
    SHAPE_GLYPHS, см. docstring _glyph_data_uri)."""
    graph = _sample_graph()
    xml_text = export_drawio(graph)
    vertices = _drawio_vertex_cells(xml_text)
    glyph_cells = [v for v in vertices if "shape=image" in v.get("style", "")]
    # По одному глифу на каждый generated-узел (switch + server); группа глифа не имеет.
    assert len(glyph_cells) == 2
    switch_glyph = graph["nodes"][0]["icon"]["glyph"]
    assert any(quote(switch_glyph) in v.get("style", "") for v in glyph_cells)


def test_export_drawio_uses_explicit_font_for_nodes_and_edges():
    """Находка №4 отчёта (Фаза 2, п.4): единый явный шрифт вместо дефолта draw.io — у узлов,
    групп и меток связей (через text_format, не через style_attributes — см. docstring
    вызывающего кода про особенность Edge.style_attributes). Декоративные объекты без текста
    (засечки порта, глиф категории) шрифт не выставляют — им нечего им подписывать."""
    graph = _sample_graph()
    xml_text = export_drawio(graph)
    root = ET.fromstring(xml_text)
    labelled_cells = [
        cell for cell in root.iter("mxCell") if cell.get("value") and (cell.get("vertex") == "1" or cell.get("edge") == "1")
    ]
    assert len(labelled_cells) == len(graph["nodes"]) + len(graph["edges"])
    assert all(f"fontFamily={DIAGRAM_FONT_FAMILY};" in cell.get("style", "") for cell in labelled_cells)


def test_export_drawio_edge_count_matches_graph():
    graph = _sample_graph()
    xml_text = export_drawio(graph)
    root = ET.fromstring(xml_text)
    edges = [cell for cell in root.iter("mxCell") if cell.get("edge") == "1"]
    assert len(edges) == len(graph["edges"])


def test_export_drawio_edge_exit_fraction_matches_resolved_port():
    """Находка №2 отчёта (Фаза 2, п.1): exitX/exitY как доля 0-1 от габарита фигуры, а не
    отсутствие entry/exit (== автомаршрутизация drawio.js в центр). _sample_graph(): source
    port_index=0, port_ticks=24 -> exitX=1/25; target-интерфейс без port_index -> entryX не
    должен быть выставлен вовсе (прежнее поведение — автовыбор точки)."""
    graph = _sample_graph()
    xml_text = export_drawio(graph)
    root = ET.fromstring(xml_text)
    edge_style = next(cell.get("style", "") for cell in root.iter("mxCell") if cell.get("edge") == "1")
    assert "exitX=0.04;" in edge_style
    assert "exitY=1.0;" in edge_style
    assert "entryX=" not in edge_style


def test_export_drawio_handles_empty_graph():
    xml_text = export_drawio(_empty_graph())
    ET.fromstring(xml_text)


# --------------------------------------------------------------------------------------
# .vsdx
# --------------------------------------------------------------------------------------

def test_export_vsdx_embeds_category_icon_as_foreign_data(tmp_path):
    """Находка №5 отчёта (Фаза 3, п.5, часть 2): иконка категории встраивается как отдельная
    фигура-картинка (ForeignData/Rel — см. docstring _embed_vsdx_category_icons) поверх основной
    фигуры узла. ВАЖНО: это проверяет структурную корректность пакета (открывается обратно самой
    vsdx, содержит валидный PNG, связи и Content-Type на месте) — НЕ визуальную отрисовку;
    сторонний инструмент проверки (headless LibreOffice) для этой конкретной фигуры недоступен
    как оракул, см. learnings в памяти проекта."""
    vsdx = pytest.importorskip("vsdx")
    graph = _sample_graph()
    data = export_vsdx(graph)
    out_path = tmp_path / "diagram_icon.vsdx"
    out_path.write_bytes(data)

    # 1. Пакет остаётся валидным ZIP/XML и читается обратно самой vsdx без исключений.
    vf = vsdx.VisioFile(str(out_path))
    try:
        page = vf.get_page(0)
        shapes = list(page.child_shapes)
        assert len(shapes) >= len(graph["nodes"])  # + отдельные фигуры-иконки поверх узлов
    finally:
        vf.close_vsdx()

    # 2. ForeignData/Rel присутствует хотя бы у одной фигуры, PNG-часть существует и валидна.
    with zipfile.ZipFile(out_path) as zf:
        names = zf.namelist()
        page1 = zf.read("visio/pages/page1.xml").decode("utf-8")
        assert "<ForeignData" in page1
        assert 'ForeignType="Bitmap"' in page1

        media_names = [n for n in names if n.startswith("visio/media/image")]
        assert media_names
        png_bytes = zf.read(media_names[0])
        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")  # сигнатура PNG

        rels = zf.read("visio/pages/_rels/page1.xml.rels").decode("utf-8")
        assert 'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"' in rels

        content_types = zf.read("[Content_Types].xml").decode("utf-8")
        assert 'Extension="png"' in content_types


def test_export_vsdx_dedupes_identical_glyph_to_one_image(tmp_path):
    """Два устройства одной категории (одинаковый icon["glyph"]) должны переиспользовать ОДНУ
    картинку, а не плодить дубликаты — см. glyph_rel_ids в export_vsdx."""
    pytest.importorskip("vsdx")
    same_glyph = '<rect x="2" y="2" width="20" height="20"/>'
    graph = {
        "nodes": [
            {"id": "a", "type": "device", "label": "a", "x": 0, "y": 0,
             "icon": {"mode": "generated", "shape": "server", "color": "#4f7cff", "glyph": same_glyph}},
            {"id": "b", "type": "device", "label": "b", "x": 300, "y": 0,
             "icon": {"mode": "generated", "shape": "server", "color": "#e67e22", "glyph": same_glyph}},
        ],
        "edges": [],
    }
    data = export_vsdx(graph)
    out_path = tmp_path / "diagram_dedup.vsdx"
    out_path.write_bytes(data)

    with zipfile.ZipFile(out_path) as zf:
        media_names = [n for n in zf.namelist() if n.startswith("visio/media/image")]
        assert len(media_names) == 1


def test_export_vsdx_without_glyphs_has_no_media(tmp_path):
    """Сгенерированная иконка без glyph и группа не должны создавать ни одной картинки-оверлея.
    (Custom-иконки картинку создают — см. test_export_vsdx_custom_icon_* ниже.)"""
    pytest.importorskip("vsdx")
    graph = {
        "nodes": [
            {"id": "a", "type": "device", "label": "a", "x": 0, "y": 0,
             "icon": {"mode": "generated", "shape": "server", "color": "#4f7cff"}},
            {"id": "g", "type": "group", "label": "group", "x": 300, "y": 0},
        ],
        "edges": [],
    }
    data = export_vsdx(graph)
    out_path = tmp_path / "diagram_no_icons.vsdx"
    out_path.write_bytes(data)

    with zipfile.ZipFile(out_path) as zf:
        media_names = [n for n in zf.namelist() if n.startswith("visio/media/")]
        assert media_names == []


def test_export_vsdx_icon_shape_has_no_leftover_template_text(tmp_path):
    """Если ForeignData не распознаётся читателем, фигура откатывается на обычную геометрию —
    без явной очистки показала бы унаследованный от шаблона текст "RECTANGLE" (см. docstring в
    export_vsdx). Проверяем, что среди фигур нет ни одной с таким текстом."""
    vsdx = pytest.importorskip("vsdx")
    graph = _sample_graph()
    data = export_vsdx(graph)
    out_path = tmp_path / "diagram_icon_text.vsdx"
    out_path.write_bytes(data)

    vf = vsdx.VisioFile(str(out_path))
    try:
        page = vf.get_page(0)
        texts = [(s.text or "").strip() for s in page.child_shapes]
        assert "RECTANGLE" not in texts
        assert "CONNECTED_SHAPE" not in texts
    finally:
        vf.close_vsdx()


def test_export_vsdx_page_fits_content_bounding_box(tmp_path):
    """Находка №5 отчёта (Фаза 2, п.3): страница подгоняется под фактический охват графа
    (тот же расчёт с отступом 40px, что и viewBox в export_svg), а не остаётся фиксированного
    размера шаблона A4 — иначе большой граф обрезался бы, а маленький терялся на пустом листе."""
    vsdx = pytest.importorskip("vsdx")
    graph = {
        "nodes": [
            {"id": "a", "type": "device", "label": "a", "x": 0, "y": 0, "icon": {"mode": "generated", "shape": "server", "color": "#4f7cff"}},
            {"id": "b", "type": "device", "label": "b", "x": 800, "y": 400, "icon": {"mode": "generated", "shape": "server", "color": "#4f7cff"}},
        ],
        "edges": [],
    }
    data = export_vsdx(graph)
    out_path = tmp_path / "diagram_page_fit.vsdx"
    out_path.write_bytes(data)

    vf = vsdx.VisioFile(str(out_path))
    try:
        page = vf.get_page(0)
        expected_width = (800 + NODE_WIDTH + 40) / 100.0
        expected_height = (400 + NODE_HEIGHT + 40) / 100.0
        assert page.width == pytest.approx(expected_width)
        assert page.height == pytest.approx(expected_height)
    finally:
        vf.close_vsdx()


def test_export_vsdx_empty_graph_keeps_template_page_size(tmp_path):
    vsdx = pytest.importorskip("vsdx")
    data = export_vsdx({"nodes": [], "edges": []})
    out_path = tmp_path / "diagram_empty.vsdx"
    out_path.write_bytes(data)

    vf = vsdx.VisioFile(str(out_path))
    try:
        page = vf.get_page(0)
        # Размер шаблона media.vsdx (A4) — не 0x0 и не какое-то произвольное значение.
        assert page.width == pytest.approx(8.26771653543307)
        assert page.height == pytest.approx(11.69291338582677)
    finally:
        vf.close_vsdx()



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


def test_export_vsdx_edge_anchors_to_resolved_port_not_shape_center(tmp_path):
    """Находка №2 отчёта (Фаза 2, п.1): для конца ребра с известным port_index точка коннектора
    должна лежать на нижней грани фигуры (в терминах графа) на нужной доле ширины, а не в
    center_x_y. _sample_graph(): source_interface.port_index=0 на switch (port_ticks=24)."""
    vsdx = pytest.importorskip("vsdx")
    graph = _sample_graph()
    data = export_vsdx(graph)
    out_path = tmp_path / "diagram_port_anchor.vsdx"
    out_path.write_bytes(data)

    vf = vsdx.VisioFile(str(out_path))
    try:
        page = vf.get_page(0)
        shapes = list(page.child_shapes)
        switch_shape = next(s for s in shapes if (s.text or "").strip() == "sw-01")
        connector = next(s for s in shapes if s.cell_value("BeginX") is not None)

        expected_x = (switch_shape.x - switch_shape.width / 2) + switch_shape.width * (1 / 25)
        expected_y = switch_shape.y - switch_shape.height / 2
        assert float(connector.cell_value("BeginX")) == pytest.approx(expected_x, abs=1e-6)
        assert float(connector.cell_value("BeginY")) == pytest.approx(expected_y, abs=1e-6)
        # Не должно случайно совпасть с центром фигуры — иначе тест не отличил бы старое
        # поведение (center_x_y) от нового (анкер на грани).
        assert float(connector.cell_value("BeginX")) != pytest.approx(switch_shape.x, abs=1e-6)
    finally:
        vf.close_vsdx()


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


# --------------------------------------------------------------------------------------
# Паритет атрибутов между форматами и открываемость .vsdx сторонним ПО (Фаза 1, п.7 плана
# доработок экспорта диаграмм: "тест на паритет атрибутов и открываемость файла — один и тот же
# тестовый граф прогоняется через все три экспортёра, проверяется совпадение «цвет узла
# присутствует» / «группа отличима от устройства» / «неактивное ребро визуально помечено»").
# --------------------------------------------------------------------------------------

def _parity_graph() -> dict:
    """_sample_graph() + одно неактивное ребро на уже имеющуюся в ней группу — минимальное
    расширение, не меняющее число узлов/рёбер, на которое опираются остальные тесты выше."""
    graph = _sample_graph()
    graph["edges"].append(
        {
            "id": "conn-2",
            "source_node_id": "dev-switch",
            "target_node_id": "group:building:none",
            "source_interface": {"id": "iface-3", "name": "Gi0/2"},
            "target_interface": None,
            "connection_type": "Витая пара",
            "is_active": False,
            "vlans": [],
        }
    )
    return graph


def test_export_svg_group_and_inactive_edge_marked_visually():
    graph = _parity_graph()
    svg = export_svg(graph)
    assert f'fill="{graph["nodes"][0]["icon"]["color"]}"' in svg  # цвет категории есть
    assert "stroke-dasharray" in svg  # у группы И у неактивного ребра — есть хоть один пунктир


def test_export_drawio_group_and_inactive_edge_marked_visually():
    graph = _parity_graph()
    xml_text = export_drawio(graph)
    root = ET.fromstring(xml_text)

    vertex_styles = [cell.get("style", "") for cell in root.iter("mxCell") if cell.get("vertex") == "1"]
    assert any(f'fillColor={graph["nodes"][0]["icon"]["color"]}' in s for s in vertex_styles)
    assert any("dashed=1" in s for s in vertex_styles)  # группа
    assert any("rounded=1" in s for s in vertex_styles)

    edge_styles = [cell.get("style", "") for cell in root.iter("mxCell") if cell.get("edge") == "1"]
    assert edge_styles
    # Раздел 4.3 ТЗ / находка отчёта: связь между устройствами не имеет "направления" —
    # стрелок не должно быть ни у одного ребра, как и в .svg/.vsdx.
    assert all("endArrow=none" in s for s in edge_styles)
    # Ровно одно (неактивное) ребро из двух помечено пунктиром (pattern="dashed_medium" ->
    # dashed=1;dashPattern=...) — активное остаётся сплошной линией, иначе их не различить.
    dashed_count = sum("dashed=1" in s for s in edge_styles)
    assert dashed_count == 1
    assert dashed_count < len(edge_styles)


def test_export_vsdx_group_and_device_and_inactive_edge_distinguishable(tmp_path):
    """Паритет с .svg/.drawio: группа должна визуально отличаться от устройства (иначе на
    .vsdx-экспорте их не различить), а неактивное ребро — быть помечено пунктиром."""
    vsdx = pytest.importorskip("vsdx")
    graph = _parity_graph()
    data = export_vsdx(graph)
    out_path = tmp_path / "diagram_parity.vsdx"
    out_path.write_bytes(data)

    vf = vsdx.VisioFile(str(out_path))
    try:
        page = vf.get_page(0)
        shapes = list(page.child_shapes)
        by_text = {(s.text or "").strip(): s for s in shapes}

        switch_shape = by_text["sw-01"]
        assert switch_shape.fill_color.lower() == graph["nodes"][0]["icon"]["color"].lower()

        group_shape = by_text["Без здания (5)"]
        assert group_shape.fill_color.lower() == GROUP_FILL_COLOR.lower()
        assert group_shape.cell_value("LinePattern") == "2"  # пунктирная рамка группы

        # Устройство (в отличие от группы) пунктирную рамку получать не должно.
        assert switch_shape.cell_value("LinePattern") is None

        inactive_connectors = [
            s for s in shapes if s.cell_value("LinePattern") == "2" and s is not group_shape
        ]
        assert len(inactive_connectors) == 1  # ровно один коннектор помечен как неактивный
    finally:
        vf.close_vsdx()


def test_export_vsdx_opens_in_third_party_reader(tmp_path):
    """Находка №1 отчёта об экспорте диаграмм: .vsdx мог читаться обратно самой библиотекой
    vsdx, но открываться ПОЛНОСТЬЮ ПУСТЫМ листом в стороннем ПО (см. docstring модуля и
    _finalize_vsdx_package). LibreOffice — не единственный сторонний читатель в природе, но
    самый доступный для автоматической проверки; отсутствие soffice в окружении не должно
    ронять пайплайн — тест в этом случае пропускается, а не падает."""
    pytest.importorskip("vsdx")
    soffice = shutil.which("soffice")
    if not soffice:
        pytest.skip("soffice (LibreOffice) недоступен в этом окружении")

    graph = _parity_graph()
    data = export_vsdx(graph)
    src_path = tmp_path / "diagram_openability.vsdx"
    src_path.write_bytes(data)

    result = subprocess.run(
        [soffice, "--headless", "--convert-to", "png", "--outdir", str(tmp_path), str(src_path)],
        capture_output=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")

    png_path = tmp_path / "diagram_openability.png"
    assert png_path.exists()
    # Пустой (полностью белый) лист LibreOffice отдаёт заметно меньшим PNG, чем лист с реальным
    # содержимым (см. отчёт и docstring _finalize_vsdx_package: воспроизведённый пустой рендер
    # ~6 КБ против ~15-26 КБ для того же графа с фигурами). Порог с большим запасом ниже
    # наблюдавшегося "пустого" размера, чтобы не быть хрупким к мелким изменениям рендеринга.
    assert png_path.stat().st_size > 8_000


# --------------------------------------------------------------------------------------
# Пользовательские (custom) иконки в .drawio/.vsdx и размер узлов .vsdx (Фаза 3, п.5)
# --------------------------------------------------------------------------------------

CUSTOM_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<circle cx="12" cy="12" r="9" fill="none" stroke="#33c9a7" stroke-width="2"/></svg>'
)


def _custom_graph(*markups: str, x_step: int = 220) -> dict:
    return {
        "nodes": [
            {"id": f"c{i}", "type": "device", "label": f"c{i}", "x": i * x_step, "y": 0,
             "icon": {"mode": "custom", "svg_markup": markup}}
            for i, markup in enumerate(markups)
        ],
        "edges": [],
    }


def _vsdx_media(data: bytes, tmp_path) -> list[str]:
    out_path = tmp_path / "custom.vsdx"
    out_path.write_bytes(data)
    with zipfile.ZipFile(out_path) as zf:
        return [n for n in zf.namelist() if n.startswith("visio/media/image")]


@pytest.mark.parametrize(
    ("markup", "expected_fragments", "forbidden_fragments"),
    [
        # голый фрагмент: координаты — пиксели бокса узла, как в .svg-экспорте
        ('<circle r="5"/>', ['xmlns="http://www.w3.org/2000/svg"', f'viewBox="0 0 {NODE_WIDTH} {NODE_HEIGHT}"', '<circle r="5"/>'], []),
        # полный <svg> без xmlns и без размера: добавляем и то и другое
        ("<svg><rect/></svg>", ['xmlns="http://www.w3.org/2000/svg"', "viewBox="], []),
        # уже самодостаточный документ не трогаем
        (CUSTOM_SVG, [CUSTOM_SVG], []),
        # width+height достаточно, чтобы вложенное изображение имело размер — viewBox не добавляем
        ('<svg width="10" height="10"><rect/></svg>', ['xmlns='], ["viewBox"]),
        # "stroke-width" — не "width": иначе размер бы посчитался заданным
        ('<svg xmlns="http://www.w3.org/2000/svg" stroke-width="2" height="5"><rect/></svg>', ["viewBox="], []),
        # xlink: без объявления пространства имён — объявляем
        ('<svg><image xlink:href="#a"/></svg>', ['xmlns:xlink="http://www.w3.org/1999/xlink"'], []),
    ],
)
def test_standalone_custom_svg_normalizes_markup(markup, expected_fragments, forbidden_fragments):
    result = _standalone_custom_svg({"mode": "custom", "svg_markup": markup})
    assert result is not None
    for fragment in expected_fragments:
        assert fragment in result
    for fragment in forbidden_fragments:
        assert fragment not in result
    ET.fromstring(result)  # результат — well-formed XML


@pytest.mark.parametrize(
    "icon",
    [
        {"mode": "generated", "svg_markup": CUSTOM_SVG},  # не custom — рисовать нечего
        {"mode": "custom", "svg_markup": ""},
        {"mode": "custom", "svg_markup": "   \n "},
        {"mode": "custom", "svg_markup": None},
        {"mode": "custom"},
        {"mode": "custom", "svg_markup": "<rect/>" * (MAX_CUSTOM_ICON_SVG_LENGTH // 7 + 1)},
    ],
)
def test_standalone_custom_svg_returns_none_for_unusable_icon(icon):
    assert _standalone_custom_svg(icon) is None


def test_export_drawio_custom_icon_rendered_as_image_tile_with_bottom_label():
    xml_text = export_drawio(_custom_graph(CUSTOM_SVG))
    vertices = _drawio_vertex_cells(xml_text)

    tiles = [v for v in vertices if "shape=image" in v.get("style", "")]
    assert len(tiles) == 1
    geometry = tiles[0].find("mxGeometry")
    assert float(geometry.get("width")) == NODE_WIDTH
    assert float(geometry.get("height")) == CUSTOM_ICON_TILE_HEIGHT

    # data URI содержит плитку, а в ней — исходную иконку, вложенную как изображение
    image_uri = re.search(r"image=(data:image/svg\+xml,[^;]+)", tiles[0].get("style", "")).group(1)
    tile_svg = unquote(image_uri.split(",", 1)[1])
    ET.fromstring(tile_svg)
    embedded = re.search(r"base64,([A-Za-z0-9+/=]+)", tile_svg).group(1)
    assert base64.b64decode(embedded).decode("utf-8") == CUSTOM_SVG

    # подпись узла у нижнего края, под плиткой
    named = [v for v in vertices if v.get("value")]
    assert len(named) == 1
    assert "verticalAlign=bottom" in named[0].get("style", "")


def test_export_drawio_custom_icon_without_markup_draws_no_tile():
    xml_text = export_drawio(_custom_graph(""))
    vertices = _drawio_vertex_cells(xml_text)
    assert [v for v in vertices if "shape=image" in v.get("style", "")] == []
    assert len([v for v in vertices if v.get("value")]) == 1  # сам узел с подписью остаётся


def test_export_vsdx_custom_icon_embedded_as_png(tmp_path):
    pytest.importorskip("vsdx")
    data = export_vsdx(_custom_graph(CUSTOM_SVG))
    out_path = tmp_path / "custom_icon.vsdx"
    out_path.write_bytes(data)

    with zipfile.ZipFile(out_path) as zf:
        media = [n for n in zf.namelist() if n.startswith("visio/media/image")]
        assert len(media) == 1
        assert zf.read(media[0]).startswith(b"\x89PNG\r\n\x1a\n")
        assert "<ForeignData" in zf.read("visio/pages/page1.xml").decode("utf-8")


def test_export_vsdx_custom_icons_dedupe_by_markup(tmp_path):
    pytest.importorskip("vsdx")
    other_svg = CUSTOM_SVG.replace("#33c9a7", "#ff0000")
    assert len(_vsdx_media(export_vsdx(_custom_graph(CUSTOM_SVG, CUSTOM_SVG, CUSTOM_SVG)), tmp_path)) == 1
    assert len(_vsdx_media(export_vsdx(_custom_graph(CUSTOM_SVG, other_svg, CUSTOM_SVG)), tmp_path)) == 2


def test_export_vsdx_survives_custom_icon_rasterization_failure(tmp_path, monkeypatch, caplog):
    """Один нерастрируемый svg_markup в каталоге не должен ронять экспорт всей диаграммы:
    иконка пропускается (с предупреждением в логе), узел остаётся с нейтральной заливкой."""
    vsdx = pytest.importorskip("vsdx")
    import resvg_py

    def _boom(**_kwargs):
        raise ValueError("render failure")

    monkeypatch.setattr(resvg_py, "svg_to_bytes", _boom)
    with caplog.at_level(logging.WARNING):
        data = export_vsdx(_custom_graph(CUSTOM_SVG, CUSTOM_SVG))

    assert _vsdx_media(data, tmp_path) == []
    assert "render failure" in caplog.text
    out_path = tmp_path / "custom.vsdx"
    vf = vsdx.VisioFile(str(out_path))
    try:
        labels = {(s.text or "").strip() for s in vf.get_page(0).child_shapes}
    finally:
        vf.close_vsdx()
    assert {"c0", "c1"} <= labels


def test_export_vsdx_survives_glyph_rasterization_failure(tmp_path, monkeypatch):
    """Как и для custom-иконки: глиф, который не удалось растрировать, не роняет экспорт — узел остаётся с заливкой
    без картинки, а повторно растрировать тот же глиф для других узлов не пытаются (None запоминается в кэше)."""
    vsdx = pytest.importorskip("vsdx")
    from app.services import diagram_export

    calls = []

    def _fail(glyph):
        calls.append(glyph)
        return None

    monkeypatch.setattr(diagram_export, "_rasterize_glyph_png", _fail)
    graph = _sample_graph()
    graph["nodes"].append({**graph["nodes"][0], "id": "dev-switch-2", "label": "sw-02", "x": 0, "y": 200})  # тот же глиф у второго узла
    data = export_vsdx(graph)

    assert _vsdx_media(data, tmp_path) == []
    assert calls == [graph["nodes"][0]["icon"]["glyph"], graph["nodes"][1]["icon"]["glyph"]]  # по одному разу на уникальный глиф
    vf = vsdx.VisioFile(str(tmp_path / "custom.vsdx"))
    try:
        labels = {(s.text or "").strip() for s in vf.get_page(0).child_shapes}
    finally:
        vf.close_vsdx()
    assert {"sw-01", "sw-02", "srv-01"} <= labels


def test_export_vsdx_skips_edges_whose_nodes_are_not_in_the_graph(tmp_path):
    """Ребро на узел, которого нет в графе, пропускается без ошибки; остальные рёбра рисуются как обычно."""
    vsdx = pytest.importorskip("vsdx")
    graph = _sample_graph()
    valid_edges = len(graph["edges"])
    graph["edges"].append({"id": "conn-dangling-target", "source_node_id": "dev-switch", "target_node_id": "нет-такого", "source_interface": None, "target_interface": None, "vlans": [{"vlan_id": 77, "name": "призрак"}]})
    graph["edges"].append({"id": "conn-dangling-source", "source_node_id": "нет-такого", "target_node_id": "dev-server", "source_interface": None, "target_interface": None, "vlans": [{"vlan_id": 78, "name": "призрак"}]})
    out_path = tmp_path / "dangling.vsdx"
    out_path.write_bytes(export_vsdx(graph))

    vf = vsdx.VisioFile(str(out_path))
    try:
        texts = [(s.text or "") for s in vf.get_page(0).child_shapes]
    finally:
        vf.close_vsdx()
    assert not any("VLAN 77" in t or "VLAN 78" in t or "призрак" in t for t in texts)
    assert len([t for t in texts if "VLAN 10" in t]) == 1 and valid_edges >= 1


def _vsdx_part(data: bytes, name: str) -> ET.Element:
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return ET.fromstring(zf.read(name))


def test_export_vsdx_page_has_no_dangling_connects_section():
    """Шаблонные «глиняные» связи <Connects> ссылаются на фигуры шаблона, которые экспорт удаляет: висячие ссылки
    в стороннем ПО дают пустой лист. Проверка прямо по XML, без LibreOffice: секции нет, значит и ссылок нет."""
    page = _vsdx_part(export_vsdx(_sample_graph()), "visio/pages/page1.xml")
    tags = {el.tag.rsplit("}", 1)[-1] for el in page.iter()}
    assert "Connects" not in tags and "Connect" not in tags
    assert len([el for el in page.iter() if el.tag.endswith("}Shape")]) >= 1  # фигуры графа на месте


def test_export_vsdx_image_relationship_ids_do_not_collide_with_the_master():
    """rId1 в page1.xml.rels занят связью со страницей-образцом (master); картинки иконок получают rId2, rId3 …
    и каждый Id встречается один раз — иначе файл не открывается."""
    rels = _vsdx_part(export_vsdx(_sample_graph()), "visio/pages/_rels/page1.xml.rels")
    by_id = [(r.get("Id"), r.get("Type", "").rsplit("/", 1)[-1]) for r in rels]
    ids = [rel_id for rel_id, _ in by_id]
    assert len(ids) == len(set(ids))
    assert ("rId1", "master") in by_id
    assert sorted(rel_id for rel_id, kind in by_id if kind == "image") == ["rId2", "rId3"]  # два разных глифа в графе


def test_custom_icon_tile_does_not_read_local_files(tmp_path):
    """Разметка иконки — пользовательский ввод, а _FORBIDDEN_SVG_PATTERN не ловит <image href>
    на локальный путь. resvg на КОРНЕВОМ уровне такой файл читает (первое утверждение фиксирует
    именно эту причину: если оно однажды упадёт — resvg изменился, пересмотреть защиту), а
    вложенное SVG-изображение — нет: плитка с файлом и с несуществующим путём идентична."""
    import resvg_py

    red_pixel_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
    )
    secret = tmp_path / "secret.png"
    secret.write_bytes(red_pixel_png)

    def markup(path: str) -> str:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">'
            f'<image xlink:href="{path}" width="10" height="10"/></svg>'
        )

    leaking = markup(str(secret))
    missing = markup(str(tmp_path / "does-not-exist.png"))

    root_level = [bytes(resvg_py.svg_to_bytes(svg_string=m, width=20, height=20)) for m in (leaking, missing)]
    assert root_level[0] != root_level[1]  # контроль: на корне resvg файл действительно читает

    tiles = [_rasterize_custom_icon_png(_standalone_custom_svg({"mode": "custom", "svg_markup": m})) for m in (leaking, missing)]
    assert tiles[0] is not None
    assert tiles[0] == tiles[1]
    assert "secret" not in _custom_icon_tile_svg(leaking)  # путь не попадает в плитку открытым текстом


def test_export_vsdx_node_shapes_have_graph_size_and_centered_pin(tmp_path):
    """Регрессия: фигуры узлов оставались размера шаблона (2.17x1.57in), а страница считалась по
    NODE_WIDTH/NODE_HEIGHT — нижний ряд и правый край большого графа обрезались. Кроме того, vsdx
    не пересчитывает LocPinX/LocPinY при смене размера — pin обязан быть в центре новой фигуры."""
    vsdx = pytest.importorskip("vsdx")
    graph = {
        "nodes": [
            {"id": "a", "type": "device", "label": "a", "x": 0, "y": 0, "icon": {"mode": "generated", "shape": "server", "color": "#4f7cff"}},
            {"id": "b", "type": "device", "label": "b", "x": 800, "y": 400, "icon": {"mode": "generated", "shape": "server", "color": "#4f7cff"}},
        ],
        "edges": [],
    }
    out_path = tmp_path / "sizes.vsdx"
    out_path.write_bytes(export_vsdx(graph))

    expected_width, expected_height = NODE_WIDTH / 100.0, NODE_HEIGHT / 100.0
    vf = vsdx.VisioFile(str(out_path))
    try:
        page = vf.get_page(0)
        nodes = {(s.text or "").strip(): s for s in page.child_shapes if (s.text or "").strip() in ("a", "b")}
        assert set(nodes) == {"a", "b"}
        for shape in nodes.values():
            assert shape.width == pytest.approx(expected_width)
            assert shape.height == pytest.approx(expected_height)
            assert float(shape.cell_value("LocPinX")) == pytest.approx(expected_width / 2)
            assert float(shape.cell_value("LocPinY")) == pytest.approx(expected_height / 2)
            # целиком внутри страницы — раньше нижний ряд уходил за нижний край
            assert shape.x - shape.width / 2 >= -1e-6
            assert shape.y - shape.height / 2 >= -1e-6
            assert shape.x + shape.width / 2 <= page.width + 1e-6
            assert shape.y + shape.height / 2 <= page.height + 1e-6
            # подпись у нижнего края фигуры (0 — верх, 1 — середина, 2 — низ)
            assert shape.cell_value("VerticalAlign") == "2"
    finally:
        vf.close_vsdx()


# --------------------------------------------------------------------------------------
# Подпись trunk-подключения: вместо списка VLAN — «trunk» (как на экране, см. edgeMidLabel).
# --------------------------------------------------------------------------------------


def _trunk_graph(is_trunk: bool) -> dict:
    graph = _sample_graph()
    graph["edges"][0]["is_trunk"] = is_trunk
    graph["edges"][0]["vlans"] = [{"id": "vlan-1", "vlan_id": 10, "name": "data"}, {"id": "vlan-2", "vlan_id": 20, "name": "voice"}]
    return graph


def test_export_svg_trunk_edge_is_labelled_trunk_instead_of_vlan_list():
    svg = export_svg(_trunk_graph(True))
    if isinstance(svg, bytes):
        svg = svg.decode("utf-8")
    assert ">trunk</text>" in svg
    assert "VLAN 10" not in svg


def test_export_svg_non_trunk_edge_keeps_vlan_list():
    svg = export_svg(_trunk_graph(False))
    if isinstance(svg, bytes):
        svg = svg.decode("utf-8")
    assert "VLAN 10, VLAN 20" in svg
    assert ">trunk</text>" not in svg


def test_export_drawio_trunk_edge_is_labelled_trunk_instead_of_vlan_list():
    xml = export_drawio(_trunk_graph(True))
    if isinstance(xml, bytes):
        xml = xml.decode("utf-8")
    assert 'value="trunk"' in xml
    assert "VLAN 10" not in xml


def test_trunk_edge_without_vlans_has_no_label():
    from app.services.diagram_export import _vlan_label

    assert _vlan_label({"is_trunk": True, "vlans": []}) == ""


# --- A-04: цвет узла из данных не должен попадать в разметку как есть ----------------------------------------------------

DIRTY_COLOR = 'x" onload="alert(1)'


def _graph_with_color(color) -> dict:
    graph = _sample_graph()
    graph["nodes"][0]["icon"]["color"] = color
    return graph


def test_export_svg_replaces_dirty_color_with_default_and_injects_nothing():
    from app.services.diagram_icons import DEFAULT_COLOR

    svg = export_svg(_graph_with_color(DIRTY_COLOR))
    assert "onload" not in svg
    assert f'fill="{DEFAULT_COLOR}"' in svg
    ET.fromstring(svg)  # разметка осталась корректным XML


def test_export_svg_keeps_valid_color():
    assert 'fill="#4f7cff"' in export_svg(_graph_with_color("#4f7cff"))


def test_export_svg_without_color_key_keeps_neutral_fallback():
    graph = _sample_graph()
    del graph["nodes"][0]["icon"]["color"]
    assert 'fill="#cccccc"' in export_svg(graph)


@pytest.mark.parametrize("color", [DIRTY_COLOR, "red", "#4f7cff;strokeColor=red", None, 5])
def test_device_fill_color_is_always_hex(color):
    from app.services.diagram_icons import DEFAULT_COLOR, is_hex_color

    resolved = _device_fill_color({"mode": "generated", "color": color})
    assert is_hex_color(resolved)
    assert resolved == DEFAULT_COLOR


def test_export_drawio_does_not_accept_foreign_style_parameters_in_color():
    xml_text = export_drawio(_graph_with_color("#4f7cff;strokeColor=red;shadow=1"))
    assert "strokeColor=red" not in xml_text
    assert "shadow=1" not in xml_text
    ET.fromstring(xml_text)


def test_export_vsdx_with_dirty_color_does_not_fail(tmp_path):
    data = export_vsdx(_graph_with_color(DIRTY_COLOR))
    assert zipfile.ZipFile(io.BytesIO(data)).testzip() is None
