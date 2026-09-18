"""
Регрессионный тест на PyInstaller-сборку (infra_registry.spec, EXE-вариант из README).

Реальная ошибка из EXE-сборки пользователя:
    FileNotFoundError: ...\\_MEI0000610c2\\vsdx\\media\\media.vsdx           (при экспорте .vsdx)
    FileNotFoundError: ...\\_MEI0000610c2\\drawpyo\\formatting_database\\edge_styles.toml  (.drawio)

PyInstaller находит Python-код обоих пакетов обычным анализом импортов (как любой другой
hiddenimport), но НЕ видит обращений к файлам ДАННЫХ (не .py), которые пакеты читают в рантайме
через путь относительно собственного __file__ (media.vsdx — services/diagram_export.py;
formatting_database/*.toml — уже при самом импорте drawpyo, см. drawpyo/diagram/base_diagram.py:
import_shape_database). Статический анализ импортов такие обращения принципиально не видит —
нужен явный collect_data_files(...) в infra_registry.spec (см. комментарий там же).

Собрать реальный Windows EXE тут негде (кросс-платформенно) — тест лишь не даёт этому месту
.spec-файла потеряться при будущем редактировании, и проверяет, что нужные файлы действительно
всё ещё существуют в установленных пакетах (т.е. что сам факт их существования не был тихой
случайностью конкретной версии).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SPEC_PATH = Path(__file__).resolve().parents[2] / "infra_registry.spec"


def _collect_data_files_args() -> set[str]:
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    args: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "collect_data_files":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    args.add(arg.value)
    return args


def test_spec_file_exists():
    assert SPEC_PATH.exists(), f"infra_registry.spec не найден по пути {SPEC_PATH}"


def test_spec_bundles_vsdx_and_drawpyo_data_files():
    args = _collect_data_files_args()
    assert "vsdx" in args, "infra_registry.spec должен собирать data-файлы пакета vsdx (media/media.vsdx)"
    assert "drawpyo" in args, "infra_registry.spec должен собирать data-файлы пакета drawpyo (formatting_database/*.toml)"


def test_vsdx_and_drawpyo_data_files_are_actually_discoverable():
    """Если пакет когда-нибудь перестанет поставлять media.vsdx/*.toml (или переименует путь
    внутри себя) — этот тест упадёт раньше, чем это всплывёт в собранном EXE у пользователя."""
    pyinstaller_hooks = pytest.importorskip("PyInstaller.utils.hooks")

    vsdx_files = pyinstaller_hooks.collect_data_files("vsdx")
    assert any(Path(src).name == "media.vsdx" for src, _dst in vsdx_files)

    drawpyo_files = pyinstaller_hooks.collect_data_files("drawpyo")
    assert any(Path(src).name == "edge_styles.toml" for src, _dst in drawpyo_files)
