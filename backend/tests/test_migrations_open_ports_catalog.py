"""Тесты на миграцию a1b7c9d3e502 (open_ports.protocol_catalog_id: backfill + NOT NULL) —
«Возможное улучшение 1» из правки "убрать текстовые поля Порт/Протокол": строки, заведённые до
той правки (или напрямую через ORM в обход API), могли остаться без ссылки на справочник.

Гоняется на одноразовой SQLite БД в /tmp — не трогает приложение и его тестовую БД (тот же приём,
что и в test_migrations_diagram.py).

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_migrations_open_ports_catalog.py -v
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
PRE_REVISION = "1e7441f45639"  # последняя ревизия до этой миграции (open_ports.protocol_catalog_id ещё nullable)
TARGET_REVISION = "a1b7c9d3e502"


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    """См. идентичную fixture в test_migrations_diagram.py — env.py читает app.config.DATABASE_URL
    напрямую, поэтому URL временной БД подставляется через monkeypatch атрибута модуля."""
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


def _insert_legacy_open_port(conn: sqlite3.Connection, *, port: int, protocol: str | None, transport_protocol: str = "TCP") -> str:
    """Строка open_ports без protocol_catalog_id — состояние, возможное до правки "убрать текстовые
    поля Порт/Протокол" (порт/протокол вводились вручную, справочник был опционален)."""
    open_port_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO open_ports (id, owner_type, owner_id, transport_protocol, port, protocol, protocol_catalog_id, created_at, updated_at) VALUES (?, 'virtual_machine', ?, ?, ?, ?, NULL, ?, ?)",
        (open_port_id, _uid(), transport_protocol, port, protocol, now, now),
    )
    conn.commit()
    return open_port_id


def test_backfill_reuses_existing_catalog_entry_when_match_found(alembic_config):
    """22/SSH уже засеян по умолчанию (PROTOCOL_DEFAULTS, см. app/services/catalogs.py) — миграция
    должна ПЕРЕИСПОЛЬЗОВАТЬ существующую запись, а не плодить дубликат с тем же (port, protocol_type)
    в обход uq_protocol_port_catalog_port_type."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    existing = conn.execute("SELECT id FROM protocol_port_catalogs WHERE port=22 AND protocol_type='SSH'").fetchone()
    assert existing is not None, "22/SSH должен быть в стандартном сидинге — иначе тест ничего не проверяет"
    open_port_id = _insert_legacy_open_port(conn, port=22, protocol="SSH")
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute("SELECT protocol_catalog_id FROM open_ports WHERE id=?", (open_port_id,)).fetchone()
    assert row["protocol_catalog_id"] == existing["id"]
    dupes = conn.execute("SELECT count(*) FROM protocol_port_catalogs WHERE port=22 AND protocol_type='SSH'").fetchone()[0]
    assert dupes == 1
    conn.close()


def test_backfill_creates_catalog_entry_for_unknown_combination(alembic_config):
    """Порт/протокол, которого ещё нет в справочнике (нестандартная комбинация) — миграция заводит
    для него новую запись, а не теряет данные и не падает."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    open_port_id = _insert_legacy_open_port(conn, port=54321, protocol="Кастомный-протокол")
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT c.port, c.protocol_type FROM open_ports o JOIN protocol_port_catalogs c ON o.protocol_catalog_id = c.id WHERE o.id=?",
        (open_port_id,),
    ).fetchone()
    assert row["port"] == 54321
    assert row["protocol_type"] == "Кастомный-протокол"
    conn.close()


def test_backfill_falls_back_to_transport_protocol_when_protocol_missing(alembic_config):
    """protocol было опциональным (Mapped[Optional[str]]) — строка могла иметь только порт и
    транспортный протокол, вообще без прикладного. COALESCE(protocol, transport_protocol) —
    тот же fallback-порядок, что использовала 8c5d1f7a2b40 при первом заведении колонки."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    open_port_id = _insert_legacy_open_port(conn, port=9999, protocol=None, transport_protocol="UDP")
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT c.protocol_type FROM open_ports o JOIN protocol_port_catalogs c ON o.protocol_catalog_id = c.id WHERE o.id=?",
        (open_port_id,),
    ).fetchone()
    assert row["protocol_type"] == "UDP"
    conn.close()


def test_protocol_catalog_id_is_not_null_in_real_ddl(alembic_config):
    """Раздел 13 ТЗ (тот же принцип, что test_migrations_diagram.py): NOT NULL проверяется через
    PRAGMA table_info по реальному DDL, а не по метаданным SQLAlchemy — на SQLite ограничение
    может молча потеряться при неаккуратном batch_alter_table."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    columns = {r["name"]: r for r in conn.execute("PRAGMA table_info(open_ports)").fetchall()}
    assert columns["protocol_catalog_id"]["notnull"] == 1
    # FK и индекс, существовавшие до пересборки таблицы, должны пережить её (см. docstring миграции).
    fks = conn.execute("PRAGMA foreign_key_list(open_ports)").fetchall()
    assert any(fk["table"] == "protocol_port_catalogs" for fk in fks)
    indexes = {r["name"] for r in conn.execute("PRAGMA index_list(open_ports)").fetchall()}
    assert "ix_open_ports_protocol_catalog_id" in indexes
    conn.close()


def test_upgrade_downgrade_upgrade_cycle_preserves_data(alembic_config):
    """Откат возвращает колонку в nullable (не падает и не требует особого состояния БД), повторный
    upgrade снова делает её NOT NULL — данные (сама ссылка на справочник) не теряются на этом пути,
    т.к. downgrade намеренно не обнуляет уже заполненные protocol_catalog_id (см. docstring миграции)."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    open_port_id = _insert_legacy_open_port(conn, port=443, protocol="HTTPS")
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    catalog_id = conn.execute("SELECT protocol_catalog_id FROM open_ports WHERE id=?", (open_port_id,)).fetchone()[0]
    assert catalog_id is not None
    conn.close()

    command.downgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    columns = {r["name"]: r for r in conn.execute("PRAGMA table_info(open_ports)").fetchall()}
    assert columns["protocol_catalog_id"]["notnull"] == 0
    assert conn.execute("SELECT protocol_catalog_id FROM open_ports WHERE id=?", (open_port_id,)).fetchone()[0] == catalog_id
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    columns = {r["name"]: r for r in conn.execute("PRAGMA table_info(open_ports)").fetchall()}
    assert columns["protocol_catalog_id"]["notnull"] == 1
    conn.close()
