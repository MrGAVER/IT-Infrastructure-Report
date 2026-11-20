"""Тесты на миграцию c8d15d8bc6b4 (item 5 правки "диаграмма топологии сети") — 'Коммутатор L2' и
'Коммутатор L3' раньше указывали на одну категорию 'Коммутаторы' (одинаковый значок на диаграмме),
'Маршрутизатор' — прямо на 'Сетевая инфраструктура' (общий generic-значок с Wi-Fi/GSM/радиомостом).

Гоняется на одноразовой SQLite БД в /tmp — тот же приём, что и в test_migrations_open_ports_catalog.py.

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_migrations_device_categories.py -v
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
PRE_REVISION = "ceb6ca304157"  # последняя ревизия до этой миграции
TARGET_REVISION = "c8d15d8bc6b4"


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


def _insert_legacy_device_type(conn: sqlite3.Connection, *, name: str, category_name: str) -> str:
    """Тип устройства, заведённый ДО этой правки — 'Коммутатор L2'/'Коммутатор L3' на общей
    категории 'Коммутаторы', 'Маршрутизатор' — прямо на 'Сетевая инфраструктура' (см. старую
    DEVICE_TYPE_CATEGORY в services/catalogs.py, до этой правки)."""
    category_id = conn.execute("SELECT id FROM device_categories WHERE name=?", (category_name,)).fetchone()["id"]
    device_type_id = _uid()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO device_types (id, name, category_id, allows_vm_hosting, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (device_type_id, name, category_id, now, now),
    )
    conn.commit()
    return device_type_id


def test_repoints_existing_switch_and_router_device_types_to_new_categories(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    l2_id = _insert_legacy_device_type(conn, name="Коммутатор L2", category_name="Коммутаторы")
    l3_id = _insert_legacy_device_type(conn, name="Коммутатор L3", category_name="Коммутаторы")
    router_id = _insert_legacy_device_type(conn, name="Маршрутизатор", category_name="Сетевая инфраструктура")
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    for device_type_id, expected_category, expected_shape in [
        (l2_id, "Коммутаторы L2", "switch_l2"),
        (l3_id, "Коммутаторы L3", "switch_l3"),
        (router_id, "Маршрутизаторы", "router"),
    ]:
        row = conn.execute(
            "SELECT dc.name AS category_name, dc.diagram_shape FROM device_types dt JOIN device_categories dc ON dt.category_id = dc.id WHERE dt.id = ?",
            (device_type_id,),
        ).fetchone()
        assert row["category_name"] == expected_category
        assert row["diagram_shape"] == expected_shape
    conn.close()


def test_new_categories_are_children_of_correct_parents(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    conn = _connect(db_path)
    switches_parent_id = conn.execute("SELECT id FROM device_categories WHERE name='Коммутаторы'").fetchone()["id"]
    network_parent_id = conn.execute("SELECT id FROM device_categories WHERE name='Сетевая инфраструктура'").fetchone()["id"]

    l2 = conn.execute("SELECT parent_id FROM device_categories WHERE name='Коммутаторы L2'").fetchone()
    l3 = conn.execute("SELECT parent_id FROM device_categories WHERE name='Коммутаторы L3'").fetchone()
    router = conn.execute("SELECT parent_id FROM device_categories WHERE name='Маршрутизаторы'").fetchone()
    assert l2["parent_id"] == switches_parent_id
    assert l3["parent_id"] == switches_parent_id
    assert router["parent_id"] == network_parent_id
    conn.close()


def test_migration_is_idempotent_when_new_categories_already_exist(alembic_config):
    """Повторный прогон (напр. downgrade + upgrade) не должен плодить дубликаты категорий."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)
    command.downgrade(cfg, PRE_REVISION)
    command.upgrade(cfg, TARGET_REVISION)

    conn = _connect(db_path)
    for name in ["Коммутаторы L2", "Коммутаторы L3", "Маршрутизаторы"]:
        count = conn.execute("SELECT COUNT(*) FROM device_categories WHERE name=?", (name,)).fetchone()[0]
        assert count == 1, f"{name}: ожидалась ровно 1 запись, найдено {count}"
    conn.close()


def test_downgrade_restores_old_category_assignment(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    l2_id = _insert_legacy_device_type(conn, name="Коммутатор L2", category_name="Коммутаторы")
    conn.close()

    command.upgrade(cfg, TARGET_REVISION)
    command.downgrade(cfg, PRE_REVISION)

    conn = _connect(db_path)
    row = conn.execute(
        "SELECT dc.name FROM device_types dt JOIN device_categories dc ON dt.category_id = dc.id WHERE dt.id = ?",
        (l2_id,),
    ).fetchone()
    assert row["name"] == "Коммутаторы"
    assert conn.execute("SELECT COUNT(*) FROM device_categories WHERE name='Коммутаторы L2'").fetchone()[0] == 0
    conn.close()


def test_fresh_database_migration_does_not_crash_before_app_seeds_device_types(alembic_config):
    """На полностью свежей базе (только что накатанные миграции, приложение ещё ни разу не
    стартовало) device_categories уже засеяны более ранней миграцией, но 'Коммутатор L2' и т.п.
    как device_types появляются только из services/catalogs.py:seed_defaults() при первом
    старте приложения — на момент этой миграции их ещё нет. Миграция не должна на этом падать."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, TARGET_REVISION)  # не должно бросить исключение
    conn = _connect(db_path)
    for name in ["Коммутаторы L2", "Коммутаторы L3", "Маршрутизаторы"]:
        assert conn.execute("SELECT COUNT(*) FROM device_categories WHERE name=?", (name,)).fetchone()[0] == 1
    conn.close()
