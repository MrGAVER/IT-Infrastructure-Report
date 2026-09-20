"""Тесты на миграцию b7f2c1e5a904 — переработка структуры БД (согласовано с заказчиком, см. отчёт
по анализу от 19.09.2026): information_system_protocols.protocol_catalog_id становится
обязательным, текстовые port/protocol удаляются из open_ports/information_system_protocols,
legacy-таблицы information_system_devices/vms/containers/ips удаляются с переносом ещё не
мигрированных строк в information_system_sources.

Гоняется на одноразовой SQLite БД в /tmp — не трогает приложение и его тестовую БД (тот же приём,
что и в test_migrations_open_ports_catalog.py/test_migrations_diagram.py).

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_migrations_isprotocol_catalog.py -v
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
PRE_REVISION = "811f39a40ec7"  # последняя ревизия до этой миграции (голова до правки)
TARGET_REVISION = "b7f2c1e5a904"


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    """См. идентичную fixture в test_migrations_open_ports_catalog.py — env.py читает
    app.config.DATABASE_URL напрямую, поэтому URL временной БД подставляется через monkeypatch
    атрибута модуля."""
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


def _insert_information_system(conn: sqlite3.Connection, *, name: str | None = None) -> str:
    is_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO information_systems (id, name, type, status, siem_enabled, crypto_protection_enabled, created_at, updated_at) "
        "VALUES (?, ?, 'ИС', 'active', 0, 0, ?, ?)",
        (is_id, name or f"ИС {is_id[:8]}", now, now),
    )
    conn.commit()
    return is_id


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


def _insert_legacy_is_device(conn: sqlite3.Connection, is_id: str, device_id: str, *, role: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO information_system_devices (id, information_system_id, physical_device_id, role, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (_uid(), is_id, device_id, role, now, now),
    )
    conn.commit()


def _insert_legacy_is_ip(conn: sqlite3.Connection, is_id: str, ip_address: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO information_system_ips (id, information_system_id, ip_address, external_interaction, created_at, updated_at) "
        "VALUES (?, ?, ?, 0, ?, ?)",
        (_uid(), is_id, ip_address, now, now),
    )
    conn.commit()


def _insert_information_system_source(conn: sqlite3.Connection, is_id: str, *, source_type: str = "manual", ip_address: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO information_system_sources (id, information_system_id, source_type, ip_address, external_interaction, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 0, ?, ?)",
        (_uid(), is_id, source_type, ip_address, now, now),
    )
    conn.commit()


def _insert_legacy_is_protocol(conn: sqlite3.Connection, is_id: str, *, protocol: str | None, port: int | None) -> str:
    """Строка information_system_protocols без protocol_catalog_id — состояние, возможное до этой
    миграции (protocol_catalog_id было опциональным полем, см. models.py до правки)."""
    protocol_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO information_system_protocols (id, information_system_id, protocol, port, protocol_catalog_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, NULL, ?, ?)",
        (protocol_id, is_id, protocol, port, now, now),
    )
    conn.commit()
    return protocol_id


def test_legacy_is_device_migrated_to_sources_when_no_sources_exist(alembic_config):
    """ИС без единого source-ряда (карточка ни разу не пересохранялась через актуальную форму) —
    legacy-строка information_system_devices переносится в information_system_sources одним шагом."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    is_id = _insert_information_system(conn)
    device_id = _insert_physical_device(conn)
    _insert_legacy_is_device(conn, is_id, device_id, role="Основной сервер")
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT source_type, physical_device_id, role FROM information_system_sources WHERE information_system_id=?",
        (is_id,),
    ).fetchone()
    assert row is not None
    assert row["source_type"] == "device"
    assert row["physical_device_id"] == device_id
    assert row["role"] == "Основной сервер"
    conn.close()


def test_legacy_rows_skipped_when_is_already_has_sources(alembic_config):
    """ИС, у которой уже есть хотя бы один unified-источник — legacy-строки этой ИС НЕ переносятся
    (источники полностью замещают legacy-таблицы для конкретной ИС, а не дополняют их, см.
    docstring миграции), иначе перенос создал бы дубли."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    is_id = _insert_information_system(conn)
    device_id = _insert_physical_device(conn)
    _insert_legacy_is_device(conn, is_id, device_id)
    _insert_information_system_source(conn, is_id, source_type="manual", ip_address="10.0.0.1")
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    rows = conn.execute("SELECT source_type FROM information_system_sources WHERE information_system_id=?", (is_id,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["source_type"] == "manual"
    conn.close()


def test_legacy_is_ip_migrated_to_sources_when_no_sources_exist(alembic_config):
    """Аналог test_legacy_is_device_migrated_to_sources_when_no_sources_exist для
    information_system_ips (source_type='manual')."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    is_id = _insert_information_system(conn)
    _insert_legacy_is_ip(conn, is_id, "192.168.1.10")
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT source_type, ip_address FROM information_system_sources WHERE information_system_id=?", (is_id,)
    ).fetchone()
    assert row is not None
    assert row["source_type"] == "manual"
    assert row["ip_address"] == "192.168.1.10"
    conn.close()


