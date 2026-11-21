"""Тесты миграции a3e7c1d9b406 — автор действия в журнале аудита.

Запуск: pytest backend/tests/test_migrations_audit_log_actor.py -v
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent.parent
PRE_REVISION = "d4b9e1a7c352"
TARGET_REVISION = "a3e7c1d9b406"
ACTOR_COLUMNS = {"actor_id", "actor_username", "actor_ip"}


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    import app.config as app_config

    db_path = tmp_path / "migration_test.db"
    monkeypatch.setattr(app_config, "DATABASE_URL", f"sqlite:///{db_path}")
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False
    return cfg, db_path


def _audit_columns(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    names = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
    conn.close()
    return names


def test_upgrade_adds_nullable_actor_columns_and_keeps_existing_entries(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    assert not ACTOR_COLUMNS & _audit_columns(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO audit_log (id, entity_type, entity_id, action, details, created_at, updated_at) VALUES ('a', 'devices', 'd', 'CREATE', 'x', '2026-01-01', '2026-01-01')")
    conn.commit()
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)

    assert ACTOR_COLUMNS <= _audit_columns(db_path)
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT id, details, actor_id, actor_username, actor_ip FROM audit_log").fetchone()
    conn.close()
    assert row == ("a", "x", None, None, None)  # старая запись цела, автор неизвестен


def test_downgrade_removes_the_columns_and_round_trips(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    command.downgrade(cfg, PRE_REVISION)
    assert not ACTOR_COLUMNS & _audit_columns(db_path)
    command.upgrade(cfg, TARGET_REVISION)
    assert ACTOR_COLUMNS <= _audit_columns(db_path)
