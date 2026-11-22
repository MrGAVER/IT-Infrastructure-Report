"""A-03: серийный номер физического устройства не уникален (миграция b3f7a1d95c24).

Серийные номера разных производителей совпадают, поэтому глобальная уникальность была ошибкой модели. Раньше поведение
зависело от СУБД: PostgreSQL и схема из `create_all` (тесты) не пускали дубль (409 INTEGRITY_ERROR с общим текстом), а в
SQLite из миграций ограничение потерялось случайно на e8c2f1a9b430. Здесь проверяются модель, API (на схеме из `create_all` и на схеме из
миграций SQLite), миграция на SQLite (цепочка и сама функция upgrade на схемах, где ограничение есть) и — отдельным блоком, только на
PostgreSQL — снятие
реального ограничения `physical_devices_serial_number_key`. Проверок дублей и составного ограничения нет сознательно.

Запуск: pytest backend/tests/test_serial_number_not_unique.py -v
PostgreSQL-часть: INFRA_REGISTRY_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/infra_test pytest
backend/tests/test_serial_number_not_unique.py
"""

from __future__ import annotations

import importlib.util
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

BACKEND_DIR = Path(__file__).resolve().parent.parent
PREVIOUS_HEAD = "a9e3d4f17b26"
MIGRATION_REV = "b3f7a1d95c24"
MIGRATION_FILE = BACKEND_DIR / "alembic" / "versions" / "b3f7a1d95c24_serial_number_not_unique.py"
SERIAL = "SN-DUPLICATE-1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_migration():
    """Модуль миграции загружается по пути: файлы ревизий не лежат в пакете, и alembic импортирует их сам."""
    spec = importlib.util.spec_from_file_location("serial_number_not_unique_migration", MIGRATION_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade(engine) -> None:
    """Выполняет upgrade() миграции на произвольной схеме — так проверяются ветки, которых нет в цепочке SQLite."""
    module = _load_migration()
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()


# ---------------------------------------------------------------------------------------------------------------------
# Модель и API
# ---------------------------------------------------------------------------------------------------------------------
def test_model_column_is_not_unique():
    from app.models import PhysicalDevice

    table = PhysicalDevice.__table__
    column = table.c.serial_number
    assert not column.unique
    assert not column.nullable, "NOT NULL сохраняется: серийный номер по-прежнему обязателен"
    unique_on_serial = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint) and [c.name for c in constraint.columns] == ["serial_number"]
    ]
    assert not unique_on_serial
    assert not [index for index in table.indexes if index.unique and [c.name for c in index.columns] == ["serial_number"]]


