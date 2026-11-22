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
from pyinstaller_spec_eval import SPEC_PATH, evaluate_spec


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


# ----- hiddenimports: модули пакета app, которых PyInstaller сам не увидит ----------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_DIR = BACKEND_DIR / "alembic"
# env.py тоже грузится как ДАННЫЕ и тоже импортирует модули app (`app.alembic_filters`, R1-02): страж, смотревший только versions/, их не видел.
ALEMBIC_SCRIPTS = [ALEMBIC_DIR / "env.py", *sorted((ALEMBIC_DIR / "versions").glob("*.py"))]


def _is_app_module(dotted: str) -> bool:
    """Модуль пакета app (файл .py или пакет с __init__.py), а не атрибут модуля (`from app.models import Base` — Base не модуль)."""
    path = BACKEND_DIR.joinpath(*dotted.split("."))
    return dotted.split(".")[0] == "app" and (path.with_suffix(".py").is_file() or (path / "__init__.py").is_file())


def _app_modules_on_disk() -> set[str]:
    modules: set[str] = set()
    for path in (BACKEND_DIR / "app").rglob("*.py"):
        parts = path.relative_to(BACKEND_DIR).with_suffix("").parts
        modules.add(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    return modules


def _app_modules_imported_by_alembic_scripts() -> dict[str, set[str]]:
    """{модуль app.*: {файлы env.py / миграций}} — импорты и на верхнем уровне, и внутри функций (ленивые, как в миграциях с шаблонами отчётов)."""
    found: dict[str, set[str]] = {}
    for path in ALEMBIC_SCRIPTS:
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


def test_every_app_module_imported_by_alembic_scripts_is_in_hiddenimports(monkeypatch):
    """Регрессия: EXE падал при запуске с `ModuleNotFoundError: No module named 'app.alembic_filters'`.

    alembic/env.py и alembic/versions/*.py грузятся как ДАННЫЕ уже после старта (alembic/util/pyfiles.py: load_python_file), поэтому
    PyInstaller не видит их импортов. Проверяется итоговый `hiddenimports`, который спецификация передаёт в Analysis (а не текст .spec):
    пропущенный модуль не ломает ни тесты, ни саму сборку — EXE падает только у пользователя, при обновлении базы.
    """
    hiddenimports = set(evaluate_spec(monkeypatch)["hiddenimports"])
    missing = {module: sorted(files) for module, files in _app_modules_imported_by_alembic_scripts().items() if module not in hiddenimports}
    assert not missing, (
        f"модули app импортируются из alembic/env.py или миграций (PyInstaller эти файлы не анализирует) и должны быть в hiddenimports: {missing}"
    )


def test_hiddenimports_cover_every_app_module_on_disk(monkeypatch):
    """В EXE должен попасть весь пакет app, а не только то, что достижимо обычным импортом от launcher.py.

    Список строит сама спецификация обходом каталога backend/app: `collect_submodules('app')` при сборке из корня репозитория возвращал
    пустой список (в sys.path нет backend/) — модули приходилось перечислять вручную, и новый модуль выпадал из сборки молча.
    """
    missing = sorted(_app_modules_on_disk() - set(evaluate_spec(monkeypatch)["hiddenimports"]))
    assert not missing, f"в hiddenimports нет модулей пакета app (их не будет в EXE): {missing}"


def test_hiddenimports_do_not_list_nonexistent_modules(monkeypatch):
    """Обратная сторона: после переименования модуля устаревшая строка в списке не должна оставаться."""
    stale = sorted(module for module in evaluate_spec(monkeypatch)["hiddenimports"] if not _is_app_module(module))
    assert not stale, f"в hiddenimports перечислены несуществующие модули: {stale}"


def test_hiddenimports_guard_sees_env_py_and_the_lazy_migration_imports():
    """Страж не должен тихо ослепнуть: импорт из env.py и известные ленивые импорты шаблонов отчётов (внутри функций миграций) он обязан находить."""
    found = _app_modules_imported_by_alembic_scripts()
    assert {"app.alembic_filters", "app.services.report_seed_templates", "app.services.report_seed_word_template"} <= set(found)
    assert "env.py" in found["app.alembic_filters"]
