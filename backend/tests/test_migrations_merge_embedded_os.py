"""Тесты на миграцию 811f39a40ec7 — слияние дублей EmbeddedOperatingSystem, накопленных багом
в services/catalogs.py:_seed_operating_systems (SONiC заводился заново при каждом запуске
приложения, см. test_embedded_os_seeding.py на сам исправленный баг сидинга).

Гоняется на одноразовой SQLite БД в /tmp — тот же приём, что и в test_migrations_device_categories.py.

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_migrations_merge_embedded_os.py -v
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent.parent
PRE_REVISION = "c8d15d8bc6b4"  # последняя ревизия до этой миграции
TARGET_REVISION = "811f39a40ec7"


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    import app.config as app_config

    db_path = tmp_path / "migration_test.db"
    monkeypatch.setattr(app_config, "DATABASE_URL", f"sqlite:///{db_path}")
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False
    return cfg, db_path


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _insert_embedded_os(conn: sqlite3.Connection, *, name: str, version: str | None, created_at: str) -> str:
    row_id = _uid()
    conn.execute(
        "INSERT INTO embedded_operating_systems (id, name, version, vendor, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (row_id, name, version, "Community", created_at, created_at),
    )
    return row_id


def _insert_device(conn: sqlite3.Connection, *, serial_number: str, embedded_os_id: str | None) -> str:
    device_type_id = conn.execute("SELECT id FROM device_types LIMIT 1").fetchone()["id"]
    device_id = _uid()
    conn.execute(
        "INSERT INTO physical_devices (id, device_type_id, serial_number, siem_enabled, embedded_os_id, created_at, "
        "updated_at) VALUES (?,?,?,0,?,'2026-01-01','2026-01-01')",
        (device_id, device_type_id, serial_number, embedded_os_id),
    )
    return device_id


def test_merges_duplicate_sonic_entries_keeping_the_oldest(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    ids = [_insert_embedded_os(conn, name="SONiC", version=None, created_at=f"2026-01-0{i}") for i in (1, 2, 3)]
    conn.commit()
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)

    conn = _connect(db_path)
    rows = conn.execute("SELECT id FROM embedded_operating_systems WHERE name='SONiC'").fetchall()
    assert len(rows) == 1
    assert rows[0]["id"] == ids[0]  # самая старая (created_at='2026-01-01') — оставлена
    conn.close()


def test_reassigns_devices_referencing_a_deleted_duplicate(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    canonical_id = _insert_embedded_os(conn, name="SONiC", version=None, created_at="2026-01-01")
    duplicate_id = _insert_embedded_os(conn, name="SONiC", version=None, created_at="2026-01-02")
    device_id = _insert_device(conn, serial_number="SN-SONIC-DUP", embedded_os_id=duplicate_id)
    conn.commit()
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)

    conn = _connect(db_path)
    device = conn.execute("SELECT embedded_os_id FROM physical_devices WHERE id=?", (device_id,)).fetchone()
    assert device["embedded_os_id"] == canonical_id
    remaining = conn.execute("SELECT COUNT(*) AS c FROM embedded_operating_systems WHERE id=?", (duplicate_id,)).fetchone()
    assert remaining["c"] == 0
    conn.close()


def test_does_not_touch_entries_without_duplicates(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    single_id = _insert_embedded_os(conn, name="Cisco IOS", version="15", created_at="2026-01-01")
    conn.commit()
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)

    conn = _connect(db_path)
    row = conn.execute("SELECT id FROM embedded_operating_systems WHERE name='Cisco IOS'").fetchone()
    assert row["id"] == single_id
    conn.close()


def test_migration_is_a_noop_on_a_fresh_database_without_duplicates(alembic_config):
    """Свежая база (единственный SONiC от seed_defaults(), уже исправленного) не должна
    сломаться на этой миграции — не должно упасть исключение, число записей не меняется."""
    cfg, _db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)  # не должно бросить исключение
