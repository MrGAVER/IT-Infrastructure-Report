"""
Код-ревью r3, A-09: «трещотка» длины строк кода приложения.

`pyproject.toml` объявляет `line-length = 400`, но форматтер применяется только к части модулей, и в `backend/app` накопилось 7 строк
длиннее 400 символов (до 2452: списки заголовков Excel в reporting.py, справочник протоколов, импорт моделей). Теперь они обёрнуты, а этот тест
не даёт им вернуться: строка длиннее объявленного предела — ошибка. Предел читается из pyproject.toml, поэтому при его снижении (план из
отчёта: до 140 по мере миграции модулей на `ruff format`) тест сам покажет, какие строки ещё нужно обернуть.

Запуск: pytest backend/tests/test_code_style_limits.py -v
"""
from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "backend" / "app"


def _line_length_limit() -> int:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["line-length"]


def test_no_application_line_is_longer_than_the_declared_line_length():
    limit = _line_length_limit()
    too_long = [
        f"{path.relative_to(ROOT)}:{number} ({len(line)} симв.)"
        for path in sorted(APP_DIR.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if len(line) > limit
    ]
    assert too_long == [], f"строки длиннее {limit} символов (оберните оператор `ruff format`-ом): {too_long}"


def test_the_limit_is_not_silently_raised():
    # Объявленный предел только снижается (план — 140). Поднять его, чтобы тест позеленел, нельзя: сначала нужно осознанно поменять число здесь.
    assert _line_length_limit() <= 400


# --- Состав шага CI «ruff format --check» --------------------------------------------------------------------------------------------------
# Модули, переведённые на форматтер в A-09: список в CI только растёт, исключить отсюда модуль можно лишь осознанно (меняя этот тест).
FORMATTED_MODULES = {
    "backend/app/api/diagrams.py",
    "backend/app/api/reports.py",
    "backend/app/constants.py",
    "backend/app/services/audit_export.py",
    "backend/app/services/report_cleanup.py",
    "backend/app/services/exe_settings.py",
    "backend/app/services/diagram_icons.py",
    "backend/app/services/auth/_common.py",
    "backend/app/services/auth/guards.py",
    "backend/app/services/auth/login.py",
    "backend/app/services/crud/__init__.py",
    "backend/app/services/diagram_export/__init__.py",
    "backend/app/services/diagram_export/_common.py",
    "backend/app/services/diagram_export/_icons.py",
    "backend/app/services/diagram_export/drawio.py",
    "backend/app/services/diagram_export/svg.py",
    "backend/app/services/diagram_export/vsdx.py",
    "backend/app/services/body_limit.py",
    "backend/app/services/request_errors.py",
    "backend/app/api/schema_base.py",
}


def _ci_format_check_paths() -> list[str]:
    import yaml

    steps = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))["jobs"]["test"]["steps"]
    command = next(step["run"] for step in steps if step.get("run", "").lstrip().startswith("ruff format --check"))
    return command.split()[3:]  # ruff format --check <пути…>


def _expand(patterns: list[str]) -> set[str]:
    return {str(path.relative_to(ROOT)) for pattern in patterns for path in ROOT.glob(pattern)}


def test_ci_format_check_covers_the_modules_formatted_in_this_review():
    covered = _expand(_ci_format_check_paths())
    assert FORMATTED_MODULES <= covered, f"в шаге CI нет модулей: {sorted(FORMATTED_MODULES - covered)}"


def test_every_path_in_the_ci_format_check_exists():
    # Опечатка в списке или glob без совпадений: ruff упал бы в CI, а здесь это видно сразу при обычном pytest.
    for pattern in _ci_format_check_paths():
        assert list(ROOT.glob(pattern)), f"в шаге CI путь без совпадений: {pattern}"


def test_every_module_in_the_ci_format_check_is_really_formatted():
    import subprocess
    import sys

    result = subprocess.run([sys.executable, "-m", "ruff", "format", "--check", *sorted(_expand(_ci_format_check_paths()))], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
