"""Тесты на миграцию d8e35a1c7f60 — interface_ips/vm_ips и information_system_sources.ip_address
объединены в ip_addresses (owner_type/owner_id); containers.management_ip удалена как
неиспользуемая. По итогам вопросов 1/3/5 отчёта по анализу БД.

Гоняется на одноразовой SQLite БД в /tmp — тот же приём, что и в остальных test_migrations_*.py.

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_migrations_ip_addresses.py -v
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
PRE_REVISION = "c4a91e6f2b83"  # последняя ревизия до этой миграции
TARGET_REVISION = "d8e35a1c7f60"


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


def _insert_interface(conn: sqlite3.Connection, device_id: str) -> str:
    iface_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO device_interfaces (id, physical_device_id, name, is_management, is_data_transfer, created_at, "
        "updated_at) VALUES (?, ?, 'eth0', 0, 1, ?, ?)",
        (iface_id, device_id, now, now),
    )
    conn.commit()
    return iface_id


def _insert_virtual_machine(conn: sqlite3.Connection) -> str:
    vm_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO virtual_machines (id, name, status, created_at, updated_at) VALUES (?, ?, 'active', ?, ?)",
        (vm_id, f"VM-{vm_id[:8]}", now, now),
    )
    conn.commit()
    return vm_id


def _insert_information_system(conn: sqlite3.Connection) -> str:
    is_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO information_systems (id, name, type, status, siem_enabled, crypto_protection_enabled, created_at, "
        "updated_at) VALUES (?, ?, 'ИС', 'active', 0, 0, ?, ?)",
        (is_id, f"ИС {is_id[:8]}", now, now),
    )
    conn.commit()
    return is_id


def _insert_source(conn: sqlite3.Connection, is_id: str, *, ip_address: str | None = None) -> str:
    source_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO information_system_sources (id, information_system_id, source_type, ip_address, "
        "external_interaction, created_at, updated_at) VALUES (?, ?, 'manual', ?, 0, ?, ?)",
        (source_id, is_id, ip_address, now, now),
    )
    conn.commit()
    return source_id


def test_interface_ip_migrated_with_device_interface_owner_type(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    device_id = _insert_physical_device(conn)
    iface_id = _insert_interface(conn, device_id)
    ip_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO interface_ips (id, interface_id, ip_address, prefix_length, purpose, is_management, created_at, "
        "updated_at) VALUES (?, ?, '10.0.0.1', 24, 'управление', 1, ?, ?)",
        (ip_id, iface_id, now, now),
    )
    conn.commit()
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute("SELECT owner_type, owner_id, ip_address, prefix_length, purpose, is_management FROM ip_addresses WHERE id=?", (ip_id,)).fetchone()
    assert row is not None
    assert row["owner_type"] == "device_interface"
    assert row["owner_id"] == iface_id
    assert row["ip_address"] == "10.0.0.1"
    assert row["prefix_length"] == 24
    assert row["is_management"] == 1
    conn.close()


def test_vm_ip_migrated_with_virtual_machine_owner_type(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    vm_id = _insert_virtual_machine(conn)
    ip_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO vm_ips (id, virtual_machine_id, ip_address, is_management, created_at, updated_at) VALUES (?, ?, '192.168.1.5', 0, ?, ?)",
        (ip_id, vm_id, now, now),
    )
    conn.commit()
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute("SELECT owner_type, owner_id, ip_address FROM ip_addresses WHERE id=?", (ip_id,)).fetchone()
    assert row is not None
    assert row["owner_type"] == "virtual_machine"
    assert row["owner_id"] == vm_id
    assert row["ip_address"] == "192.168.1.5"
    conn.close()


def test_source_ip_address_split_into_separate_rows(alembic_config):
    """information_system_sources.ip_address хранила несколько адресов через запятую — миграция
    разбивает их на отдельные строки ip_addresses (вопрос 3/5 отчёта по анализу БД)."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    is_id = _insert_information_system(conn)
    source_id = _insert_source(conn, is_id, ip_address=" 10.1.1.1 , 10.1.1.2,10.1.1.3 ")
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT ip_address FROM ip_addresses WHERE owner_type='information_system_source' AND owner_id=? ORDER BY ip_address",
        (source_id,),
    ).fetchall()
    assert [r["ip_address"] for r in rows] == ["10.1.1.1", "10.1.1.2", "10.1.1.3"]
    conn.close()


def test_source_without_ip_address_produces_no_rows(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    is_id = _insert_information_system(conn)
    source_id = _insert_source(conn, is_id, ip_address=None)
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM ip_addresses WHERE owner_type='information_system_source' AND owner_id=?", (source_id,)).fetchone()[0]
    assert count == 0
    conn.close()


def test_old_tables_dropped_and_columns_removed(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "interface_ips" not in tables
    assert "vm_ips" not in tables
    assert "ip_addresses" in tables

    container_cols = {r["name"] for r in conn.execute("PRAGMA table_info(containers)").fetchall()}
    assert "management_ip" not in container_cols

    source_cols = {r["name"] for r in conn.execute("PRAGMA table_info(information_system_sources)").fetchall()}
    assert "ip_address" not in source_cols
    conn.close()


def test_ip_addresses_real_ddl_after_migration(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    columns = {r["name"]: r for r in conn.execute("PRAGMA table_info(ip_addresses)").fetchall()}
    assert set(columns) == {"id", "owner_type", "owner_id", "ip_address", "prefix_length", "purpose", "is_management", "created_at", "updated_at"}
    assert columns["ip_address"]["notnull"] == 1
    assert columns["prefix_length"]["notnull"] == 0
    indexes = {r["name"] for r in conn.execute("PRAGMA index_list(ip_addresses)").fetchall()}
    assert "ix_ip_addresses_owner" in indexes
    conn.close()


def test_containers_and_sources_real_ddl_preserved_after_rebuild(alembic_config):
    """Пересборка на SQLite не должна терять FK/индексы остальных (не удаляемых) колонок."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    container_fks = {fk["table"] for fk in conn.execute("PRAGMA foreign_key_list(containers)").fetchall()}
    assert container_fks == {"virtual_machines", "physical_devices"}
    source_fks = {fk["table"] for fk in conn.execute("PRAGMA foreign_key_list(information_system_sources)").fetchall()}
    assert source_fks == {"containers", "virtual_machines", "physical_devices", "information_systems"}
    source_indexes = {r["name"] for r in conn.execute("PRAGMA index_list(information_system_sources)").fetchall()}
    assert "ix_information_system_sources_information_system_id" in source_indexes
    conn.close()


def test_downgrade_is_not_supported(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    with pytest.raises(RuntimeError):
        command.downgrade(cfg, PRE_REVISION)
