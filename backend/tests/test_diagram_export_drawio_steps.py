"""R1-08 (п. 2) код-ревью: `export_drawio` разбита на шаги, исключение ruff для `diagram_export.py` снято.

Функция в 112 строк (13 ветвей, 63 оператора) держала файл в списке исключений ruff (`PLR0912`, `PLR0915`), который по
`pyproject.toml` «только сокращается». Теперь она — десяток строк поверх шагов `_drawio_add_node` (объект узла и иконка поверх
него), `_drawio_add_edge` и
их помощников. Вывод не менялся: сверен побайтово (с нормализацией случайных id) на графах со всеми видами узлов и рёбер до и
после разбиения; сам формат
покрывают `test_diagram_export.py` (узлы, засечки, глиф, custom-иконки, шрифты, привязка рёбер, пунктир). Здесь — шаги по
отдельности и страж долга.

Запуск: pytest backend/tests/test_diagram_export_drawio_steps.py -v
"""

from __future__ import annotations

import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from test_diagram_export import _sample_graph

from app.services.diagram_export import _drawio_edge_anchors, export_drawio

ROOT = Path(__file__).resolve().parents[2]


def _nodes_by_id(graph: dict) -> dict:
    return {node["id"]: node for node in graph["nodes"]}


def test_edge_anchors_point_to_the_port_tick_of_each_end():
    graph = _sample_graph(port_ticks=24)  # у коммутатора 24 засечки, у сервера — по образцу из теста
    edge = graph["edges"][0]
    nodes = _nodes_by_id(graph)
    anchors = _drawio_edge_anchors(edge, nodes)
    assert anchors["exitX"] == (0 + 1) / (24 + 1) and anchors["exitY"] == 1.0  # порт с индексом 0 у источника
    assert "entryX" not in anchors  # у приёмника port_index не резолвится — привязки нет, draw.io выберет точку сам


def test_edge_anchors_are_empty_without_interface_references():
    graph = _sample_graph()
    edge = {**graph["edges"][0], "source_interface": None, "target_interface": None}
    assert _drawio_edge_anchors(edge, _nodes_by_id(graph)) == {}


def test_export_skips_edges_whose_endpoint_is_missing_and_still_draws_the_rest():
    graph = _sample_graph()
    graph["edges"].append({**graph["edges"][0], "id": "ghost", "target_node_id": "no-such-node"})
    root = ET.fromstring(export_drawio(graph))
    edges = [cell for cell in root.iter("mxCell") if cell.get("edge") == "1"]
    assert len(edges) == 1


def test_export_draws_every_node_once_in_input_order():
    graph = _sample_graph()
    root = ET.fromstring(export_drawio(graph))
    labels = [cell.get("value") for cell in root.iter("mxCell") if cell.get("vertex") == "1" and cell.get("value")]
    assert labels == [node["label"] for node in graph["nodes"]]


# --- Долг по сложности только сокращается ------------------------------------------------------------------------------------
KNOWN_DEBT = {"backend/app/services/crud/payload.py", "backend/app/services/report_engine.py"}


def test_ruff_complexity_debt_list_only_shrinks():
    """Исключения ruff для файлов приложения — только перечисленный остаток (PLR0911). `diagram_export.py` из списка снят: вернуть
    его нельзя, разбирать нужно функцию на шаги, а не расширять исключения (см. комментарий в pyproject.toml)."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ignores = config["tool"]["ruff"]["lint"]["per-file-ignores"]
    app_files = {path for path in ignores if path.startswith("backend/app/")}
    assert app_files <= KNOWN_DEBT, f"в исключения ruff добавлены файлы приложения: {sorted(app_files - KNOWN_DEBT)}"
    assert "backend/app/services/diagram_export.py" not in ignores
