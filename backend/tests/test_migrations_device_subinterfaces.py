"""Тесты на миграцию e3b7d2a9c158 — подинтерфейсы портов (device_subinterfaces).

Миграция только добавляет таблицу; главное, что проверяется: upgrade не трогает существующие порты и их
IP, а downgrade() работает — удаляет таблицу вместе с полиморфными IP/открытыми портами подинтерфейсов
(иначе они остались бы «висячими») и не затрагивает данные физических портов.

Запуск: pytest backend/tests/test_migrations_device_subinterfaces.py -v
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
PRE_REVISION = "b5d2f8a1c673"
REVISION = "e3b7d2a9c158"


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    """См. идентичную fixture в test_migrations_interface_groups.py."""
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
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _seed_port(conn: sqlite3.Connection) -> tuple[str, str, str]:
    """Устройство + порт + IP порта + VLAN на PRE_REVISION. Возвращает (id порта, id IP порта, id VLAN)."""
    dev_id, iface_id, ip_id, vlan_id = _uid(), _uid(), _uid(), _uid()
    device_type_id = conn.execute("SELECT id FROM device_types LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO physical_devices (id, device_type_id, serial_number, siem_enabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (dev_id, device_type_id, dev_id[:12], _now(), _now()),
    )
    conn.execute(
        "INSERT INTO device_interfaces (id, physical_device_id, name, is_management, is_data_transfer, vlan_mode, "
        "created_at, updated_at) VALUES (?, ?, 'Gi0/0', 0, 0, 'trunk', ?, ?)",
        (iface_id, dev_id, _now(), _now()),
    )
    conn.execute(
        "INSERT INTO ip_addresses (id, owner_type, owner_id, ip_address, prefix_length, is_management, created_at, "
        "updated_at) VALUES (?, 'device_interface', ?, '192.168.0.1', 24, 0, ?, ?)",
        (ip_id, iface_id, _now(), _now()),
    )
    conn.execute("INSERT INTO vlans (id, vlan_id, name, created_at, updated_at) VALUES (?, 10, 'VLAN 10', ?, ?)", (vlan_id, _now(), _now()))
    conn.commit()
    return iface_id, ip_id, vlan_id


def _seed_subinterface(conn: sqlite3.Connection, iface_id: str, vlan_id: str) -> tuple[str, str]:
    """Подинтерфейс с IP и открытым портом после upgrade. Возвращает (id IP, id открытого порта)."""
    sub_id, ip_id, port_id = _uid(), _uid(), _uid()
    catalog_id = conn.execute("SELECT id FROM protocol_port_catalogs LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO device_subinterfaces (id, parent_interface_id, name, vlan_id, is_management, is_data_transfer, "
        "created_at, updated_at) VALUES (?, ?, 'Gi0/0.10', ?, 0, 1, ?, ?)",
        (sub_id, iface_id, vlan_id, _now(), _now()),
    )
    conn.execute(
        "INSERT INTO ip_addresses (id, owner_type, owner_id, ip_address, prefix_length, is_management, created_at, "
        "updated_at) VALUES (?, 'device_subinterface', ?, '10.0.10.1', 24, 0, ?, ?)",
        (ip_id, sub_id, _now(), _now()),
    )
    conn.execute(
        "INSERT INTO open_ports (id, owner_type, owner_id, protocol_catalog_id, transport_protocol, created_at, "
        "updated_at) VALUES (?, 'device_subinterface', ?, ?, 'TCP', ?, ?)",
        (port_id, sub_id, catalog_id, _now(), _now()),
    )
    conn.commit()
    return ip_id, port_id


def test_upgrade_adds_subinterfaces_table_and_keeps_existing_data(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    iface_id, ip_id, _ = _seed_port(conn)
    assert "device_subinterfaces" not in _tables(conn)
    conn.close()

    command.upgrade(cfg, REVISION)

    conn = _connect(db_path)
    try:
        assert "device_subinterfaces" in _tables(conn)
        columns = {r["name"]: r for r in conn.execute("PRAGMA table_info(device_subinterfaces)").fetchall()}
        assert set(columns) == {
            "id",
            "parent_interface_id",
            "name",
            "vlan_id",
            "is_management",
            "is_data_transfer",
            "description",
            "created_at",
            "updated_at",
        }
        assert columns["vlan_id"]["notnull"] == 1 and columns["description"]["notnull"] == 0
        assert conn.execute("SELECT name FROM device_interfaces WHERE id=?", (iface_id,)).fetchone()["name"] == "Gi0/0"
        assert conn.execute("SELECT ip_address FROM ip_addresses WHERE id=?", (ip_id,)).fetchone()["ip_address"] == "192.168.0.1"
    finally:
        conn.close()


def test_subinterfaces_cascade_with_their_port_and_vlan_is_protected(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    iface_id, _, vlan_id = _seed_port(conn)
    conn.close()
    command.upgrade(cfg, REVISION)

    conn = _connect(db_path)
    try:
        _seed_subinterface(conn, iface_id, vlan_id)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM vlans WHERE id=?", (vlan_id,))
        conn.rollback()
        conn.execute("DELETE FROM ip_addresses WHERE owner_id=?", (iface_id,))
        conn.execute("DELETE FROM device_interfaces WHERE id=?", (iface_id,))
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM device_subinterfaces").fetchone()[0] == 0
    finally:
        conn.close()


def test_downgrade_drops_table_and_subinterface_owned_rows_but_keeps_ports(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    iface_id, port_ip_id, vlan_id = _seed_port(conn)
    conn.close()
    command.upgrade(cfg, REVISION)
    conn = _connect(db_path)
    sub_ip_id, sub_port_id = _seed_subinterface(conn, iface_id, vlan_id)
    conn.close()

    command.downgrade(cfg, PRE_REVISION)

    conn = _connect(db_path)
    try:
        assert "device_subinterfaces" not in _tables(conn)
        assert conn.execute("SELECT 1 FROM ip_addresses WHERE id=?", (sub_ip_id,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM open_ports WHERE id=?", (sub_port_id,)).fetchone() is None
        # физический порт и его IP не затронуты
        assert conn.execute("SELECT 1 FROM device_interfaces WHERE id=?", (iface_id,)).fetchone() is not None
        assert conn.execute("SELECT 1 FROM ip_addresses WHERE id=?", (port_ip_id,)).fetchone() is not None
    finally:
        conn.close()

    # и повторный upgrade после downgrade проходит
    command.upgrade(cfg, REVISION)
    conn = _connect(db_path)
    try:
        assert "device_subinterfaces" in _tables(conn)
    finally:
        conn.close()
