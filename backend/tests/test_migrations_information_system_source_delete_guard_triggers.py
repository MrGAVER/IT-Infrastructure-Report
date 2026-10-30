"""Тесты на миграцию 5b1e7c94a2d8 — триггеры БД, запрещающие удалять устройство/ВМ/контейнер,
на который ссылается information_system_sources.owner_id (пятый уровень защиты, см.
services/integrity.py).

Гоняется на одноразовой SQLite БД во временной директории — тот же приём, что и в остальных
test_migrations_*.py. Проверки идут на РЕАЛЬНОМ поведении (прямой SQL DELETE), а не только на
наличии триггеров: пересборка таблицы в любой будущей SQLite-миграции молча удаляет её триггеры,
и только такой тест это ловит.

Запуск: pytest backend/tests/test_migrations_information_system_source_delete_guard_triggers.py -v
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
PRE_REVISION = "944bd490d967"
TARGET_REVISION = "5b1e7c94a2d8"
EXPECTED_TRIGGERS = {
    "trg_is_source_guard_physical_devices",
    "trg_is_source_guard_virtual_machines",
    "trg_is_source_guard_containers",
}


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


def _triggers(conn: sqlite3.Connection) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()}


def _insert_device(conn) -> str:
    dev_id = _uid()
    device_type_id = conn.execute("SELECT id FROM device_types LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO physical_devices (id, device_type_id, serial_number, siem_enabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (dev_id, device_type_id, dev_id[:12], _now(), _now()),
    )
    conn.commit()
    return dev_id


def _status_insert(conn, table: str) -> tuple[str, str]:
    """Колонку status удалила миграция b3f7a2c91d54: на head её нет, на более ранних ревизиях (TARGET_REVISION, откат) она обязательна."""
    if any(row[1] == "status" for row in conn.execute(f"PRAGMA table_info({table})")):
        return ", status", ", 'active'"
    return "", ""


def _insert_vm(conn) -> str:
    vm_id = _uid()
    status_column, status_value = _status_insert(conn, "virtual_machines")
    conn.execute(f"INSERT INTO virtual_machines (id, name{status_column}, created_at, updated_at) VALUES (?, ?{status_value}, ?, ?)", (vm_id, f"VM-{vm_id[:8]}", _now(), _now()))
    conn.commit()
    return vm_id


def _insert_container(conn) -> str:
    cont_id = _uid()
    conn.execute("INSERT INTO containers (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)", (cont_id, f"CT-{cont_id[:8]}", _now(), _now()))
    conn.commit()
    return cont_id


def _insert_is(conn) -> str:
    is_id = _uid()
    status_column, status_value = _status_insert(conn, "information_systems")
    conn.execute(
        f"INSERT INTO information_systems (id, name, type{status_column}, siem_enabled, crypto_protection_enabled, created_at, updated_at) "
        f"VALUES (?, ?, 'ИС'{status_value}, 0, 0, ?, ?)",
        (is_id, f"ИС {is_id[:8]}", _now(), _now()),
    )
    conn.commit()
    return is_id


def _insert_source(conn, is_id: str, source_type: str, owner_id: str | None = None) -> str:
    source_id = _uid()
    conn.execute(
        "INSERT INTO information_system_sources (id, information_system_id, source_type, owner_id, external_interaction, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 0, ?, ?)",
        (source_id, is_id, source_type, owner_id, _now(), _now()),
    )
    conn.commit()
    return source_id


def _exists(conn, table: str, row_id: str) -> bool:
    return conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (row_id,)).fetchone() is not None


@pytest.fixture()
def migrated(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, "head")
    conn = _connect(db_path)
    yield cfg, db_path, conn
    conn.close()


def test_triggers_exist_at_head(migrated):
    """На head, а не на TARGET_REVISION: будущая миграция, пересобравшая одну из защищённых
    таблиц на SQLite, потеряет триггер — и этот тест упадёт."""
    _, _, conn = migrated
    assert EXPECTED_TRIGGERS <= _triggers(conn)


@pytest.mark.parametrize("table,source_type,factory", [
    ("physical_devices", "device", _insert_device),
    ("virtual_machines", "vm", _insert_vm),
    ("containers", "container", _insert_container),
])
def test_raw_delete_of_referenced_owner_is_blocked(migrated, table, source_type, factory):
    _, _, conn = migrated
    owner_id = factory(conn)
    _insert_source(conn, _insert_is(conn), source_type, owner_id)

    with pytest.raises(sqlite3.IntegrityError, match="источник информационной системы"):
        conn.execute(f"DELETE FROM {table} WHERE id=?", (owner_id,))
    conn.rollback()
    assert _exists(conn, table, owner_id)


@pytest.mark.parametrize("table,source_type,factory", [
    ("physical_devices", "device", _insert_device),
    ("virtual_machines", "vm", _insert_vm),
    ("containers", "container", _insert_container),
])
def test_raw_delete_allowed_after_source_removed(migrated, table, source_type, factory):
    _, _, conn = migrated
    owner_id = factory(conn)
    source_id = _insert_source(conn, _insert_is(conn), source_type, owner_id)

    conn.execute("DELETE FROM information_system_sources WHERE id=?", (source_id,))
    conn.execute(f"DELETE FROM {table} WHERE id=?", (owner_id,))
    conn.commit()
    assert not _exists(conn, table, owner_id)


def test_unreferenced_owner_and_manual_source_do_not_block(migrated):
    _, _, conn = migrated
    device_id = _insert_device(conn)
    _insert_source(conn, _insert_is(conn), "manual")
    conn.execute("DELETE FROM physical_devices WHERE id=?", (device_id,))
    conn.commit()
    assert not _exists(conn, "physical_devices", device_id)


def test_source_of_other_type_with_same_id_does_not_block(migrated):
    """Триггер различает владельцев по source_type: источник типа 'vm' с owner_id, случайно
    совпавшим с id устройства, устройство не защищает."""
    _, _, conn = migrated
    device_id = _insert_device(conn)
    _insert_source(conn, _insert_is(conn), "vm", device_id)
    conn.execute("DELETE FROM physical_devices WHERE id=?", (device_id,))
    conn.commit()
    assert not _exists(conn, "physical_devices", device_id)


def test_downgrade_works_and_removes_triggers(alembic_config):
    """Требование проекта: downgrade() обязан работать. Проверяется и сам откат, и его эффект
    (после отката защита снята), и повторный upgrade (миграция обратима туда-обратно)."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    device_id = _insert_device(conn)
    _insert_source(conn, _insert_is(conn), "device", device_id)
    assert EXPECTED_TRIGGERS <= _triggers(conn)
    conn.close()

    command.downgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    assert not (EXPECTED_TRIGGERS & _triggers(conn))
    assert conn.execute("SELECT owner_id FROM information_system_sources").fetchone()["owner_id"] == device_id
    conn.execute("DELETE FROM physical_devices WHERE id=?", (device_id,))
    conn.commit()
    assert not _exists(conn, "physical_devices", device_id)
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    assert EXPECTED_TRIGGERS <= _triggers(conn)
    conn.close()
