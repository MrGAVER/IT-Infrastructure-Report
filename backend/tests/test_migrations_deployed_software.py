"""Тесты на миграцию c4a91e6f2b83 — device_software/vm_software объединены в deployed_software
(owner_type/owner_id), по итогам вопроса 2 отчёта по анализу БД.

Гоняется на одноразовой SQLite БД в /tmp — тот же приём, что и в
test_migrations_isprotocol_catalog.py/test_migrations_open_ports_catalog.py.

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_migrations_deployed_software.py -v
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent.parent
PRE_REVISION = "b7f2c1e5a904"  # последняя ревизия до этой миграции
TARGET_REVISION = "c4a91e6f2b83"


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    """См. идентичную fixture в test_migrations_isprotocol_catalog.py."""
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


def _insert_software_asset(conn: sqlite3.Connection, name: str) -> str:
    asset_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO software_assets (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (asset_id, name, now, now),
    )
    conn.commit()
    return asset_id


def _insert_physical_device(conn: sqlite3.Connection) -> str:
    dev_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    device_type_id = conn.execute("SELECT id FROM device_types LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO physical_devices (id, device_type_id, serial_number, siem_enabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (dev_id, device_type_id, dev_id[:12], now, now),
    )
    conn.commit()
    return dev_id


def _insert_virtual_machine(conn: sqlite3.Connection) -> str:
    vm_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO virtual_machines (id, name, status, created_at, updated_at) VALUES (?, ?, 'active', ?, ?)",
        (vm_id, f"VM-{vm_id[:8]}", now, now),
    )
    conn.commit()
    return vm_id


def _insert_device_software(conn: sqlite3.Connection, device_id: str, asset_id: str, *, version: str | None = None) -> str:
    row_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO device_software (id, physical_device_id, software_asset_id, version, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (row_id, device_id, asset_id, version, now, now),
    )
    conn.commit()
    return row_id


def _insert_vm_software(conn: sqlite3.Connection, vm_id: str, asset_id: str, *, version: str | None = None) -> str:
    row_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO vm_software (id, virtual_machine_id, software_asset_id, version, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (row_id, vm_id, asset_id, version, now, now),
    )
    conn.commit()
    return row_id


def test_device_software_migrated_with_physical_device_owner_type(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    device_id = _insert_physical_device(conn)
    asset_id = _insert_software_asset(conn, "1С:Предприятие")
    row_id = _insert_device_software(conn, device_id, asset_id, version="8.3")
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute("SELECT owner_type, owner_id, software_asset_id, version FROM deployed_software WHERE id=?", (row_id,)).fetchone()
    assert row is not None
    assert row["owner_type"] == "physical_device"
    assert row["owner_id"] == device_id
    assert row["software_asset_id"] == asset_id
    assert row["version"] == "8.3"
    conn.close()


def test_vm_software_migrated_with_virtual_machine_owner_type(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    vm_id = _insert_virtual_machine(conn)
    asset_id = _insert_software_asset(conn, "Nginx")
    row_id = _insert_vm_software(conn, vm_id, asset_id)
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute("SELECT owner_type, owner_id, software_asset_id FROM deployed_software WHERE id=?", (row_id,)).fetchone()
    assert row is not None
    assert row["owner_type"] == "virtual_machine"
    assert row["owner_id"] == vm_id
    assert row["software_asset_id"] == asset_id
    conn.close()


def test_ids_preserved_across_both_tables_without_collision(alembic_config):
    """Обе исходные таблицы независимо генерировали UUID для id — совпадение крайне маловероятно,
    но перенос через один общий id-namespace обязан был бы упасть на PRIMARY KEY, если бы вдруг
    совпало; тест хотя бы проверяет, что строки из разных исходных таблиц не затирают друг друга,
    когда используют явно разные id (обычный случай)."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    device_id = _insert_physical_device(conn)
    vm_id = _insert_virtual_machine(conn)
    asset_id = _insert_software_asset(conn, "Общее ПО")
    dev_row_id = _insert_device_software(conn, device_id, asset_id)
    vm_row_id = _insert_vm_software(conn, vm_id, asset_id)
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM deployed_software").fetchone()[0]
    assert count == 2
    assert conn.execute("SELECT owner_type FROM deployed_software WHERE id=?", (dev_row_id,)).fetchone()["owner_type"] == "physical_device"
    assert conn.execute("SELECT owner_type FROM deployed_software WHERE id=?", (vm_row_id,)).fetchone()["owner_type"] == "virtual_machine"
    conn.close()


def test_old_tables_are_dropped(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "device_software" not in tables
    assert "vm_software" not in tables
    assert "deployed_software" in tables
    conn.close()


def test_deployed_software_real_ddl_after_migration(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    columns = {r["name"]: r for r in conn.execute("PRAGMA table_info(deployed_software)").fetchall()}
    assert set(columns) == {"id", "owner_type", "owner_id", "software_asset_id", "version", "created_at", "updated_at"}
    assert columns["owner_type"]["notnull"] == 1
    assert columns["owner_id"]["notnull"] == 1
    assert columns["software_asset_id"]["notnull"] == 1
    assert columns["version"]["notnull"] == 0
    fks = conn.execute("PRAGMA foreign_key_list(deployed_software)").fetchall()
    assert any(fk["table"] == "software_assets" for fk in fks)
    indexes = {r["name"] for r in conn.execute("PRAGMA index_list(deployed_software)").fetchall()}
    assert "ix_deployed_software_owner" in indexes
    conn.close()


def test_downgrade_is_not_supported(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    with pytest.raises(RuntimeError):
        command.downgrade(cfg, PRE_REVISION)
