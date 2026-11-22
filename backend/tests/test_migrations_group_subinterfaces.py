"""Тесты на миграцию b8e4c2f6a109 — подинтерфейсы групп портов (флаг manage_subinterfaces и три таблицы шаблонов).

Миграция только добавляет структуру: существующие группы получают manage_subinterfaces = 0 и по-прежнему не трогают
подинтерфейсы своих портов; шаблоны уходят каскадом вместе с группой, VLAN под защитой; downgrade() работает и
не затрагивает уже записанные в порты данные.

Запуск: pytest backend/tests/test_migrations_group_subinterfaces.py -v
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
PRE_REVISION = "a7d3e9c1f452"
REVISION = "b8e4c2f6a109"
NEW_TABLES = {"interface_group_subinterfaces", "interface_group_subinterface_ips", "interface_group_subinterface_open_ports"}


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    """См. идентичную fixture в test_migrations_device_subinterfaces.py."""
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


def _seed_group(conn: sqlite3.Connection) -> tuple[str, str]:
    """Устройство + группа портов + VLAN на PRE_REVISION. Возвращает (id группы, id VLAN)."""
    dev_id, group_id, vlan_id = _uid(), _uid(), _uid()
    device_type_id = conn.execute("SELECT id FROM device_types LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO physical_devices (id, device_type_id, serial_number, siem_enabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (dev_id, device_type_id, dev_id[:12], _now(), _now()),
    )
    conn.execute(
        "INSERT INTO interface_groups (id, physical_device_id, name, vlan_mode, all_vlans, manage_open_ports, "
        "created_at, updated_at) VALUES (?, ?, 'Серверные', 'trunk', 0, 0, ?, ?)",
        (group_id, dev_id, _now(), _now()),
    )
    conn.execute("INSERT INTO vlans (id, vlan_id, name, created_at, updated_at) VALUES (?, 10, 'VLAN 10', ?, ?)", (vlan_id, _now(), _now()))
    conn.commit()
    return group_id, vlan_id


def _seed_template(conn: sqlite3.Connection, group_id: str, vlan_id: str) -> None:
    """Шаблон подинтерфейса группы с IP и открытым портом (после upgrade)."""
    sub_id = _uid()
    catalog_id = conn.execute("SELECT id FROM protocol_port_catalogs LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO interface_group_subinterfaces (id, group_id, vlan_id, is_management, is_data_transfer, "
        "created_at, updated_at) VALUES (?, ?, ?, 0, 1, ?, ?)",
        (sub_id, group_id, vlan_id, _now(), _now()),
    )
    conn.execute(
        "INSERT INTO interface_group_subinterface_ips (id, subinterface_id, ip_address, prefix_length, created_at, "
        "updated_at) VALUES (?, ?, '10.0.10.1', 24, ?, ?)",
        (_uid(), sub_id, _now(), _now()),
    )
    conn.execute(
        "INSERT INTO interface_group_subinterface_open_ports (id, subinterface_id, protocol_catalog_id, "
        "transport_protocol, created_at, updated_at) VALUES (?, ?, ?, 'TCP', ?, ?)",
        (_uid(), sub_id, catalog_id, _now(), _now()),
    )
    conn.commit()


def test_upgrade_adds_tables_and_flag_and_keeps_existing_groups_unmanaged(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    group_id, _ = _seed_group(conn)
    assert not NEW_TABLES & _tables(conn)
    conn.close()

    command.upgrade(cfg, REVISION)

    conn = _connect(db_path)
    try:
        assert NEW_TABLES <= _tables(conn)
        row = conn.execute("SELECT name, vlan_mode, manage_subinterfaces FROM interface_groups WHERE id=?", (group_id,)).fetchone()
        assert (row["name"], row["vlan_mode"], row["manage_subinterfaces"]) == ("Серверные", "trunk", 0)
        columns = {r["name"]: r for r in conn.execute("PRAGMA table_info(interface_group_subinterfaces)").fetchall()}
        assert set(columns) == {"id", "group_id", "vlan_id", "is_management", "is_data_transfer", "description", "created_at", "updated_at"}
    finally:
        conn.close()


def test_templates_cascade_with_group_and_vlan_is_protected(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    group_id, vlan_id = _seed_group(conn)
    conn.close()
    command.upgrade(cfg, REVISION)

    conn = _connect(db_path)
    try:
        _seed_template(conn, group_id, vlan_id)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM vlans WHERE id=?", (vlan_id,))
        conn.rollback()
        conn.execute("DELETE FROM interface_groups WHERE id=?", (group_id,))
        conn.commit()
        for table in NEW_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    finally:
        conn.close()


def test_downgrade_drops_tables_and_flag_and_keeps_groups(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    group_id, vlan_id = _seed_group(conn)
    conn.close()
    command.upgrade(cfg, REVISION)
    conn = _connect(db_path)
    _seed_template(conn, group_id, vlan_id)
    conn.close()

    command.downgrade(cfg, PRE_REVISION)

    conn = _connect(db_path)
    try:
        assert not NEW_TABLES & _tables(conn)
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(interface_groups)").fetchall()}
        assert "manage_subinterfaces" not in columns
        assert conn.execute("SELECT name FROM interface_groups WHERE id=?", (group_id,)).fetchone()["name"] == "Серверные"
    finally:
        conn.close()

    command.upgrade(cfg, REVISION)  # и повторный upgrade после downgrade проходит
    conn = _connect(db_path)
    try:
        assert NEW_TABLES <= _tables(conn)
    finally:
        conn.close()
