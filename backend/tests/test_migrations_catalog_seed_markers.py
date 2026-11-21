"""Миграция e4c8a1d7b350 (catalog_seed_markers).

Главное, что проверяется:
* уже работающая база (есть следы прошлых запусков приложения) получает маркер — иначе удалённые
  администратором стандартные записи вернулись бы ещё раз при первом старте после обновления;
* СВЕЖАЯ база маркера не получает — иначе первый запуск не заведёт стартовые значения. Часть
  справочников на свежей базе непуста уже после миграций (их значения вставляет f2a9c7d1e530), и
  именно поэтому признак «использовалась» опирается только на таблицы, заполняемые приложением;
* downgrade() работает и не теряет данные справочников.

Запуск: pytest backend/tests/test_migrations_catalog_seed_markers.py -v
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
PRE_MARKERS = "d9a4f2c8b516"
MARKERS_REV = "e4c8a1d7b350"
MARKER_NAME = "default_catalogs.v1"


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


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _markers(conn: sqlite3.Connection) -> list[str]:
    return [r["name"] for r in conn.execute("SELECT name FROM catalog_seed_markers").fetchall()]


def test_fresh_database_gets_table_but_no_marker(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, "head")
    conn = _connect(db_path)
    try:
        assert "catalog_seed_markers" in _tables(conn)
        assert _markers(conn) == []  # первый запуск приложения обязан заселить стартовые значения
        # Предпосылка теста: справочники интерфейсов на свежей базе уже непусты — их нельзя
        # использовать как признак «использовалась».
        assert conn.execute("SELECT COUNT(*) FROM interface_speeds").fetchone()[0] > 0
    finally:
        conn.close()


def test_used_database_with_manufacturers_gets_marker(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_MARKERS)
    conn = _connect(db_path)
    conn.execute("INSERT INTO manufacturers (id, name, created_at, updated_at) VALUES (?, 'Cisco', ?, ?)", (_uid(), _now(), _now()))
    conn.commit()
    conn.close()

    command.upgrade(cfg, MARKERS_REV)

    conn = _connect(db_path)
    try:
        assert _markers(conn) == [MARKER_NAME]
    finally:
        conn.close()


def test_used_database_with_only_auth_settings_row_gets_marker(alembic_config):
    """Администратор мог удалить всё из справочников — след запуска остаётся в auth_settings."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_MARKERS)
    conn = _connect(db_path)
    conn.execute("INSERT INTO auth_settings (id, enabled, updated_at) VALUES ('singleton', 0, ?)", (_now(),))
    conn.commit()
    conn.close()

    command.upgrade(cfg, MARKERS_REV)

    conn = _connect(db_path)
    try:
        assert _markers(conn) == [MARKER_NAME]
    finally:
        conn.close()


def test_markers_downgrade_drops_table_and_keeps_catalog_data(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_MARKERS)
    conn = _connect(db_path)
    conn.execute("INSERT INTO manufacturers (id, name, created_at, updated_at) VALUES (?, 'Cisco', ?, ?)", (_uid(), _now(), _now()))
    conn.commit()
    conn.close()
    command.upgrade(cfg, MARKERS_REV)

    command.downgrade(cfg, PRE_MARKERS)

    conn = _connect(db_path)
    try:
        assert "catalog_seed_markers" not in _tables(conn)
        assert conn.execute("SELECT COUNT(*) FROM manufacturers").fetchone()[0] == 1
    finally:
        conn.close()
