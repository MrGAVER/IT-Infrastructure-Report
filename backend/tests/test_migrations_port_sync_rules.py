"""Тесты миграции d4b9e1a7c352 — таблица port_sync_rules (правила согласования данных порта).

Запуск: pytest backend/tests/test_migrations_port_sync_rules.py -v
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent.parent
PRE_REVISION = "c2f8a6d4e917"
TARGET_REVISION = "d4b9e1a7c352"


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    import app.config as app_config

    db_path = tmp_path / "migration_test.db"
    monkeypatch.setattr(app_config, "DATABASE_URL", f"sqlite:///{db_path}")
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False
    return cfg, db_path


def _tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    return names


def test_upgrade_creates_the_table_empty_with_the_same_columns_as_the_model(alembic_config):
    from app.models import PortSyncRule

    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    assert "port_sync_rules" not in _tables(db_path)

    command.upgrade(cfg, TARGET_REVISION)

    conn = sqlite3.connect(str(db_path))
    columns = {row[1]: row for row in conn.execute("PRAGMA table_info(port_sync_rules)").fetchall()}
    assert set(columns) == {c.name for c in PortSyncRule.__table__.columns}
    assert conn.execute("SELECT COUNT(*) FROM port_sync_rules").fetchone()[0] == 0  # стандартные правила добавляет приложение при старте
    # created_at/updated_at в миграциях проекта допускают NULL (как у остальных таблиц), в модели они
    # заполняются приложением — остальные обязательные колонки должны совпадать.
    not_null = {name for name, row in columns.items() if row[3]}
    timestamps = {"created_at", "updated_at"}
    assert {c.name for c in PortSyncRule.__table__.columns if not c.nullable} - timestamps <= not_null
    conn.close()


def test_name_and_code_are_unique_and_defaults_apply(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO port_sync_rules (id, name) VALUES ('1', 'Правило')")
    row = conn.execute("SELECT enabled, priority, action, target_vlans, rel_role, apply_role, vlan_policy FROM port_sync_rules").fetchone()

    assert row == (1, 100, "auto", "any", "any", 0, "keep")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO port_sync_rules (id, name) VALUES ('2', 'Правило')")
    conn.execute("INSERT INTO port_sync_rules (id, name, code) VALUES ('3', 'Другое', 'c')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO port_sync_rules (id, name, code) VALUES ('4', 'Третье', 'c')")
    conn.close()


def test_downgrade_drops_the_table_and_round_trips(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)

    command.downgrade(cfg, PRE_REVISION)
    assert "port_sync_rules" not in _tables(db_path)

    command.upgrade(cfg, "head")
    assert "port_sync_rules" in _tables(db_path)
