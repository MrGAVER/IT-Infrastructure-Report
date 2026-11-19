"""
Код-ревью r3, A-09 и ИА-05: «трещотки» стиля кода backend.

1. Длина строк. `pyproject.toml` объявляет `line-length = 400`; в `backend/app` накопилось 7 строк длиннее 400 символов (до 2452: списки заголовков
   Excel в reporting.py, справочник протоколов, импорт моделей), теперь они обёрнуты, а тест не даёт им вернуться. Предел читается из pyproject.toml,
   поэтому при его снижении (план: до 140) тест сам покажет, какие строки ещё нужно обернуть.
2. Форматтер (ИА-05). `ruff format` применяется ко ВСЕМУ backend, кроме списка исключений в `[tool.ruff.format] exclude` (pyproject.toml) — единственного
   места, где он хранится; CI проверяет одной командой `ruff format --check backend`. Новый модуль форматируется автоматически, а список исключений
   только сокращается: тест не даёт ему расти, не терпит записей, которые уже не нужны, и следит, чтобы шаг CI остался одним.

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


# --- Исключения из `ruff format` (ИА-05) ---------------------------------------------------------------------------------------------------
# Число модулей-исключений на момент ИА-05. Менять его можно только вниз: отформатировали модуль — удалили запись из pyproject.toml и уменьшили число.
MAX_EXCLUDED_FILES = 271
CI_FORMAT_COMMAND = "ruff format --check backend"
CI_FILE = ROOT / ".github" / "workflows" / "ci.yml"


def _format_exclusions() -> list[str]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["format"]["exclude"]


def _explicit_exclusions() -> list[str]:
    """Записи-файлы; записи-шаблоны (`*`, `?`, `[`) — осознанные группы вроде исторических миграций — в счёт и в проверку устаревания не входят."""
    return [entry for entry in _format_exclusions() if not any(char in entry for char in "*?[")]


def _ruff_format_check(*paths: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "ruff", "format", "--check", *paths], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")


def test_the_format_exclusion_list_is_exactly_the_frozen_size():
    """Растёт — ошибка (новые файлы форматируются, а не вносятся в исключения); сократился — число выше нужно уменьшить, чтобы запас не копился."""
    size = len(_explicit_exclusions())
    assert size <= MAX_EXCLUDED_FILES, f"список исключений из ruff format вырос до {size} (было {MAX_EXCLUDED_FILES}): отформатируйте новый файл, а не исключайте его"
    assert size == MAX_EXCLUDED_FILES, f"список сократился до {size} — уменьшите MAX_EXCLUDED_FILES в этом тесте до {size}"


def test_the_format_exclusion_list_has_no_duplicates_and_every_entry_exists():
    entries = _format_exclusions()
    assert len(entries) == len(set(entries)), "повторы в [tool.ruff.format] exclude"
    for entry in entries:
        assert list(ROOT.glob(entry)), f"в исключениях путь без совпадений (файл удалён или переименован — уберите запись): {entry}"


def test_every_excluded_file_is_still_unformatted():
    """Файл, который форматтер уже не изменил бы, из исключений нужно убрать: так список сам сжимается и не хранит лишнего."""
    explicit = _explicit_exclusions()
    result = _ruff_format_check(*explicit)  # явно переданные пути проверяются, несмотря на exclude
    assert result.returncode == 1, result.stdout + result.stderr
    already_formatted = [entry for entry in explicit if entry not in result.stdout]
    assert already_formatted == [], f"эти файлы уже отформатированы — удалите их из [tool.ruff.format] exclude и уменьшите MAX_EXCLUDED_FILES: {already_formatted}"


def test_everything_outside_the_exclusions_is_formatted():
    """Тот же вызов, что в CI: новый модуль или тест, не прошедший форматтер, ловится здесь, а не после пуша."""
    result = _ruff_format_check("backend")
    assert result.returncode == 0, result.stdout + result.stderr


def test_ci_checks_the_format_of_the_whole_backend_in_one_step():
    """Перечень модулей жил в трёх местах (CI, константа теста, комментарий pyproject.toml); теперь в CI одна команда без списка файлов."""
    workflow = yaml.safe_load(CI_FILE.read_text(encoding="utf-8"))
    commands = [str(step["run"]).strip() for job in workflow["jobs"].values() for step in job.get("steps", []) if "ruff format" in str(step.get("run", ""))]
    assert commands == [CI_FORMAT_COMMAND]


# --- Ссылки на номера замечаний ревью и на «память проекта» ---------------------------------------------------------------------------------
# Номера замечаний (R1-07, A-05, ИА-01…) теряют смысл вместе с самим отчётом, а «память проекта» — артефакт вне репозитория, читатель не может его
# открыть. В комментарии пишется ПОЧЕМУ так (инвариант), история — в CHANGELOG.md и git. Первая волна почистила файлы вне владения первого исполнителя
# (API и безопасность); файлы из списка ниже правит вторая волна после слияния его PR (иначе правки комментариев конфликтовали бы с правками логики).
# Список только сокращается: очистили файл — удалите его отсюда, тест не терпит устаревших записей.
REVIEW_REFERENCE = re.compile(
    r"память проекта|\bR\d?-\d+\b|\b(?:ИА|ИБ|BE|FE|UI|F)-\d+\b|\b[AB]-\d{2}\b|\b[СНП]-\d+\b|код-ревью|\bревью\b", re.IGNORECASE
)
REVIEW_REFERENCES_UNTIL_WAVE_2 = (
    "api/device_stacks.py",
    "api/diagram_schemas.py",
    "api/diagrams.py",
    "api/port_config_schemas.py",
    "api/report_builder.py",
    "api/report_schemas.py",
    "api/reports.py",
    "api/resource_schemas.py",
    "api/schema_base.py",
    "api/vlan.py",
    "main.py",
    "services/auth/__init__.py",
    "services/auth/_common.py",
    "services/auth/gate.py",
    "services/auth/guards.py",
    "services/auth/proxy_headers.py",
    "services/auth/settings.py",
    "services/auth/users.py",
    "services/body_limit.py",
    "services/crud/__init__.py",
    "services/crud/deletion.py",
    "services/crud/interfaces.py",
    "services/crud/payload.py",
    "services/crud/validators.py",
    "services/diagram_icons.py",
    "services/login_throttle.py",
)


def _files_with_review_references() -> set[str]:
    return {
        path.relative_to(APP_DIR).as_posix()
        for path in APP_DIR.rglob("*.py")
        if any(REVIEW_REFERENCE.search(line) for line in path.read_text(encoding="utf-8").splitlines())
    }


def test_comments_do_not_refer_to_review_numbers_or_to_the_project_memory():
    unexpected = sorted(_files_with_review_references() - set(REVIEW_REFERENCES_UNTIL_WAVE_2))
    assert unexpected == [], f"замените номер замечания/«память проекта» описанием инварианта (почему так): {unexpected}"


def test_the_review_reference_allowlist_has_no_stale_entries():
    stale = sorted(set(REVIEW_REFERENCES_UNTIL_WAVE_2) - _files_with_review_references())
    assert stale == [], f"файлы уже чисты — удалите их из REVIEW_REFERENCES_UNTIL_WAVE_2: {stale}"
    assert len(REVIEW_REFERENCES_UNTIL_WAVE_2) == len(set(REVIEW_REFERENCES_UNTIL_WAVE_2))
