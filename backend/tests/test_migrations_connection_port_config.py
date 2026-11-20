"""Тесты миграции c5d2a8f1e703 — connections.purpose удалено (дублировало роли портов),
добавлена подпись одобренного расхождения; downgrade() рабочий.

Запуск: pytest backend/tests/test_migrations_connection_port_config.py -v
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
TARGET_REVISION = "c5d2a8f1e703"


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


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert_interface(conn: sqlite3.Connection, *, management: int, data: int) -> str:
    device_id, iface_id = _uid(), _uid()
    device_type_id = conn.execute("SELECT id FROM device_types LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO physical_devices (id, device_type_id, serial_number, siem_enabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (device_id, device_type_id, device_id[:12], _now(), _now()),
    )
    conn.execute(
        "INSERT INTO device_interfaces (id, physical_device_id, name, is_management, is_data_transfer, vlan_mode, created_at, updated_at) VALUES (?, ?, 'p1', ?, ?, 'trunk', ?, ?)",
        (iface_id, device_id, management, data, _now(), _now()),
    )
    return iface_id


def _insert_connection(conn: sqlite3.Connection, *, src: str, dst: str, purpose: str | None, description: str | None = None) -> str:
    conn_id = _uid()
    cable_id = conn.execute("SELECT id FROM connection_types LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO connections (id, source_interface_id, destination_interface_id, connection_type_id, purpose, is_active, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
        (conn_id, src, dst, cable_id, purpose, description, _now(), _now()),
    )
    return conn_id


def _seed_pre_migration(db_path: Path) -> dict[str, str]:
    conn = _connect(db_path)
    conn.execute("INSERT INTO connection_types (id, name, created_at, updated_at) VALUES (?, 'Кабель', ?, ?)", (_uid(), _now(), _now()))
    ids = {
        "preset": _insert_connection(conn, src=_insert_interface(conn, management=0, data=1), dst=_insert_interface(conn, management=0, data=1), purpose="Передача данных"),
        "custom": _insert_connection(conn, src=_insert_interface(conn, management=0, data=1), dst=_insert_interface(conn, management=0, data=1), purpose="Резервный канал репликации СХД", description="Кабель 3 м"),
        "custom_no_description": _insert_connection(conn, src=_insert_interface(conn, management=0, data=1), dst=_insert_interface(conn, management=0, data=1), purpose="Резерв"),
        "empty": _insert_connection(conn, src=_insert_interface(conn, management=0, data=1), dst=_insert_interface(conn, management=0, data=1), purpose=None),
    }
    conn.commit()
    conn.close()
    return ids


def test_upgrade_drops_purpose_and_adds_signature_column(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(connections)").fetchall()}
    conn.close()
    assert "purpose" not in cols
    assert "port_config_approved_signature" in cols


def test_upgrade_keeps_custom_purpose_text_in_description(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    ids = _seed_pre_migration(db_path)

    command.upgrade(cfg, TARGET_REVISION)

    conn = _connect(db_path)
    get = lambda key: conn.execute("SELECT description FROM connections WHERE id=?", (ids[key],)).fetchone()["description"]
    assert get("custom") == "Назначение: Резервный канал репликации СХД\nКабель 3 м"
    assert get("custom_no_description") == "Назначение: Резерв"
    assert get("preset") is None  # типовое значение дублирует роли портов — переносить нечего
    assert get("empty") is None
    conn.close()


def test_downgrade_restores_purpose_from_port_roles_only_when_roles_match(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    conn.execute("INSERT INTO connection_types (id, name, created_at, updated_at) VALUES (?, 'Кабель', ?, ?)", (_uid(), _now(), _now()))
    matching = _insert_connection_post(conn, (1, 1), (1, 1))
    mismatching = _insert_connection_post(conn, (1, 0), (0, 1))
    unconfigured = _insert_connection_post(conn, (0, 0), (0, 0))
    conn.commit()
    conn.close()

    command.downgrade(cfg, PRE_REVISION)

    conn = _connect(db_path)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(connections)").fetchall()}
    assert "purpose" in cols and "port_config_approved_signature" not in cols
    purpose = lambda cid: conn.execute("SELECT purpose FROM connections WHERE id=?", (cid,)).fetchone()["purpose"]
    assert purpose(matching) == "Передача данных и управление активами"
    assert purpose(mismatching) is None
    assert purpose(unconfigured) is None
    conn.close()


def test_upgrade_after_downgrade_round_trips(alembic_config):
    cfg, _ = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    command.downgrade(cfg, PRE_REVISION)
    command.upgrade(cfg, TARGET_REVISION)


def _insert_connection_post(conn: sqlite3.Connection, src_flags: tuple[int, int], dst_flags: tuple[int, int]) -> str:
    src = _insert_interface(conn, management=src_flags[0], data=src_flags[1])
    dst = _insert_interface(conn, management=dst_flags[0], data=dst_flags[1])
    conn_id = _uid()
    cable_id = conn.execute("SELECT id FROM connection_types LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO connections (id, source_interface_id, destination_interface_id, connection_type_id, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
        (conn_id, src, dst, cable_id, _now(), _now()),
    )
    return conn_id
