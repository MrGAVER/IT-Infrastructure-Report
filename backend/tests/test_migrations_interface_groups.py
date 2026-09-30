"""Тесты на миграцию c7e2a91d4b35 — группы портов (interface_groups, interface_group_vlans,
interface_group_open_ports, device_interfaces.group_id).

group_id добавляется через batch_alter_table (на SQLite это пересборка device_interfaces), поэтому
главное, что проверяется: существующие порты и их связи переживают и upgrade, и downgrade.

Запуск: pytest backend/tests/test_migrations_interface_groups.py -v
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
PRE_REVISION = "5b1e7c94a2d8"
NEW_TABLES = {"interface_groups", "interface_group_vlans", "interface_group_open_ports"}


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    """См. идентичную fixture в test_migrations_ip_addresses.py."""
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


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _seed_port_with_vlan(conn: sqlite3.Connection) -> tuple[str, str]:
    """Устройство + порт + VLAN-связь на PRE_REVISION (до появления групп)."""
    dev_id, iface_id, vlan_id, link_id = _uid(), _uid(), _uid(), _uid()
    device_type_id = conn.execute("SELECT id FROM device_types LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO physical_devices (id, device_type_id, serial_number, siem_enabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (dev_id, device_type_id, dev_id[:12], _now(), _now()),
    )
    conn.execute(
        "INSERT INTO device_interfaces (id, physical_device_id, name, is_management, is_data_transfer, vlan_mode, created_at, updated_at) VALUES (?, ?, 'Gi0/1', 0, 0, 'access', ?, ?)",
        (iface_id, dev_id, _now(), _now()),
    )
    conn.execute("INSERT INTO vlans (id, vlan_id, name, created_at, updated_at) VALUES (?, 10, 'VLAN 10', ?, ?)", (vlan_id, _now(), _now()))
    conn.execute("INSERT INTO interface_vlans (id, interface_id, vlan_id, mode, created_at, updated_at) VALUES (?, ?, ?, 'access', ?, ?)", (link_id, iface_id, vlan_id, _now(), _now()))
    conn.commit()
    return iface_id, link_id


def test_upgrade_adds_group_structure_and_keeps_existing_ports(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    iface_id, link_id = _seed_port_with_vlan(conn)
    assert not NEW_TABLES & _tables(conn)
    conn.close()

    command.upgrade(cfg, "head")

    conn = _connect(db_path)
    try:
        assert NEW_TABLES <= _tables(conn)
        assert "group_id" in _columns(conn, "device_interfaces")
        row = conn.execute("SELECT name, vlan_mode, group_id FROM device_interfaces WHERE id=?", (iface_id,)).fetchone()
        assert (row["name"], row["vlan_mode"], row["group_id"]) == ("Gi0/1", "access", None)
        assert conn.execute("SELECT 1 FROM interface_vlans WHERE id=?", (link_id,)).fetchone() is not None
    finally:
        conn.close()


def test_downgrade_removes_group_structure_and_keeps_ports(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    iface_id, link_id = _seed_port_with_vlan(conn)
    conn.close()
    command.upgrade(cfg, "head")

    command.downgrade(cfg, PRE_REVISION)

    conn = _connect(db_path)
    try:
        assert not NEW_TABLES & _tables(conn)
        assert "group_id" not in _columns(conn, "device_interfaces")
        assert conn.execute("SELECT 1 FROM device_interfaces WHERE id=?", (iface_id,)).fetchone() is not None
        assert conn.execute("SELECT 1 FROM interface_vlans WHERE id=?", (link_id,)).fetchone() is not None
    finally:
        conn.close()