def test_legacy_is_link_tables_are_dropped(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "information_system_devices" not in tables
    assert "information_system_vms" not in tables
    assert "information_system_containers" not in tables
    assert "information_system_ips" not in tables
    conn.close()


def test_is_protocol_backfill_reuses_existing_catalog_entry(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    existing = conn.execute("SELECT id FROM protocol_port_catalogs WHERE port=22 AND protocol_type='SSH'").fetchone()
    assert existing is not None, "22/SSH должен быть в стандартном сидинге — иначе тест ничего не проверяет"
    is_id = _insert_information_system(conn)
    protocol_id = _insert_legacy_is_protocol(conn, is_id, protocol="SSH", port=22)
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute("SELECT protocol_catalog_id FROM information_system_protocols WHERE id=?", (protocol_id,)).fetchone()
    assert row["protocol_catalog_id"] == existing["id"]
    conn.close()


def test_is_protocol_backfill_creates_catalog_entry_for_unknown_combination(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    is_id = _insert_information_system(conn)
    protocol_id = _insert_legacy_is_protocol(conn, is_id, protocol="Внутренний-протокол", port=54321)
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT c.port, c.protocol_type FROM information_system_protocols p "
        "JOIN protocol_port_catalogs c ON p.protocol_catalog_id = c.id WHERE p.id=?",
        (protocol_id,),
    ).fetchone()
    assert row["port"] == 54321
    assert row["protocol_type"] == "Внутренний-протокол"
    conn.close()


def test_is_protocol_without_port_is_dropped(alembic_config):
    """Совсем свободный текст без порта (protocol_catalog_id NULL И port NULL) — привязать было не
    к чему даже в принципе (см. п.1 docstring миграции), строка удаляется, а не блокирует NOT NULL."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    is_id = _insert_information_system(conn)
    protocol_id = _insert_legacy_is_protocol(conn, is_id, protocol="Свободный текст без порта", port=None)
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute("SELECT id FROM information_system_protocols WHERE id=?", (protocol_id,)).fetchone()
    assert row is None
    conn.close()


def test_information_system_protocols_real_ddl_after_migration(alembic_config):
    """NOT NULL/FK/индексы проверяются через PRAGMA table_info по реальному DDL, а не по метаданным
    SQLAlchemy — на SQLite ограничение может молча потеряться при неаккуратной пересборке таблицы
    (тот же принцип, что в test_migrations_open_ports_catalog.py)."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    columns = {r["name"]: r for r in conn.execute("PRAGMA table_info(information_system_protocols)").fetchall()}
    assert columns["protocol_catalog_id"]["notnull"] == 1
    assert "protocol" not in columns
    assert "port" not in columns
    assert "version" not in columns
    assert "direction" not in columns
    fks = conn.execute("PRAGMA foreign_key_list(information_system_protocols)").fetchall()
    assert any(fk["table"] == "protocol_port_catalogs" for fk in fks)
    assert any(fk["table"] == "information_systems" for fk in fks)
    indexes = {r["name"] for r in conn.execute("PRAGMA index_list(information_system_protocols)").fetchall()}
    assert "ix_information_system_protocols_protocol_catalog_id" in indexes
    assert "ix_information_system_protocols_information_system_id" in indexes
    conn.close()


def test_open_ports_port_and_protocol_columns_dropped(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(open_ports)").fetchall()}
    assert "port" not in columns
    assert "protocol" not in columns
    assert "protocol_catalog_id" in columns
    fks = conn.execute("PRAGMA foreign_key_list(open_ports)").fetchall()
    assert any(fk["table"] == "protocol_port_catalogs" for fk in fks)
    indexes = {r["name"] for r in conn.execute("PRAGMA index_list(open_ports)").fetchall()}
    assert "ix_open_ports_protocol_catalog_id" in indexes
    conn.close()


def test_downgrade_is_not_supported(alembic_config):
    """См. docstring миграции: столбцы и таблицы удаляются безвозвратно, откат одной лишь схемы
    создал бы ложное ощущение обратимости (тот же принцип, что в 38e9b2624a53)."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    with pytest.raises(RuntimeError):
        command.downgrade(cfg, PRE_REVISION)
