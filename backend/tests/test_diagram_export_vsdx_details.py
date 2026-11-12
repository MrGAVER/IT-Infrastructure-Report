"""Экспорт .vsdx: быстрое копирование шаблонных фигур (A-06).

Библиотека vsdx при каждом копировании фигуры обходила всю страницу — n копий стоили n² обходов. _ShapeTemplate копирует
без повторного обхода; здесь проверяется, что результат тот же, что у Shape.copy(), и что обходов не больше константы.
Запуск: pytest backend/tests/test_diagram_export_vsdx_details.py -v
"""
from __future__ import annotations

import copy
import os
import shutil
import xml.etree.ElementTree as ET

import pytest

from app.services.diagram_export import export_vsdx
from test_diagram_export import _sample_graph

vsdx = pytest.importorskip("vsdx")


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
    edges = [
        {"id": f"e{i}", "source_node_id": f"n{i}", "target_node_id": f"n{i + 1}", "source_interface": {"port_index": 2}, "target_interface": None, "is_active": True, "vlans": []}
        for i in range(39)
    ]
    export_vsdx({"nodes": nodes, "edges": edges})
    assert len(calls) <= 2  # шаблон узла и шаблон коннектора; при 40 узлах, 240 засечках и 39 рёбрах
