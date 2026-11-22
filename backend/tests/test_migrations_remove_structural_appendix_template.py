"""Тесты на миграцию a9e3d4f17b26 — удаление шаблона конструктора «Приложение к структурной схеме (по образцу)».

Удаляется только нетронутая заготовка (вместе с историей версий); отредактированный пользователем шаблон остаётся;
downgrade() возвращает заготовку. Работает на настоящей цепочке миграций (файл SQLite), а не на подмене alembic.op.

Запуск: pytest backend/tests/test_migrations_remove_structural_appendix_template.py -v
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent.parent
PRE_REVISION = "c5d2a8e1f730"
REVISION = "a9e3d4f17b26"
TEMPLATE_NAME = "Приложение к структурной схеме (по образцу)"

pytestmark = pytest.mark.sqlite_only


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    """См. идентичную fixture в test_migrations_interface_sort_order.py."""
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
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _template(conn: sqlite3.Connection, name: str = TEMPLATE_NAME):
    return conn.execute("SELECT * FROM report_templates WHERE name=?", (name,)).fetchone()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_upgrade_removes_untouched_seed_template_with_its_versions(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    with _connect(db_path) as conn:
        seeded = _template(conn)
        assert seeded is not None, "предусловие: b44cd42f9fa0 добавила шаблон"
        conn.execute(
            "INSERT INTO report_template_versions (id, report_template_id, version_number, name, description, format, "
            "config, created_at, updated_at) VALUES (?, ?, 1, ?, NULL, 'docx', ?, ?, ?)",
            (str(uuid.uuid4()), seeded["id"], seeded["name"], seeded["config"], _now(), _now()),
        )

    command.upgrade(cfg, REVISION)

    with _connect(db_path) as conn:
        assert _template(conn) is None
        assert conn.execute("SELECT COUNT(*) FROM report_template_versions").fetchone()[0] == 0


def test_upgrade_keeps_template_edited_by_user(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    edited = json.dumps({"params": [], "blocks": [{"type": "heading", "level": 1, "text": "Мой документ"}]}, ensure_ascii=False)
    with _connect(db_path) as conn:
        conn.execute("UPDATE report_templates SET config=? WHERE name=?", (edited, TEMPLATE_NAME))

    command.upgrade(cfg, REVISION)

    with _connect(db_path) as conn:
        row = _template(conn)
        assert row is not None and json.loads(row["config"])["blocks"][0]["text"] == "Мой документ"


def test_upgrade_keeps_template_with_unreadable_config(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    with _connect(db_path) as conn:
        conn.execute("UPDATE report_templates SET config='{не json' WHERE name=?", (TEMPLATE_NAME,))

    command.upgrade(cfg, REVISION)

    with _connect(db_path) as conn:
        assert _template(conn) is not None


def test_upgrade_does_not_touch_copies_and_other_templates(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    with _connect(db_path) as conn:
        seeded = _template(conn)
        conn.execute(
            "INSERT INTO report_templates (id, name, description, format, config, created_at, updated_at) VALUES (?, ?, NULL, 'docx', ?, ?, ?)",
            (str(uuid.uuid4()), f"{TEMPLATE_NAME} (копия)", seeded["config"], _now(), _now()),
        )
        before = conn.execute("SELECT COUNT(*) FROM report_templates").fetchone()[0]

    command.upgrade(cfg, REVISION)

    with _connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM report_templates").fetchone()[0] == before - 1
        assert _template(conn, f"{TEMPLATE_NAME} (копия)") is not None


def test_upgrade_is_noop_when_template_is_already_gone(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM report_templates WHERE name=?", (TEMPLATE_NAME,))

    command.upgrade(cfg, REVISION)  # не должна падать

    with _connect(db_path) as conn:
        assert _template(conn) is None


def test_downgrade_restores_seed_template_and_is_not_duplicated_on_reupgrade(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, REVISION)
    with _connect(db_path) as conn:
        assert _template(conn) is None

    command.downgrade(cfg, PRE_REVISION)

    from app.services.report_seed_word_template import TEMPLATE_DESCRIPTION, default_structural_appendix_config

    with _connect(db_path) as conn:
        row = _template(conn)
        assert row is not None and row["format"] == "docx" and row["description"] == TEMPLATE_DESCRIPTION
        assert json.loads(row["config"]) == default_structural_appendix_config()

    command.upgrade(cfg, REVISION)
    with _connect(db_path) as conn:
        assert _template(conn) is None


def test_downgrade_does_not_overwrite_existing_template_with_same_name(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, REVISION)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO report_templates (id, name, description, format, config, created_at, updated_at) VALUES (?, ?, "
            "'моё', 'docx', '{\"blocks\": []}', ?, ?)",
            (str(uuid.uuid4()), TEMPLATE_NAME, _now(), _now()),
        )

    command.downgrade(cfg, PRE_REVISION)

    with _connect(db_path) as conn:
        rows = conn.execute("SELECT description FROM report_templates WHERE name=?", (TEMPLATE_NAME,)).fetchall()
        assert [r["description"] for r in rows] == ["моё"]