def _device_type(client, name: str) -> str:
    categories = client.get("/api/v1/resources/device-categories").json()["items"]
    r = client.post("/api/v1/resources/device-types", json={"name": name, "category_id": categories[0]["id"]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_two_devices_with_the_same_serial_number_are_accepted(client):
    """Разные производители — один и тот же номер. Обе записи создаются, никакого 409 и предупреждений о дубле."""
    device_type = _device_type(client, "Тип A-03: дубли серийных номеров")
    first_vendor = client.post("/api/v1/resources/manufacturers", json={"name": "Производитель А"}).json()["id"]
    second_vendor = client.post("/api/v1/resources/manufacturers", json={"name": "Производитель Б"}).json()["id"]

    first = client.post(
        "/api/v1/resources/devices", json={"device_type_id": device_type, "manufacturer_id": first_vendor, "serial_number": SERIAL}
    )
    second = client.post(
        "/api/v1/resources/devices", json={"device_type_id": device_type, "manufacturer_id": second_vendor, "serial_number": SERIAL}
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] != second.json()["id"]
    listing = client.get("/api/v1/resources/devices").json()["items"]
    assert [d["serial_number"] for d in listing].count(SERIAL) == 2


def test_serial_number_is_still_required(client):
    device_type = _device_type(client, "Тип A-03: обязательный номер")
    r = client.post("/api/v1/resources/devices", json={"device_type_id": device_type})
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------------------------------------------------
# Миграция на SQLite
# ---------------------------------------------------------------------------------------------------------------------
@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    import app.config as app_config

    db_path = tmp_path / "serial_number_migration.db"
    monkeypatch.setattr(app_config, "DATABASE_URL", f"sqlite:///{db_path}")
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False
    return cfg, db_path


def _insert_device(conn: sqlite3.Connection, serial: str) -> None:
    conn.execute(
        "INSERT INTO physical_devices (id, device_type_id, serial_number, siem_enabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (str(uuid.uuid4()), str(uuid.uuid4()), serial, _now(), _now()),
    )


@pytest.mark.sqlite_only
class TestSqliteChain:
    def test_the_new_revision_is_in_the_single_chain(self, alembic_config):
        """Ревизия входит в цепочку единственного head (позже на неё могут лечь другие миграции, например A-14)."""
        from alembic.script import ScriptDirectory

        cfg, _ = alembic_config
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        assert len(heads) == 1
        assert MIGRATION_REV in {revision.revision for revision in script.iterate_revisions(heads[0], "base")}

    def test_schema_from_migrations_accepts_duplicates(self, alembic_config):
        cfg, db_path = alembic_config
        command.upgrade(cfg, "head")
        conn = sqlite3.connect(str(db_path))
        try:
            _insert_device(conn, SERIAL)
            _insert_device(conn, SERIAL)  # FK в «сыром» соединении SQLite не проверяются — важна только уникальность
            conn.commit()
            assert conn.execute("SELECT COUNT(*) FROM physical_devices WHERE serial_number = ?", (SERIAL,)).fetchone()[0] == 2
        finally:
            conn.close()

    def test_upgrade_is_idempotent_and_downgrade_does_not_fail(self, alembic_config):
        cfg, db_path = alembic_config
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")  # повторный запуск — без изменений
        command.downgrade(cfg, PREVIOUS_HEAD)  # намеренный no-op, но не ошибка
        conn = sqlite3.connect(str(db_path))
        try:
            assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == PREVIOUS_HEAD
        finally:
            conn.close()
        command.upgrade(cfg, MIGRATION_REV)  # именно эта ревизия: поверх неё могут лежать более поздние миграции
        conn = sqlite3.connect(str(db_path))
        try:
            assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == MIGRATION_REV
            _insert_device(conn, SERIAL)
            _insert_device(conn, SERIAL)
            conn.commit()
        finally:
            conn.close()


@pytest.mark.sqlite_only
def test_api_accepts_duplicate_serial_number_on_schema_built_by_migrations(alembic_config, monkeypatch):
    """Критерий задания: и на схеме из `alembic upgrade head`, и на схеме из `create_all` два POST с одним номером дают 201.
    Приложение здесь работает на файловой SQLite-базе, собранной цепочкой миграций, а не на in-memory базе из моделей."""
    from fastapi.testclient import TestClient
    from sqlalchemy import event
    from sqlalchemy.orm import sessionmaker

    from app import db as app_db
    from app import main as app_main
    from app.db import configure_sqlite_connection, get_db

    cfg, db_path = alembic_config
    command.upgrade(cfg, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    event.listen(engine, "connect", lambda dbapi_connection, _record: configure_sqlite_connection(dbapi_connection))
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(app_main, "SessionLocal", factory)
    monkeypatch.setattr(app_db, "SessionLocal", factory)

    def _get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app_main.app.dependency_overrides[get_db] = _get_db
    try:
        with TestClient(app_main.app, client=("127.0.0.1", 50000)) as client:
            device_type = _device_type(client, "Тип A-03: схема из миграций")
            first_vendor = client.post("/api/v1/resources/manufacturers", json={"name": "Производитель М1"}).json()["id"]
            second_vendor = client.post("/api/v1/resources/manufacturers", json={"name": "Производитель М2"}).json()["id"]
            first = client.post(
                "/api/v1/resources/devices", json={"device_type_id": device_type, "manufacturer_id": first_vendor, "serial_number": SERIAL}
            )
            second = client.post(
                "/api/v1/resources/devices", json={"device_type_id": device_type, "manufacturer_id": second_vendor, "serial_number": SERIAL}
            )
            assert first.status_code == 201, first.text
            assert second.status_code == 201, second.text
    finally:
        app_main.app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _scratch_engine(tmp_path, ddl: list[str]):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'scratch.db'}", future=True)
    with engine.begin() as connection:
        for statement in ddl:
            connection.exec_driver_sql(statement)
    return engine


def _has_unique_on_serial(engine) -> bool:
    inspector = sa.inspect(engine)
    constraints = [c for c in inspector.get_unique_constraints("physical_devices") if c["column_names"] == ["serial_number"]]
    indexes = [i for i in inspector.get_indexes("physical_devices") if i.get("unique") and i["column_names"] == ["serial_number"]]
    return bool(constraints or indexes)


@pytest.mark.sqlite_only
class TestUpgradeFunctionOnSchemasWithTheConstraint:
    """В цепочке миграций SQLite ограничения уже нет, поэтому ветки «снять ограничение/индекс» проверяются на самодельных схемах."""

    def test_named_unique_constraint_is_dropped_and_other_constraints_stay(self, tmp_path):
        engine = _scratch_engine(
            tmp_path,
            [
                "CREATE TABLE physical_devices (id VARCHAR(36) PRIMARY KEY, serial_number VARCHAR(255) NOT NULL, system_name "
                "VARCHAR(255), CONSTRAINT uq_serial UNIQUE (serial_number), CONSTRAINT uq_system UNIQUE (system_name))",
            ],
        )
        assert _has_unique_on_serial(engine)

        _run_upgrade(engine)

        assert not _has_unique_on_serial(engine)
        remaining = [c["column_names"] for c in sa.inspect(engine).get_unique_constraints("physical_devices")]
        assert ["system_name"] in remaining, "ограничения других колонок не трогаются"
        with engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO physical_devices (id, serial_number) VALUES ('1', 'X'), ('2', 'X')")
        engine.dispose()

    def test_standalone_unique_index_is_dropped(self, tmp_path):
        engine = _scratch_engine(
            tmp_path,
            [
                "CREATE TABLE physical_devices (id VARCHAR(36) PRIMARY KEY, serial_number VARCHAR(255) NOT NULL, rack_id VARCHAR(36))",
                "CREATE UNIQUE INDEX ix_physical_devices_serial_number ON physical_devices (serial_number)",
                "CREATE UNIQUE INDEX uq_device_rack_slot ON physical_devices (rack_id) WHERE rack_id IS NOT NULL",
            ],
        )
        assert _has_unique_on_serial(engine)

        _run_upgrade(engine)

        assert not _has_unique_on_serial(engine)
        index_names = {i["name"] for i in sa.inspect(engine).get_indexes("physical_devices")}
        assert "uq_device_rack_slot" in index_names, "уникальный индекс по другой колонке не трогаем"
        engine.dispose()

    def test_schema_without_the_constraint_is_left_alone(self, tmp_path):
        engine = _scratch_engine(
            tmp_path, ["CREATE TABLE physical_devices (id VARCHAR(36) PRIMARY KEY, serial_number VARCHAR(255) NOT NULL)"]
        )
        _run_upgrade(engine)
        _run_upgrade(engine)  # повторно — тоже без ошибок
        assert not _has_unique_on_serial(engine)
        engine.dispose()


# ---------------------------------------------------------------------------------------------------------------------
# PostgreSQL: реальное ограничение physical_devices_serial_number_key
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.postgres_only
class TestPostgresConstraint:
    def _unique_on_serial(self, database) -> list[str]:
        inspector = sa.inspect(database.engine)
        names = [c["name"] for c in inspector.get_unique_constraints("physical_devices") if c["column_names"] == ["serial_number"]]
        names += [
            i["name"] for i in inspector.get_indexes("physical_devices") if i.get("unique") and i["column_names"] == ["serial_number"]
        ]
        return names

    def test_constraint_exists_before_and_is_dropped_by_the_migration(self):
        from migration_support import insert_row as _insert
        from test_migrations_postgres import ScratchDatabase

        database = ScratchDatabase()
        try:
            database.upgrade(PREVIOUS_HEAD)
            assert self._unique_on_serial(database), "до миграции PostgreSQL хранит ограничение (batch_alter_table таблицу не пересобирает)"

            database.upgrade("head")
            assert self._unique_on_serial(database) == []

            with database.engine.begin() as connection:
                _insert(connection, "physical_devices", serial_number=SERIAL)
                _insert(connection, "physical_devices", serial_number=SERIAL)
                count = connection.execute(
                    sa.text("SELECT COUNT(*) FROM physical_devices WHERE serial_number = :s"), {"s": SERIAL}
                ).scalar()
            assert count == 2

            # другие ограничения таблицы на месте: частичный уникальный индекс слота стойки
            index_names = {i["name"] for i in sa.inspect(database.engine).get_indexes("physical_devices")}
            assert "uq_device_rack_slot" in index_names
        finally:
            database.close()

    def test_second_upgrade_and_downgrade_do_not_fail(self):
        from test_migrations_postgres import ScratchDatabase

        database = ScratchDatabase()
        try:
            database.upgrade("head")
            database.upgrade("head")
            import app.config as app_config

            original = app_config.DATABASE_URL
            app_config.DATABASE_URL = database.url
            try:
                from test_migrations_postgres import _config

                command.downgrade(_config(), PREVIOUS_HEAD)
            finally:
                app_config.DATABASE_URL = original
            assert self._unique_on_serial(database) == [], "downgrade не возвращает глобальную уникальность"
            database.upgrade("head")
            assert self._unique_on_serial(database) == []
        finally:
            database.close()
