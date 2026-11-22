"""Тесты миграции a7c3e9d15b42 — connections.port_config_approved_signature VARCHAR(64) → VARCHAR(255).

Подпись одобрения теперь включает режим порта и отпечатки VLAN и доходит до ~95 символов.
Прежние подписи (`management>data`) сохраняются; downgrade() обнуляет подписи нового формата.

Запуск: pytest backend/tests/test_migrations_connection_signature_wider.py -v
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
PRE_REVISION = "b8e4d2a7c91f"
TARGET_REVISION = "a7c3e9d15b42"

LEGACY = "management>data"
NEW_FORMAT = "|mode:trunk>access"
LONG_NEW_FORMAT = "management_data>none|mode:trunk>access|vlan:" + "1" * 18 + ">" + "2" * 18


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


def _insert_interface(conn: sqlite3.Connection) -> str:
    device_id, iface_id = _uid(), _uid()
    device_type_id = conn.execute("SELECT id FROM device_types LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO physical_devices (id, device_type_id, serial_number, siem_enabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (device_id, device_type_id, device_id[:12], _now(), _now()),
    )
    conn.execute(
        "INSERT INTO device_interfaces (id, physical_device_id, name, is_management, is_data_transfer, vlan_mode, created_at, updated_at) VALUES (?, ?, 'p1', 0, 1, 'trunk', ?, ?)",
        (iface_id, device_id, _now(), _now()),
    )
    return iface_id


def _seed_connections(db_path: Path) -> dict[str, str]:
    conn = _connect(db_path)
    conn.execute("INSERT INTO connection_types (id, name, created_at, updated_at) VALUES (?, 'Кабель', ?, ?)", (_uid(), _now(), _now()))
    cable_id = conn.execute("SELECT id FROM connection_types LIMIT 1").fetchone()[0]
    ids: dict[str, str] = {}
    for key, signature in (("legacy", LEGACY), ("short_new", NEW_FORMAT), ("long_new", LONG_NEW_FORMAT), ("none", None)):
        ids[key] = _uid()
        conn.execute(
            "INSERT INTO connections (id, source_interface_id, destination_interface_id, connection_type_id, is_active, "
            "port_config_approved_signature, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?, ?)",
            (ids[key], _insert_interface(conn), _insert_interface(conn), cable_id, signature, _now(), _now()),
        )
    conn.commit()
    conn.close()
    return ids


def _signature_column_type(db_path: Path) -> str:
    conn = _connect(db_path)
    column = next(r for r in conn.execute("PRAGMA table_info(connections)").fetchall() if r["name"] == "port_config_approved_signature")
    conn.close()
    return column["type"].upper()


def _signature(db_path: Path, connection_id: str) -> str | None:
    conn = _connect(db_path)
    value = conn.execute("SELECT port_config_approved_signature FROM connections WHERE id=?", (connection_id,)).fetchone()[0]
    conn.close()
    return value


def test_upgrade_widens_the_column_and_keeps_every_signature(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    assert _signature_column_type(db_path) == "VARCHAR(64)"
    ids = _seed_connections(db_path)

    command.upgrade(cfg, TARGET_REVISION)

    assert _signature_column_type(db_path) == "VARCHAR(255)"
    assert _signature(db_path, ids["legacy"]) == LEGACY  # прежние подписи не теряются
    assert _signature(db_path, ids["short_new"]) == NEW_FORMAT
    assert _signature(db_path, ids["none"]) is None


def test_downgrade_clears_new_format_signatures_and_keeps_legacy_ones(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    ids = _seed_connections(db_path)

    command.downgrade(cfg, PRE_REVISION)

    assert _signature_column_type(db_path) == "VARCHAR(64)"
    assert _signature(db_path, ids["legacy"]) == LEGACY
    assert _signature(db_path, ids["short_new"]) is None  # формат с `|` прежний код не сверяет
    assert _signature(db_path, ids["long_new"]) is None  # и длиннее колонки — не вместился бы в PostgreSQL
    assert _signature(db_path, ids["none"]) is None


def test_upgrade_after_downgrade_round_trips_to_a_single_head(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    command.downgrade(cfg, PRE_REVISION)
    command.upgrade(cfg, "head")
    assert _signature_column_type(db_path) == "VARCHAR(255)"
