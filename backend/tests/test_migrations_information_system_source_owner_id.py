"""Тесты на миграцию 944bd490d967 — information_system_sources.physical_device_id/
virtual_machine_id/container_id объединены в owner_id (source_type играет роль owner_type).
По итогам п.5 отчёта по анализу БД (последний из 9 вопросов на согласование).

Гоняется на одноразовой SQLite БД в /tmp — тот же приём, что и в остальных test_migrations_*.py.

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_migrations_information_system_source_owner_id.py -v
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
PRE_REVISION = "d8e35a1c7f60"  # последняя ревизия до этой миграции
TARGET_REVISION = "944bd490d967"


def _uid() -> str:
    return str(uuid.uuid4())


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


def _insert_virtual_machine(conn: sqlite3.Connection) -> str:
    vm_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO virtual_machines (id, name, status, created_at, updated_at) VALUES (?, ?, 'active', ?, ?)",
        (vm_id, f"VM-{vm_id[:8]}", now, now),
    )
    conn.commit()
    return vm_id


def _insert_container(conn: sqlite3.Connection) -> str:
    cont_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO containers (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (cont_id, f"CT-{cont_id[:8]}", now, now),
    )
    conn.commit()
    return cont_id


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


def _insert_source(conn: sqlite3.Connection, is_id: str, source_type: str, *, physical_device_id=None, virtual_machine_id=None, container_id=None) -> str:
    source_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO information_system_sources (id, information_system_id, source_type, physical_device_id, "
        "virtual_machine_id, container_id, external_interaction, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, "
        "?, ?)",
        (source_id, is_id, source_type, physical_device_id, virtual_machine_id, container_id, now, now),
    )
    conn.commit()
    return source_id


def test_device_source_owner_id_backfilled_from_physical_device_id(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    is_id = _insert_information_system(conn)
    device_id = _insert_physical_device(conn)
    source_id = _insert_source(conn, is_id, "device", physical_device_id=device_id)
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute("SELECT source_type, owner_id FROM information_system_sources WHERE id=?", (source_id,)).fetchone()
    assert row["source_type"] == "device"
    assert row["owner_id"] == device_id
    conn.close()


def test_vm_source_owner_id_backfilled_from_virtual_machine_id(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    is_id = _insert_information_system(conn)
    vm_id = _insert_virtual_machine(conn)
    source_id = _insert_source(conn, is_id, "vm", virtual_machine_id=vm_id)
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute("SELECT owner_id FROM information_system_sources WHERE id=?", (source_id,)).fetchone()
    assert row["owner_id"] == vm_id
    conn.close()


def test_container_source_owner_id_backfilled_from_container_id(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    is_id = _insert_information_system(conn)
    cont_id = _insert_container(conn)
    source_id = _insert_source(conn, is_id, "container", container_id=cont_id)
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute("SELECT owner_id FROM information_system_sources WHERE id=?", (source_id,)).fetchone()
    assert row["owner_id"] == cont_id
    conn.close()


def test_manual_source_owner_id_stays_null(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    is_id = _insert_information_system(conn)
    source_id = _insert_source(conn, is_id, "manual")
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute("SELECT owner_id FROM information_system_sources WHERE id=?", (source_id,)).fetchone()
    assert row["owner_id"] is None
    conn.close()


def test_old_fk_columns_dropped_and_owner_id_added(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(information_system_sources)").fetchall()}
    assert "owner_id" in cols
    assert "physical_device_id" not in cols
    assert "virtual_machine_id" not in cols
    assert "container_id" not in cols
    conn.close()


def test_real_ddl_after_migration(alembic_config):
    """Пересборка на SQLite не должна терять FK/индексы остальных (не удаляемых) колонок — owner_id
    сознательно БЕЗ FK (см. docstring миграции): единая колонка не может физически ссылаться на три
    разные таблицы, защита от удаления воссоздана вручную в crud/, а не на уровне БД."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    fks = {fk["table"] for fk in conn.execute("PRAGMA foreign_key_list(information_system_sources)").fetchall()}
    assert fks == {"information_systems"}
    indexes = {r["name"] for r in conn.execute("PRAGMA index_list(information_system_sources)").fetchall()}
    assert "ix_information_system_sources_owner_id" in indexes
    assert "ix_information_system_sources_information_system_id" in indexes
    conn.close()


def test_downgrade_is_not_supported(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    with pytest.raises(RuntimeError):
        command.downgrade(cfg, PRE_REVISION)
