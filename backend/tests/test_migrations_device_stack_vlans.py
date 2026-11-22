"""Тесты миграции a7d3e9c1f452 — таблица device_stack_vlans (общие настройки VLAN стека).

Запуск: pytest backend/tests/test_migrations_device_stack_vlans.py -v
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent.parent
PRE_REVISION = "f1a6c3d8e279"
TARGET_REVISION = "a7d3e9c1f452"


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
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _columns(conn, table: str) -> dict[str, tuple]:
    return {row[1]: row for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _seed_stack_and_vlan(conn) -> tuple[str, str]:
    conn.execute("INSERT INTO device_stacks (id, name, created_at, updated_at) VALUES ('s1', 'Стек', '2026-01-01', '2026-01-01')")
    conn.execute("INSERT INTO vlans (id, vlan_id, name, created_at, updated_at) VALUES ('v1', 10, 'mgmt', '2026-01-01', '2026-01-01')")
    return "s1", "v1"


def test_upgrade_creates_the_table_with_the_same_columns_as_the_model(alembic_config):
    from app.models import DeviceStackVLAN

    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    with _connect(db_path) as conn:
        assert not _columns(conn, "device_stack_vlans")
    command.upgrade(cfg, TARGET_REVISION)
    with _connect(db_path) as conn:
        assert set(_columns(conn, "device_stack_vlans")) == {c.name for c in DeviceStackVLAN.__table__.columns}


def test_unique_pair_and_vlan_without_cascade_but_stack_with_cascade(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    with _connect(db_path) as conn:
        stack_id, vlan_id = _seed_stack_and_vlan(conn)
        insert = (
            "INSERT INTO device_stack_vlans (id, stack_id, vlan_id, is_management, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, '2026-01-01', '2026-01-01')"
        )
        conn.execute(insert, ("a", stack_id, vlan_id))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("b", stack_id, vlan_id))  # одна настройка на пару «стек — VLAN»
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM vlans WHERE id = ?", (vlan_id,))  # VLAN с настройкой удалить нельзя
        conn.execute("DELETE FROM device_stacks WHERE id = ?", (stack_id,))
        assert conn.execute("SELECT COUNT(*) FROM device_stack_vlans").fetchone()[0] == 0  # настройка ушла вместе со стеком


def test_downgrade_drops_the_table_and_upgrade_is_repeatable(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    command.downgrade(cfg, PRE_REVISION)
    with _connect(db_path) as conn:
        assert not _columns(conn, "device_stack_vlans")
    command.upgrade(cfg, TARGET_REVISION)
    with _connect(db_path) as conn:
        assert _columns(conn, "device_stack_vlans")
