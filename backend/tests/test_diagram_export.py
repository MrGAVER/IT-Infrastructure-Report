"""
Тесты на backend/app/services/diagram_export.py — раздел 13 ТЗ диаграммы топологии сети:
".drawio/.vsdx — файл парсится обратно соответствующей библиотекой, число узлов совпадает с
ответом API; .svg — валидный XML, число узловых элементов совпадает с числом узлов графа, число
засечек порта на коммутаторе — с port_ticks дескриптора."

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_diagram_export.py -v
"""
from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from urllib.parse import quote

import pytest

from app.services.diagram_export import (
    GROUP_FILL_COLOR,
    DIAGRAM_FONT_FAMILY,
    NODE_HEIGHT,
    NODE_WIDTH,
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
                "icon": {"mode": "generated", "shape": "switch", "color": "#4f7cff", "glyph": "M1 4h3v4H1z", "port_ticks": port_ticks},
            },
            {
                "id": "dev-server",
                "type": "device",
                "label": "srv-01",
                "x": 300,
                "y": 0,
                "icon": {"mode": "generated", "shape": "server", "color": "#8a8f98", "glyph": "M2 2h10v2H2z"},
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


def test_export_svg_renders_category_glyph_path_from_descriptor():
    """Находка №3 отчёта (Фаза 2, п.2): путь глифа берётся из icon["glyph"] (единый источник —
    diagram_icons.py:SHAPE_GLYPHS), а не вычисляется самим экспортёром по имени формы."""
    graph = _sample_graph()
    svg = export_svg(graph)
    switch_glyph = graph["nodes"][0]["icon"]["glyph"]
    assert f'<path d="{switch_glyph}"' in svg


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
    assert any(quote(f'<path d="{switch_glyph}"') in v.get("style", "") for v in glyph_cells)


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
