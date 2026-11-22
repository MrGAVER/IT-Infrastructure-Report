"""Миграция b8e4d2a7c91f — назначение общего IP-адреса в группах портов (interface_groups.ip_purpose).

Колонка добавляется пустой, после чего миграция переносит в группу общее назначение IP её портов —
иначе безусловная запись назначения группой затёрла бы то, что уже введено у портов. downgrade()
снимает колонку и не теряет сами группы (interface_groups пересобирается через batch_alter_table).

Запуск: pytest backend/tests/test_migrations_interface_group_ip_purpose.py -v
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
PRE_REVISION = "e4c8a1d7b350"
IP_PURPOSE_REV = "b8e4d2a7c91f"


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
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _insert_group_with_ip(conn: sqlite3.Connection) -> str:
    dev_id, group_id = _uid(), _uid()
    device_type_id = conn.execute("SELECT id FROM device_types LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO physical_devices (id, device_type_id, serial_number, siem_enabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (dev_id, device_type_id, dev_id[:12], _now(), _now()),
    )
    conn.execute(
        "INSERT INTO interface_groups (id, physical_device_id, name, ip_address, prefix_length, manage_open_ports, "
        "created_at, updated_at) VALUES (?, ?, 'Серверные', '10.0.0.5', 24, 0, ?, ?)",
        (group_id, dev_id, _now(), _now()),
    )
    conn.commit()
    return group_id


def test_upgrade_adds_nullable_column_and_keeps_existing_groups(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    group_id = _insert_group_with_ip(conn)
    assert "ip_purpose" not in _columns(conn, "interface_groups")
    conn.close()

    command.upgrade(cfg, IP_PURPOSE_REV)

    conn = _connect(db_path)
    try:
        assert "ip_purpose" in _columns(conn, "interface_groups")
        row = conn.execute("SELECT name, ip_address, prefix_length, ip_purpose FROM interface_groups WHERE id=?", (group_id,)).fetchone()
        assert (row["name"], row["ip_address"], row["prefix_length"], row["ip_purpose"]) == ("Серверные", "10.0.0.5", 24, None)
    finally:
        conn.close()


def test_downgrade_drops_column_and_keeps_groups(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    group_id = _insert_group_with_ip(conn)
    conn.close()
    command.upgrade(cfg, IP_PURPOSE_REV)

    command.downgrade(cfg, PRE_REVISION)

    conn = _connect(db_path)
    try:
        assert "ip_purpose" not in _columns(conn, "interface_groups")
        row = conn.execute("SELECT ip_address, prefix_length FROM interface_groups WHERE id=?", (group_id,)).fetchone()
        assert (row["ip_address"], row["prefix_length"]) == ("10.0.0.5", 24)
    finally:
        conn.close()


def _insert_device(conn: sqlite3.Connection) -> str:
    dev_id = _uid()
    device_type_id = conn.execute("SELECT id FROM device_types LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO physical_devices (id, device_type_id, serial_number, siem_enabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (dev_id, device_type_id, dev_id[:12], _now(), _now()),
    )
    return dev_id


def _insert_group(conn: sqlite3.Connection, dev_id: str, name: str, ip_address: str | None) -> str:
    group_id = _uid()
    conn.execute(
        "INSERT INTO interface_groups (id, physical_device_id, name, ip_address, prefix_length, manage_open_ports, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, 24, 0, ?, ?)",
        (group_id, dev_id, name, ip_address, _now(), _now()),
    )
    return group_id


def _insert_port(conn: sqlite3.Connection, dev_id: str, group_id: str, name: str, ip_address: str | None, purpose: str | None) -> None:
    iface_id = _uid()
    conn.execute(
        "INSERT INTO device_interfaces (id, physical_device_id, name, is_management, is_data_transfer, vlan_mode, "
        "group_id, created_at, updated_at) VALUES (?, ?, ?, 0, 0, 'access', ?, ?, ?)",
        (iface_id, dev_id, name, group_id, _now(), _now()),
    )
    if ip_address:
        conn.execute(
            "INSERT INTO ip_addresses (id, owner_type, owner_id, ip_address, prefix_length, purpose, is_management, "
            "created_at, updated_at) VALUES (?, 'device_interface', ?, ?, 24, ?, 0, ?, ?)",
            (_uid(), iface_id, ip_address, purpose, _now(), _now()),
        )


def _group_purposes(conn: sqlite3.Connection) -> dict[str, str | None]:
    return {r["name"]: r["ip_purpose"] for r in conn.execute("SELECT name, ip_purpose FROM interface_groups").fetchall()}


def test_upgrade_moves_the_common_purpose_of_member_ports_into_the_group(alembic_config):
    """Безусловная запись назначения группой не должна затирать то, что уже введено у портов."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    dev = _insert_device(conn)
    same = _insert_group(conn, dev, "Одинаковое", "10.0.0.5")
    _insert_port(conn, dev, same, "Gi0/1", "10.0.0.5", "Администрирование")
    _insert_port(conn, dev, same, "Gi0/2", "10.0.0.5", " Администрирование ")  # пробелы не создают «второе» назначение
    _insert_port(conn, dev, same, "Gi0/3", "10.0.0.5", None)  # порт без назначения получит общее
    mixed = _insert_group(conn, dev, "Разное", "10.0.1.5")
    _insert_port(conn, dev, mixed, "Gi0/4", "10.0.1.5", "Управление")
    _insert_port(conn, dev, mixed, "Gi0/5", "10.0.1.5", "Резерв")
    empty = _insert_group(conn, dev, "Пустое", "10.0.2.5")
    _insert_port(conn, dev, empty, "Gi0/6", "10.0.2.5", "")
    _insert_group(conn, dev, "Без портов", "10.0.3.5")
    no_ip = _insert_group(conn, dev, "Без IP", None)
    _insert_port(conn, dev, no_ip, "Gi0/7", None, None)
    stale = _insert_group(conn, dev, "Чужой адрес", "10.0.4.5")
    _insert_port(conn, dev, stale, "Gi0/8", "192.168.9.9", "Не общий IP")  # IP порта не совпадает с общим адресом группы
    conn.commit()
    conn.close()

    command.upgrade(cfg, IP_PURPOSE_REV)

    conn = _connect(db_path)
    try:
        assert _group_purposes(conn) == {
            "Одинаковое": "Администрирование",
            "Разное": None,  # однозначно выбрать нельзя
            "Пустое": None,
            "Без портов": None,
            "Без IP": None,
            "Чужой адрес": None,
        }
        # сами IP портов миграция не трогает
        assert conn.execute("SELECT purpose FROM ip_addresses WHERE ip_address='192.168.9.9'").fetchone()[0] == "Не общий IP"
    finally:
        conn.close()
