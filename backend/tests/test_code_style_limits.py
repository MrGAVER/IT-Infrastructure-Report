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
