"""
Регрессионный тест на PyInstaller-сборку (infra_registry.spec, EXE-вариант из README).

Реальная ошибка из EXE-сборки пользователя:
    FileNotFoundError: ...\\_MEI0000610c2\\vsdx\\media\\media.vsdx           (при экспорте .vsdx)
    FileNotFoundError: ...\\_MEI0000610c2\\drawpyo\\formatting_database\\edge_styles.toml  (.drawio)

PyInstaller находит Python-код обоих пакетов обычным анализом импортов (как любой другой
hiddenimport), но НЕ видит обращений к файлам ДАННЫХ (не .py), которые пакеты читают в рантайме
через путь относительно собственного __file__ (media.vsdx — services/diagram_export/vsdx.py;
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


# ----- hiddenimports: модули, на которые ссылаются только миграции ---------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parents[1]
VERSIONS_DIR = BACKEND_DIR / "alembic" / "versions"


def _is_app_module(dotted: str) -> bool:
    """Модуль пакета app (файл .py или пакет с __init__.py), а не атрибут модуля (`from app.models import Base` — Base не модуль)."""
    path = BACKEND_DIR.joinpath(*dotted.split("."))
    return dotted.split(".")[0] == "app" and (path.with_suffix(".py").is_file() or (path / "__init__.py").is_file())


def _app_modules_imported_by_migrations() -> dict[str, set[str]]:
    """{модуль app.*: {файлы миграций}} — импорты и на верхнем уровне, и внутри функций (ленивые, как в миграциях с шаблонами отчётов)."""
    found: dict[str, set[str]] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                candidates = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
            elif isinstance(node, ast.Import):
                candidates = [alias.name for alias in node.names]
            else:
                continue
            for dotted in candidates:
                if _is_app_module(dotted):
                    found.setdefault(dotted, set()).add(path.name)
    return found


def _explicit_hiddenimports() -> set[str]:
    """Строки-литералы из списка `hiddenimports = collect_submodules('app') + [ ... ]` в .spec."""
    for node in ast.walk(ast.parse(SPEC_PATH.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "hiddenimports" for t in node.targets):
            return {n.value for n in ast.walk(node.value) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value != "app"}
    raise AssertionError("в infra_registry.spec нет присваивания hiddenimports")


def test_every_app_module_imported_by_a_migration_is_listed_in_hiddenimports():
    """alembic/versions/*.py грузятся как ДАННЫЕ уже после старта (alembic/util/pyfiles.py: load_python_file), поэтому PyInstaller не видит
    их импортов. Пропущенный модуль не ломает ни тесты, ни сборку: EXE падает с ModuleNotFoundError только при обновлении базы
    у пользователя. README требует явной строки в hiddenimports на каждую такую миграцию — тест держит это правило."""
    missing = {module: sorted(files) for module, files in _app_modules_imported_by_migrations().items() if module not in _explicit_hiddenimports()}
    assert not missing, f"добавьте в hiddenimports в infra_registry.spec (импортируются только из миграций): {missing}"


def test_explicit_hiddenimports_point_at_existing_modules():
    """Обратная сторона: после переименования модуля устаревшая строка в списке молча остаётся (collect_submodules её не ищет)."""
    stale = sorted(module for module in _explicit_hiddenimports() if not _is_app_module(module))
    assert not stale, f"в hiddenimports перечислены несуществующие модули: {stale}"


def test_hiddenimports_guard_sees_the_known_lazy_imports():
    """Страж не должен тихо ослепнуть: известные ленивые импорты шаблонов отчётов (внутри функций миграций) он обязан находить."""
    found = _app_modules_imported_by_migrations()
    assert {"app.services.report_seed_templates", "app.services.report_seed_word_template"} <= set(found)
