"""Тесты миграции c2f8a6d4e917 — индексы журнала аудита под постраничную выборку.

Запуск: pytest backend/tests/test_migrations_audit_log_indexes.py -v
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent.parent
PRE_REVISION = "a7c3e9d15b42"
TARGET_REVISION = "c2f8a6d4e917"
INDEXES = {"ix_audit_log_created_at_id", "ix_audit_log_action", "ix_audit_log_entity_type"}


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    import app.config as app_config

    db_path = tmp_path / "migration_test.db"
    monkeypatch.setattr(app_config, "DATABASE_URL", f"sqlite:///{db_path}")
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False
    return cfg, db_path


def _audit_indexes(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    names = {row[1] for row in conn.execute("PRAGMA index_list(audit_log)").fetchall()}
    conn.close()
    return names & INDEXES


def test_upgrade_creates_the_indexes_and_keeps_existing_entries(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    assert _audit_indexes(db_path) == set()
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO audit_log (id, entity_type, entity_id, action, details, created_at, updated_at) VALUES ('a', 'devices', 'd', 'CREATE', 'x', '2026-01-01', '2026-01-01')")
    conn.commit()
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)

    assert _audit_indexes(db_path) == INDEXES
    conn = sqlite3.connect(str(db_path))
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 1
    conn.close()


def test_downgrade_drops_the_indexes_and_round_trips(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)

    command.downgrade(cfg, PRE_REVISION)
    assert _audit_indexes(db_path) == set()

    command.upgrade(cfg, "head")
    assert _audit_indexes(db_path) == INDEXES
