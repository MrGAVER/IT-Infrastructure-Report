"""
Код-ревью r3, A-07: `services/diagram_export` — пакет из трёх экспортёров и общих модулей (раньше один файл на 1020 строк).

Перенос механический: доказан сравнением AST всех 68 верхнеуровневых определений до и после (совпали), существующие тесты диаграмм
проходят, а вручную пришлось перенацелить лишь два места, привязанных к внутреннему устройству (см. test_diagram_export_safe_xml.py и
подмену растеризатора в test_diagram_export.py). Здесь — стражи структуры, чтобы пакет не вернулся к монолиту и не оброс циклами.

Запуск: pytest backend/tests/test_diagram_export_package.py -v
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.api import diagrams as diagrams_module
from app.services import diagram_export
from app.services import vsdx_process
from app.services.diagram_export import drawio, svg, vsdx

PACKAGE_DIR = Path(diagram_export.__file__).parent
MODULES = ["_common", "_icons", "svg", "drawio", "vsdx"]
# Разрешённые внутренние зависимости: только вниз, экспортёры друг о друге не знают.
ALLOWED_SIBLING_IMPORTS = {
    "_common": set(),
    "_icons": {"_common"},
    "svg": {"_common", "_icons"},
    "drawio": {"_common", "_icons"},
    "vsdx": {"_common", "_icons"},
}
MAX_MODULE_LINES = 600  # самый большой модуль (vsdx) — около 470; предел не даёт пакету снова собраться в один файл


def _sibling_imports(module: str) -> set[str]:
    tree = ast.parse((PACKAGE_DIR / f"{module}.py").read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            found.add(node.module)
    return found


def test_it_is_a_package_and_the_old_single_file_is_gone():
    assert (PACKAGE_DIR / "__init__.py").is_file()
    assert not (PACKAGE_DIR.parent / "diagram_export.py").exists(), "рядом с пакетом не должно лежать старого одноимённого файла"
    assert {path.stem for path in PACKAGE_DIR.glob("*.py")} == {"__init__", *MODULES}


def test_public_exporters_are_the_functions_of_their_modules():
    assert diagram_export.export_svg is svg.export_svg
    assert diagram_export.export_drawio is drawio.export_drawio
    assert diagram_export.export_vsdx is vsdx.export_vsdx


def test_the_export_registry_serves_what_the_package_functions_produce():
    """Реестр форматов (api/diagrams.py) подключён к функциям пакета: svg и drawio обёрнуты в encode (функции возвращают str), vsdx идёт
    через рендер в дочернем процессе (services/vsdx_process.py), который вызывает export_vsdx."""
    graph = {"nodes": [], "edges": []}
    registry = diagrams_module.EXPORT_FORMATS
    assert registry["svg"][1](graph) == diagram_export.export_svg(graph).encode("utf-8")
    drawio_bytes = registry["drawio"][1](graph)  # побайтно не сравнить: drawpyo ставит в <mxfile> отметку времени
    assert isinstance(drawio_bytes, bytes) and drawio_bytes.startswith(b"<mxfile")
    assert registry["vsdx"][1] is vsdx_process.export_vsdx_isolated


def test_dunder_all_lists_only_importable_names_and_all_three_exporters():
    assert {"export_svg", "export_drawio", "export_vsdx"} <= set(diagram_export.__all__)
    for name in diagram_export.__all__:
        assert hasattr(diagram_export, name), name
    assert len(diagram_export.__all__) == len(set(diagram_export.__all__)) and diagram_export.__all__ == sorted(diagram_export.__all__, key=lambda n: (n[0].islower(), n))


@pytest.mark.parametrize("module", MODULES)
def test_layering_has_only_downward_dependencies(module):
    assert _sibling_imports(module) <= ALLOWED_SIBLING_IMPORTS[module], f"{module} импортирует лишнее: {_sibling_imports(module) - ALLOWED_SIBLING_IMPORTS[module]}"


@pytest.mark.parametrize("module", MODULES)
def test_no_module_grows_back_into_a_monolith(module):
    lines = (PACKAGE_DIR / f"{module}.py").read_text(encoding="utf-8").count("\n")
    assert lines <= MAX_MODULE_LINES, f"{module}.py — {lines} строк (предел {MAX_MODULE_LINES}): выделите часть в отдельный модуль"


def test_a_stale_monkeypatch_on_the_facade_fails_loudly_instead_of_silently_doing_nothing(monkeypatch):
    """`_rasterize_glyph_png` намеренно не реэкспортирован: подмена на фасаде не повлияла бы на vsdx.py, и тест «проходил бы» впустую."""
    with pytest.raises(AttributeError):
        monkeypatch.setattr(diagram_export, "_rasterize_glyph_png", lambda glyph: None)
    monkeypatch.setattr(vsdx, "_rasterize_glyph_png", lambda glyph: None)  # а в модуле, который его вызывает, подмена возможна


def test_every_private_name_the_facade_reexports_exists_in_a_submodule():
    # Страж реэкспорта для существующих тестов: переименование функции в подмодуле должно ломаться здесь, а не в десятке тестов.
    for name in (
        "_device_fill_color",
        "_vlan_label",
        "_custom_icon_tile_svg",
        "_rasterize_custom_icon_png",
        "_standalone_custom_svg",
        "_drawio_edge_anchors",
        "_embed_vsdx_category_icons",
        "_finalize_vsdx_package",
    ):
        assert callable(getattr(diagram_export, name)), name
