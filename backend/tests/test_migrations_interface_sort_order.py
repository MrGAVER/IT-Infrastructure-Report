"""Тесты на миграцию c5d2a8e1f730 — порядок портов устройства (device_interfaces.sort_order).

Существующие порты расставляются по «естественной» сортировке имени в пределах устройства (Gi0/2 раньше Gi0/10, регистр не
важен); у разных устройств нумерация независима; downgrade() снимает колонку.

Запуск: pytest backend/tests/test_migrations_interface_sort_order.py -v
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
PRE_REVISION = "b8e4c2f6a109"
REVISION = "c5d2a8e1f730"

pytestmark = pytest.mark.sqlite_only


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    """См. идентичную fixture в test_migrations_group_subinterfaces.py."""
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


def _device(conn: sqlite3.Connection) -> str:
    dev_id = _uid()
    device_type_id = conn.execute("SELECT id FROM device_types LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO physical_devices (id, device_type_id, serial_number, siem_enabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (dev_id, device_type_id, dev_id[:12], _now(), _now()),
    )
    return dev_id


def _port(conn: sqlite3.Connection, device_id: str, name: str, created_at: str | None = None) -> str:
    port_id = _uid()
    conn.execute(
        "INSERT INTO device_interfaces (id, physical_device_id, name, is_management, is_data_transfer, vlan_mode, "
        "all_vlans, created_at, updated_at) VALUES (?, ?, ?, 0, 0, 'trunk', 0, ?, ?)",
        (port_id, device_id, name, created_at or _now(), _now()),
    )
    return port_id


def _order(conn: sqlite3.Connection, device_id: str) -> list[str]:
    rows = conn.execute("SELECT name FROM device_interfaces WHERE physical_device_id=? ORDER BY sort_order, created_at, id", (device_id,)).fetchall()
    return [r["name"] for r in rows]


def test_upgrade_sorts_existing_ports_naturally_per_device(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    first, second = _device(conn), _device(conn)
    # Порты заведены вперемешку: порядок вставки не совпадает ни с алфавитным, ни с естественным.
    for name in ("Gi0/10", "Gi0/2", "gi0/1", "Gi0/20", "Mgmt0"):
        _port(conn, first, name)
    for name in ("Te1/0/2", "Te1/0/1"):
        _port(conn, second, name)
    conn.commit()
    conn.close()

    command.upgrade(cfg, REVISION)

    conn = _connect(db_path)
    try:
        assert _order(conn, first) == ["gi0/1", "Gi0/2", "Gi0/10", "Gi0/20", "Mgmt0"]
        assert _order(conn, second) == ["Te1/0/1", "Te1/0/2"]
        positions = [
            r["sort_order"]
            for r in conn.execute("SELECT sort_order FROM device_interfaces WHERE physical_device_id=? ORDER BY sort_order", (first,)).fetchall()
        ]
        assert positions == [0, 1, 2, 3, 4]
    finally:
        conn.close()


def test_upgrade_breaks_ties_by_creation_time(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    dev = _device(conn)
    late = _port(conn, dev, "Gi0/1", "2026-10-02T00:00:00+00:00")
    early = _port(conn, dev, "Gi0/1", "2026-10-01T00:00:00+00:00")
    conn.commit()
    conn.close()

    command.upgrade(cfg, REVISION)

    conn = _connect(db_path)
    try:
        orders = {r["id"]: r["sort_order"] for r in conn.execute("SELECT id, sort_order FROM device_interfaces WHERE physical_device_id=?", (dev,)).fetchall()}
        assert orders[early] == 0 and orders[late] == 1
    finally:
        conn.close()


def test_upgrade_on_empty_table_and_downgrade_drops_column(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, REVISION)
    conn = _connect(db_path)
    try:
        columns = {r["name"]: r for r in conn.execute("PRAGMA table_info(device_interfaces)").fetchall()}
        assert "sort_order" in columns and columns["sort_order"]["notnull"] == 1
    finally:
        conn.close()

    command.downgrade(cfg, PRE_REVISION)

    conn = _connect(db_path)
    try:
        assert "sort_order" not in {r["name"] for r in conn.execute("PRAGMA table_info(device_interfaces)").fetchall()}
    finally:
        conn.close()
