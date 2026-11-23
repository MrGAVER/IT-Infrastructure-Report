"""Трещотка: миграции Alembic не ссылаются на номера замечаний код-ревью (F-09).

Миграция живёт в репозитории дольше любого отчёта: «закрывает замечание N» через год ничего не скажет, а сам отчёт к тому времени
может не лежать рядом. Причина изменения описывается словами — что было не так и что теперь. Тот же запрет, что действует для
`backend/app` (см. `test_code_style_limits.REVIEW_REFERENCE`), распространяется на `backend/alembic`.

Запуск: pytest backend/tests/test_review_p3_migration_docstrings.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_code_style_limits import REVIEW_REFERENCE

ALEMBIC_DIR = Path(__file__).resolve().parent.parent / "alembic"


def _migration_files() -> list[Path]:
    return sorted(ALEMBIC_DIR.rglob("*.py"))


def test_the_scan_sees_the_migrations_so_the_ratchet_is_not_vacuous():
    assert len(list((ALEMBIC_DIR / "versions").glob("*.py"))) > 10


@pytest.mark.parametrize(
    "text",
    ["закрывает замечание F-09", "по итогам код-ревью", "см. R2-3", "замечание ИБ-4", "память проекта"],
)
def test_the_pattern_recognises_references_to_review_findings(text):
    assert REVIEW_REFERENCE.search(text), text


def test_migrations_do_not_refer_to_code_review_findings():
    offenders = [
        f"{path.relative_to(ALEMBIC_DIR.parent).as_posix()}:{number}: {line.strip()}"
        for path in _migration_files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if REVIEW_REFERENCE.search(line)
    ]

    assert not offenders, "Опишите причину словами, без номеров замечаний:\n" + "\n".join(offenders)
