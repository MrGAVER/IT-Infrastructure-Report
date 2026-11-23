"""
Трещотки стиля кода backend: длина строк, форматтер для всех файлов, запрет ссылок на номера замечаний ревью.

1. Длина строк. Предел читается из `pyproject.toml` (`[tool.ruff] line-length`) и снижен ступенями до 140: 400 → 300 → 240 → 200 → 160
   → 140. Каждая ступень — отдельный механический коммит: `ruff format backend` плюс проверка равенства AST до и после. Тест проверяет
   все .py-файлы backend, кроме исторических миграций (`alembic/versions`): форматтер переносит операторы, но не переносит одиночные
   строковые литералы, комментарии и докстринги — их режут вручную (строки — неявной конкатенацией), и тест не даёт им вернуться.
2. Форматтер. `ruff format` применяется ко ВСЕМУ backend, кроме исторических миграций (шаблон в `[tool.ruff.format] exclude`,
   pyproject.toml); CI проверяет одной командой `ruff format --check backend`. Список файлов-исключений, который сокращали пачками
   (было 271 файл), теперь пуст: новый модуль форматируется автоматически, а добавить файл в исключения нельзя — тест этого не
   пропустит.
3. Ссылки на номера замечаний ревью и на «память проекта» в backend/app запрещены: в комментарии пишут, почему так, а не какое
   замечание это потребовало.

Запуск: pytest backend/tests/test_code_style_limits.py -v
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "backend" / "app"


def _line_length_limit() -> int:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["line-length"]


HISTORICAL_MIGRATIONS = ROOT / "backend" / "alembic" / "versions"


def _backend_python_files() -> list[Path]:
    return sorted(path for path in (ROOT / "backend").rglob("*.py") if HISTORICAL_MIGRATIONS not in path.parents)


def test_no_backend_line_is_longer_than_the_declared_line_length():
    limit = _line_length_limit()
    too_long = [
        f"{path.relative_to(ROOT)}:{number} ({len(line)} симв.)"
        for path in _backend_python_files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if len(line) > limit
    ]
    assert too_long == [], (
        f"строки длиннее {limit} символов (код оберните `ruff format`-ом, строку-литерал разрежьте на части, "
        f"комментарий и докстринг перенесите): {too_long}"
    )


def test_the_limit_is_not_silently_raised():
    # Объявленный предел только снижается (план — 140). Поднять его, чтобы тест позеленел, нельзя: сначала нужно осознанно
    # поменять число здесь.
    assert _line_length_limit() <= 140


# --- Исключения из `ruff format` ----------------------------------------------------------------------------------------------------------
# Единственное исключение — шаблон исторических миграций (их не переписывают). Файлы-исключения не допускаются: отформатируйте
# файл, а не исключайте его.
CI_FORMAT_COMMAND = "ruff format --check backend"
CI_FILE = ROOT / ".github" / "workflows" / "ci.yml"


def _format_exclusions() -> list[str]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["format"]["exclude"]


def _explicit_exclusions() -> list[str]:
    """Записи-файлы; записи-шаблоны (`*`, `?`, `[`) — осознанные группы вроде исторических миграций — не в счёт."""
    return [entry for entry in _format_exclusions() if not any(char in entry for char in "*?[")]


def _ruff_format_check(*paths: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", *paths], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
    )


def test_no_file_is_excluded_from_the_formatter():
    """Список исключений был сокращён до нуля (271 → 0 пачками без изменения AST); новый файл в нём — ошибка: форматируется он сам."""
    assert _explicit_exclusions() == [], "отформатируйте файл (`ruff format <файл>`), а не исключайте его из [tool.ruff.format] exclude"


def test_the_format_exclusion_list_has_no_duplicates_and_every_entry_exists():
    entries = _format_exclusions()
    assert len(entries) == len(set(entries)), "повторы в [tool.ruff.format] exclude"
    for entry in entries:
        assert list(ROOT.glob(entry)), f"в исключениях путь без совпадений (файл удалён или переименован — уберите запись): {entry}"


def test_everything_outside_the_exclusions_is_formatted():
    """Тот же вызов, что в CI: новый модуль или тест, не прошедший форматтер, ловится здесь, а не после пуша."""
    result = _ruff_format_check("backend")
    assert result.returncode == 0, result.stdout + result.stderr


def test_ci_checks_the_format_of_the_whole_backend_in_one_step():
    """Перечень модулей жил в трёх местах (CI, константа теста, комментарий pyproject.toml); теперь в CI одна команда без списка файлов."""
    workflow = yaml.safe_load(CI_FILE.read_text(encoding="utf-8"))
    commands = [
        str(step["run"]).strip()
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if "ruff format" in str(step.get("run", ""))
    ]
    assert commands == [CI_FORMAT_COMMAND]


# --- Ссылки на номера замечаний ревью и на «память проекта»
# ---------------------------------------------------------------------------------
# Номера замечаний (R1-07, A-05, ИА-01…) теряют смысл вместе с самим отчётом, а «память проекта» — артефакт вне репозитория,
# читатель не может его открыть. В комментарии пишется ПОЧЕМУ так (инвариант), история — в CHANGELOG.md и git. Исключений нет:
# файлы, которые чистили по волнам
# (сначала вне владения первого исполнителя, затем — после слияния его PR — остальные), закончились.
REVIEW_REFERENCE = re.compile(
    r"память проекта|\bR\d?-\d+\b|\b(?:ИА|ИБ|BE|FE|UI|F)-\d+\b|\b[AB]-\d{2}\b|\b[СНП]-\d+\b|код-ревью|\bревью\b", re.IGNORECASE
)


def _review_references() -> list[str]:
    return [
        f"{path.relative_to(APP_DIR).as_posix()}:{number}"
        for path in sorted(APP_DIR.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if REVIEW_REFERENCE.search(line)
    ]


def test_comments_do_not_refer_to_review_numbers_or_to_the_project_memory():
    assert _review_references() == [], "замените номер замечания/«память проекта» описанием инварианта (почему так)"
