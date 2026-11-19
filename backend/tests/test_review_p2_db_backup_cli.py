"""Команда `python -m app.services.db_backup` — копия SQLite-базы перед миграцией в Docker-образе.

Команда запускается из docker-entrypoint.sh до `alembic upgrade head`. Здесь она проверяется как настоящий подпроцесс (адрес БД — из
переменных окружения, как в контейнере): код возврата 0 — миграцию можно начинать, 1 — копию сделать не удалось. Логика самой копии
(ревизии, ротация, согласованность) покрыта в test_launcher_backup.py: её использует и EXE.

Запуск: pytest backend/tests/test_review_p2_db_backup_cli.py -v
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.db_backup import SKIP_BACKUP_ENV, sqlite_database_path

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("sqlite:////app/data/infra_registry.db", Path("/app/data/infra_registry.db")),
        ("sqlite:///relative.db", Path("relative.db")),
        ("sqlite:///:memory:", None),
        ("sqlite://", None),
        ("sqlite:///file:registry.db?uri=true", None),
        ("postgresql+psycopg://infra:secret@db/infra_registry", None),
    ],
)
def test_sqlite_database_path(url, expected):
    assert sqlite_database_path(url) == expected


def _run(database_url: str, data_dir: Path, **extra_env: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database_url, "INFRA_REGISTRY_DATA_DIR": str(data_dir), "PYTHONPATH": str(BACKEND_DIR), **extra_env}
    if SKIP_BACKUP_ENV not in extra_env:
        env.pop(SKIP_BACKUP_ENV, None)
    return subprocess.run([sys.executable, "-m", "app.services.db_backup"], env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)


def _backups(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.bak"))


def _legacy_database(path: Path) -> None:
    """БД с таблицей данных, но без alembic_version: миграция её изменит — копия обязана быть."""
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE manufacturers (id TEXT, name TEXT)")
        conn.execute("INSERT INTO manufacturers VALUES ('1', 'Старый')")


def test_old_sqlite_database_is_backed_up_and_the_path_is_printed(tmp_path):
    db_path = tmp_path / "infra_registry.db"
    _legacy_database(db_path)

    result = _run(f"sqlite:///{db_path}", tmp_path)

    assert result.returncode == 0, result.stderr
    backups = _backups(tmp_path)
    assert len(backups) == 1 and str(backups[0]) in result.stdout
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("SELECT name FROM manufacturers").fetchall() == [("Старый",)]


def test_missing_database_needs_no_backup(tmp_path):
    db_path = tmp_path / "infra_registry.db"

    result = _run(f"sqlite:///{db_path}", tmp_path)

    assert result.returncode == 0, result.stderr
    assert _backups(tmp_path) == [] and not db_path.exists(), "первый запуск: копировать нечего, файл БД проверка не создаёт"


def test_unreadable_database_fails_the_command_so_the_migration_does_not_start(tmp_path):
    db_path = tmp_path / "infra_registry.db"
    db_path.write_bytes("это не база данных SQLite".encode() * 100)

    result = _run(f"sqlite:///{db_path}", tmp_path)

    assert result.returncode == 1
    assert "ОШИБКА" in result.stderr and "База не изменена" in result.stderr and SKIP_BACKUP_ENV in result.stderr
    assert _backups(tmp_path) == []


def test_skip_variable_disables_the_backup(tmp_path):
    db_path = tmp_path / "infra_registry.db"
    _legacy_database(db_path)

    result = _run(f"sqlite:///{db_path}", tmp_path, **{SKIP_BACKUP_ENV: "1"})

    assert result.returncode == 0, result.stderr
    assert _backups(tmp_path) == [] and SKIP_BACKUP_ENV in result.stdout


def test_postgresql_is_left_to_the_database_tools(tmp_path):
    """К серверу команда не подключается (его там может ещё не быть): только подсказка, код 0."""
    result = _run("postgresql+psycopg://infra:secret@127.0.0.1:1/infra_registry", tmp_path)

    assert result.returncode == 0, result.stderr
    assert "не SQLite" in result.stdout and "README" in result.stdout
    assert _backups(tmp_path) == []
