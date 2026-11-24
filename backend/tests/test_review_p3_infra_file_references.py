"""Трещотка: файлы запуска, CI, Docker и установщика не ссылаются на номера замечаний код-ревью (F-09, часть исполнителя 1).

Для `backend/app` и миграций такой запрет уже есть (`test_code_style_limits`, `test_review_p3_migration_docstrings`). Здесь он
распространён на остальное, что живёт в репозитории дольше любого отчёта: `infra_registry.spec`, `docker-compose.yml`, Docker-файлы,
workflow и `dependabot.yml`, каталог `installer`. Причина пишется словами: что было не так и что теперь.

Запуск: pytest backend/tests/test_review_p3_infra_file_references.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_code_style_limits import REVIEW_REFERENCE

ROOT = Path(__file__).resolve().parents[2]
SINGLE_FILES = ("infra_registry.spec", "docker-compose.yml", "backend/Dockerfile", "backend/docker-entrypoint.sh", ".env.example")
TREES = (".github", "installer")


def _scanned_files() -> list[Path]:
    files = [ROOT / name for name in SINGLE_FILES]
    for tree in TREES:
        files += sorted(path for path in (ROOT / tree).rglob("*") if path.is_file())
    return files


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:  # двоичный файл установщика (значок, ресурс) — ссылок на замечания в нём нет
        return None


def test_the_scan_sees_the_files_so_the_ratchet_is_not_vacuous():
    files = _scanned_files()
    missing = [path.relative_to(ROOT).as_posix() for path in files[: len(SINGLE_FILES)] if not path.is_file()]
    assert not missing, f"файлы из списка трещотки исчезли или переименованы — обновите SINGLE_FILES: {missing}"
    assert any(path.name == "ci.yml" for path in files), "workflow не попал в проверку"


@pytest.mark.parametrize("text", ["# закрывает F-09", "# по итогам код-ревью", "# см. R2-3", "# замечание ИБ-4", "# память проекта"])
def test_the_pattern_recognises_references_to_review_findings(text):
    assert REVIEW_REFERENCE.search(text), text


def test_infrastructure_files_do_not_refer_to_code_review_findings():
    offenders = []
    for path in _scanned_files():
        text = _read(path)
        if text is None:
            continue
        offenders += [
            f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}"
            for number, line in enumerate(text.splitlines(), start=1)
            if REVIEW_REFERENCE.search(line)
        ]
    assert not offenders, "Опишите причину словами, без номеров замечаний:\n" + "\n".join(offenders)
