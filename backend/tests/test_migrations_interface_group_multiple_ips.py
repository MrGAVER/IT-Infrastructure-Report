"""Миграция d5a8c3e7b196 — несколько общих IP-адресов у группы портов (таблица interface_group_ips).

upgrade() переносит единственный IP каждой группы (ip_address/prefix_length/ip_purpose) строкой в interface_group_ips и
снимает три колонки; группы без IP ничего не получают. downgrade() возвращает колонки и записывает в них ПЕРВЫЙ адрес
группы, остальные теряются (в старой схеме адрес один).

Запуск: pytest backend/tests/test_migrations_interface_group_multiple_ips.py -v
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
PRE_REVISION = "b3f7a2c91d54"
MULTIPLE_IPS_REV = "d5a8c3e7b196"
_NOW = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    """См. идентичную fixture в test_migrations_interface_group_ip_purpose.py."""
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


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _insert_groups(conn: sqlite3.Connection) -> dict[str, str]:
    """Две группы: с общим IP (адрес, префикс, назначение) и без IP. Возвращает {имя -> id}."""
    dev_id = _uid()
    device_type_id = conn.execute("SELECT id FROM device_types LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO physical_devices (id, device_type_id, serial_number, siem_enabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (dev_id, device_type_id, dev_id[:12], _NOW, _NOW),
    )
    ids = {"С IP": _uid(), "Без IP": _uid()}
    conn.execute(
        "INSERT INTO interface_groups (id, physical_device_id, name, ip_address, prefix_length, ip_purpose, "
        "manage_open_ports, created_at, updated_at) VALUES (?, ?, 'С IP', '10.0.0.5', 24, 'Управление', 0, ?, ?)",
        (ids["С IP"], dev_id, _NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO interface_groups (id, physical_device_id, name, manage_open_ports, created_at, "
        "updated_at) VALUES (?, ?, 'Без IP', 0, ?, ?)",
        (ids["Без IP"], dev_id, _NOW, _NOW),
    )
    conn.commit()
    return ids


def test_upgrade_moves_single_group_ip_into_new_table_and_drops_columns(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    ids = _insert_groups(conn)
    conn.close()

    command.upgrade(cfg, MULTIPLE_IPS_REV)

    conn = _connect(db_path)
    rows = conn.execute("SELECT group_id, ip_address, prefix_length, purpose FROM interface_group_ips").fetchall()
    assert [tuple(r) for r in rows] == [(ids["С IP"], "10.0.0.5", 24, "Управление")]
    assert not {"ip_address", "prefix_length", "ip_purpose"} & _columns(conn, "interface_groups")
    assert conn.execute("SELECT COUNT(*) FROM interface_groups").fetchone()[0] == 2  # группы не потеряны
    conn.close()


def test_downgrade_restores_columns_with_first_ip_of_each_group(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    ids = _insert_groups(conn)
    conn.close()
    command.upgrade(cfg, MULTIPLE_IPS_REV)
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO interface_group_ips (id, group_id, ip_address, prefix_length, purpose, created_at, updated_at) "
        "VALUES (?, ?, '10.0.1.5', 24, 'Данные', '2099-01-01 00:00:00', '2099-01-01 00:00:00')",
        (_uid(), ids["С IP"]),
    )
    conn.commit()
    conn.close()

    command.downgrade(cfg, PRE_REVISION)

    conn = _connect(db_path)
    assert {"ip_address", "prefix_length", "ip_purpose"} <= _columns(conn, "interface_groups")
    got = {
        r["name"]: (r["ip_address"], r["prefix_length"], r["ip_purpose"])
        for r in conn.execute("SELECT name, ip_address, prefix_length, ip_purpose FROM interface_groups")
    }
    assert got == {"С IP": ("10.0.0.5", 24, "Управление"), "Без IP": (None, None, None)}  # второй адрес в старой схеме негде хранить
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'interface_group_ips'").fetchone() is None
    conn.close()


def test_deleting_group_cascades_to_its_ips(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    ids = _insert_groups(conn)
    conn.close()
    command.upgrade(cfg, MULTIPLE_IPS_REV)

    conn = _connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("DELETE FROM interface_groups WHERE id = ?", (ids["С IP"],))
    conn.commit()

    assert conn.execute("SELECT COUNT(*) FROM interface_group_ips").fetchone()[0] == 0
    conn.close()


def test_repeated_upgrade_is_idempotent_and_does_not_duplicate_ips(alembic_config):
    """Ревизии проекта идемпотентны (см. test_the_index_migration_is_idempotent_on_sqlite): повторный накат на базе, где
    таблица создана, а колонки сняты, ничего не ломает и не удваивает перенесённые адреса."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    _insert_groups(conn)
    conn.close()
    command.upgrade(cfg, MULTIPLE_IPS_REV)

    command.stamp(cfg, PRE_REVISION)
    command.upgrade(cfg, MULTIPLE_IPS_REV)

    conn = _connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM interface_group_ips").fetchone()[0] == 1
    conn.close()


def test_upgrade_does_not_duplicate_ips_when_table_exists_but_columns_remain(alembic_config):
    """Частично выполненная ревизия (таблица уже заполнена, колонки ещё не сняты) при повторе не удваивает адреса группы."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    ids = _insert_groups(conn)
    conn.close()
    command.upgrade(cfg, MULTIPLE_IPS_REV)
    command.downgrade(cfg, PRE_REVISION)  # колонки вернулись с первым адресом
    conn = _connect(db_path)
    conn.execute(
        "CREATE TABLE interface_group_ips (id VARCHAR(36) PRIMARY KEY, group_id VARCHAR(36) NOT NULL REFERENCES "
        "interface_groups(id) ON DELETE CASCADE, ip_address VARCHAR(64) NOT NULL, prefix_length INTEGER, purpose "
        "VARCHAR(255), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
    )
    conn.execute("INSERT INTO interface_group_ips VALUES (?, ?, '10.0.0.5', 24, 'Управление', ?, ?)", (_uid(), ids["С IP"], _NOW, _NOW))
    conn.commit()
    conn.close()

    command.upgrade(cfg, MULTIPLE_IPS_REV)

    conn = _connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM interface_group_ips").fetchone()[0] == 1
    assert not {"ip_address", "prefix_length", "ip_purpose"} & _columns(conn, "interface_groups")
    conn.close()
