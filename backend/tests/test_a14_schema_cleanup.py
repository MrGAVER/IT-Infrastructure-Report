"""A-14, части 2 и 3: NOT NULL у двух внешних ключей и удаление устаревших колонок/таблицы (миграции d7a3f1c8b254, e9b4c2a7d136).

Часть 2 — `connections.connection_type_id` и `device_models.device_type_id` становятся обязательными (в моделях они такие и были).
Часть 3 — удаляются `physical_devices.os_name/os_version`, `virtual_machines.os_name/os_version/virtualization_platform_id` и
таблица `virtualization_platforms` (данные перенесены в каталог операционных систем миграцией c4e8a7d91b20).

Что проверяется на данных (а не на пустой базе, где ветки миграций не выполняются):
  • предпроверки: при NULL-строках и при данных, которым нет замены, миграция падает ДО изменений и схема остаётся прежней;
  • после миграции: колонки обязательны / удалены, остальные данные, внешние ключи, уникальные ограничения и индексы на месте;
  • SQLite: триггер защиты `trg_is_source_guard_virtual_machines` пережил пересборку `virtual_machines` и работает;
  • downgrade возвращает пустые объекты, повторный upgrade проходит.

Запуск: pytest tests/test_a14_schema_cleanup.py
PostgreSQL: INFRA_REGISTRY_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/любая_база pytest tests/test_a14_schema_cleanup.py
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command

import app.config as app_config
from test_migrations_match_models import _alembic_config
from migration_support import insert_row as _insert
from test_migrations_postgres import ScratchDatabase

BEFORE = "c5d2e8a4b713"  # индексы внешних ключей (до A-14 ч.2)
NOT_NULL = "d7a3f1c8b254"  # A-14 ч.2
CLEANUP = "e9b4c2a7d136"  # A-14 ч.3

LEGACY = {
    "physical_devices": {"os_name", "os_version"},
    "virtual_machines": {"os_name", "os_version", "virtualization_platform_id"},
}


class SqliteDatabase:
    """Файловая база SQLite с тем же интерфейсом, что и ScratchDatabase."""

    def __init__(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.path = Path(self._directory.name) / "a14.db"
        self.url = f"sqlite:///{self.path}"
        self.engine = sa.create_engine(self.url, future=True)

    def _run(self, action, revision: str) -> None:
        original = app_config.DATABASE_URL
        app_config.DATABASE_URL = self.url
        try:
            action(_alembic_config(), revision)
        finally:
            app_config.DATABASE_URL = original

    def upgrade(self, revision: str = "head") -> None:
        self._run(command.upgrade, revision)

    def downgrade(self, revision: str) -> None:
        self._run(command.downgrade, revision)

    def close(self) -> None:
        self.engine.dispose()
        self._directory.cleanup()


def _downgrade(database, revision: str) -> None:
    if isinstance(database, SqliteDatabase):
        database.downgrade(revision)
        return
    original = app_config.DATABASE_URL
    app_config.DATABASE_URL = database.url
    try:
        command.downgrade(_alembic_config(), revision)
    finally:
        app_config.DATABASE_URL = original


@pytest.fixture(params=[pytest.param("sqlite", marks=pytest.mark.sqlite_only), pytest.param("postgres", marks=pytest.mark.postgres_only)])
def database(request):
    db = SqliteDatabase() if request.param == "sqlite" else ScratchDatabase()
    try:
        yield db
    finally:
        db.close()


def _columns(database, table: str) -> dict:
    return {column["name"]: column for column in sa.inspect(database.engine).get_columns(table)}


def _revision(database) -> str:
    with database.engine.connect() as connection:
        return connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()


def _sqlite_only(database) -> None:
    if not isinstance(database, SqliteDatabase):
        pytest.skip("проверка относится к SQLite")


# ---------------------------------------------------------------------------------------------------------------------
# Часть 2: NOT NULL
# ---------------------------------------------------------------------------------------------------------------------
class TestNotNullTypeForeignKeys:
    def _rows(self, database, *, with_type: bool) -> dict:
        with database.engine.begin() as connection:
            vendor = _insert(connection, "manufacturers")
            device_type = _insert(connection, "device_types")
            model = _insert(connection, "device_models", manufacturer_id=vendor, device_type_id=device_type if with_type else None)
            device = _insert(connection, "physical_devices", model_id=model, device_type_id=device_type)
            connection_type = _insert(connection, "connection_types")
            link = _insert(connection, "connections", connection_type_id=connection_type if with_type else None)
        return {"vendor": vendor, "device_type": device_type, "model": model, "device": device, "connection_type": connection_type, "link": link}

    def test_null_rows_stop_the_migration_before_any_change(self, database):
        database.upgrade(BEFORE)
        self._rows(database, with_type=False)

        with pytest.raises(RuntimeError) as error:
            database.upgrade(NOT_NULL)

        message = str(error.value)
        assert "connections.connection_type_id: 1" in message and "device_models.device_type_id: 1" in message
        assert _revision(database) == BEFORE
        assert _columns(database, "connections")["connection_type_id"]["nullable"]
        assert _columns(database, "device_models")["device_type_id"]["nullable"]
        with database.engine.connect() as connection:
            assert connection.execute(sa.text("SELECT COUNT(*) FROM connections")).scalar() == 1

    def test_columns_become_required_and_everything_else_survives(self, database):
        database.upgrade(BEFORE)
        ids = self._rows(database, with_type=True)
        inspector = sa.inspect(database.engine)
        before = {
            table: (
                sorted((tuple(fk["constrained_columns"]), fk["referred_table"]) for fk in inspector.get_foreign_keys(table)),
                sorted(index["name"] for index in inspector.get_indexes(table)),
                sorted(tuple(uc["column_names"]) for uc in inspector.get_unique_constraints(table)),
            )
            for table in ("connections", "device_models")
        }

        database.upgrade(NOT_NULL)

        assert not _columns(database, "connections")["connection_type_id"]["nullable"]
        assert not _columns(database, "device_models")["device_type_id"]["nullable"]
        inspector = sa.inspect(database.engine)
        after = {
            table: (
                sorted((tuple(fk["constrained_columns"]), fk["referred_table"]) for fk in inspector.get_foreign_keys(table)),
                sorted(index["name"] for index in inspector.get_indexes(table)),
                sorted(tuple(uc["column_names"]) for uc in inspector.get_unique_constraints(table)),
            )
            for table in ("connections", "device_models")
        }
        assert after == before
        with database.engine.connect() as connection:
            assert connection.execute(sa.text("SELECT device_type_id FROM device_models WHERE id = :id"), {"id": ids["model"]}).scalar() == ids["device_type"]
            assert connection.execute(sa.text("SELECT connection_type_id FROM connections WHERE id = :id"), {"id": ids["link"]}).scalar() == ids["connection_type"]
            assert connection.execute(sa.text("SELECT model_id FROM physical_devices WHERE id = :id"), {"id": ids["device"]}).scalar() == ids["model"]

    def test_null_is_rejected_after_the_migration_and_downgrade_relaxes_it(self, database):
        database.upgrade(NOT_NULL)
        with pytest.raises(sa.exc.IntegrityError), database.engine.begin() as connection:
            _insert(connection, "connections", connection_type_id=None)

        _downgrade(database, BEFORE)
        assert _columns(database, "connections")["connection_type_id"]["nullable"]
        assert _columns(database, "device_models")["device_type_id"]["nullable"]
        database.upgrade(NOT_NULL)  # повторный upgrade проходит
        assert not _columns(database, "connections")["connection_type_id"]["nullable"]


# ---------------------------------------------------------------------------------------------------------------------
# Часть 3: устаревшие колонки и таблица
# ---------------------------------------------------------------------------------------------------------------------
def _legacy_rows(database, *, migrated: bool = True) -> dict:
    """Строки старой схемы. `migrated=True` — значения уже скопированы в каталог (как сделал c4e8a7d91b20)."""
    with database.engine.begin() as connection:
        category = _insert(connection, "operating_system_categories")
        guest_os = _insert(connection, "operating_systems", category_id=category, name="Debian", version="12")
        hypervisor_os = _insert(connection, "operating_systems", category_id=category, name="KVM", version="8")
        platform = _insert(connection, "virtualization_platforms", name="KVM", version="8")
        device = _insert(
            connection, "physical_devices", os_name="Debian", os_version="12", operating_system_id=guest_os if migrated else None,
            serial_number="SN-1", rack_position=None,
        )
        vm = _insert(
            connection, "virtual_machines", name="vm-a14", os_name="Debian", os_version="12", virtualization_platform_id=platform,
            operating_system_id=guest_os if migrated else None, hypervisor_os_id=hypervisor_os if migrated else None,
            physical_device_id=device,
        )
    return {"guest_os": guest_os, "hypervisor_os": hypervisor_os, "platform": platform, "device": device, "vm": vm}


def _snapshot(database, table: str) -> dict:
    inspector = sa.inspect(database.engine)
    return {
        "columns": sorted(c["name"] for c in inspector.get_columns(table)),
        "foreign_keys": sorted((tuple(fk["constrained_columns"]), fk["referred_table"]) for fk in inspector.get_foreign_keys(table)),
        "indexes": sorted(index["name"] for index in inspector.get_indexes(table)),
        "unique": sorted(tuple(uc["column_names"]) for uc in inspector.get_unique_constraints(table)),
    }


class TestDropLegacyOsAndPlatformObjects:
    def test_legacy_objects_are_removed_and_other_data_survives(self, database):
        database.upgrade(NOT_NULL)
        ids = _legacy_rows(database)
        before = {table: _snapshot(database, table) for table in LEGACY}

        database.upgrade(CLEANUP)

        inspector = sa.inspect(database.engine)
        assert "virtualization_platforms" not in inspector.get_table_names()
        for table, legacy in LEGACY.items():
            after = _snapshot(database, table)
            assert not legacy & set(after["columns"]), table
            # Всё, кроме удалённого, осталось: остальные колонки, индексы, уникальные ограничения, внешние ключи.
            assert after["columns"] == sorted(set(before[table]["columns"]) - legacy)
            assert after["indexes"] == before[table]["indexes"]
            assert after["unique"] == before[table]["unique"]
            assert after["foreign_keys"] == [fk for fk in before[table]["foreign_keys"] if fk[1] != "virtualization_platforms"]
        with database.engine.connect() as connection:
            vm = connection.execute(sa.text("SELECT name, physical_device_id, operating_system_id, hypervisor_os_id FROM virtual_machines WHERE id = :id"), {"id": ids["vm"]}).one()
            assert tuple(vm) == ("vm-a14", ids["device"], ids["guest_os"], ids["hypervisor_os"])
            assert connection.execute(sa.text("SELECT operating_system_id FROM physical_devices WHERE id = :id"), {"id": ids["device"]}).scalar() == ids["guest_os"]

    @pytest.mark.parametrize(
        "fixture, expected",
        [
            ("device_os_without_catalog_entry", "physical_devices: os_name/os_version без operating_system_id и embedded_os_id: 1"),
            ("vm_os_without_catalog_entry", "virtual_machines: os_name/os_version без operating_system_id: 1"),
            ("vm_platform_without_hypervisor", "virtual_machines: virtualization_platform_id без hypervisor_os_id: 1"),
            ("platform_without_catalog_entry", "virtualization_platforms: строки без пары в operating_systems (имя + версия): 1"),
        ],
    )
    def test_data_without_a_replacement_stops_the_migration_before_any_change(self, database, fixture, expected):
        database.upgrade(NOT_NULL)
        with database.engine.begin() as connection:
            category = _insert(connection, "operating_system_categories")
            if fixture == "device_os_without_catalog_entry":
                _insert(connection, "physical_devices", os_name="Windows", operating_system_id=None, embedded_os_id=None)
            elif fixture == "vm_os_without_catalog_entry":
                _insert(connection, "virtual_machines", name="vm-lost", os_version="1.0", operating_system_id=None)
            elif fixture == "vm_platform_without_hypervisor":
                platform = _insert(connection, "virtualization_platforms", name="Xen", version="4")
                _insert(connection, "operating_systems", category_id=category, name="Xen", version="4")  # в каталоге пара есть
                _insert(connection, "virtual_machines", name="vm-xen", virtualization_platform_id=platform, hypervisor_os_id=None)
            else:
                _insert(connection, "virtualization_platforms", name="Hyper-V", version="2022")
        columns_before = {table: _snapshot(database, table)["columns"] for table in LEGACY}

        with pytest.raises(RuntimeError) as error:
            database.upgrade(CLEANUP)

        assert expected in str(error.value)
        assert _revision(database) == NOT_NULL
        assert "virtualization_platforms" in sa.inspect(database.engine).get_table_names()
        assert {table: _snapshot(database, table)["columns"] for table in LEGACY} == columns_before

    def test_already_migrated_values_are_not_treated_as_a_loss(self, database):
        """c4e8a7d91b20 копировал значения в каталог, не очищая исходные колонки: такие базы обновляются без вмешательства."""
        database.upgrade(NOT_NULL)
        _legacy_rows(database, migrated=True)
        database.upgrade(CLEANUP)
        assert _revision(database) == CLEANUP

    def test_downgrade_restores_empty_objects_and_upgrade_works_again(self, database):
        database.upgrade(NOT_NULL)
        _legacy_rows(database)
        database.upgrade(CLEANUP)

        _downgrade(database, NOT_NULL)

        inspector = sa.inspect(database.engine)
        assert "virtualization_platforms" in inspector.get_table_names()
        for table, legacy in LEGACY.items():
            assert legacy <= {c["name"] for c in inspector.get_columns(table)}
        assert any(
            fk["referred_table"] == "virtualization_platforms" and fk["constrained_columns"] == ["virtualization_platform_id"]
            for fk in inspector.get_foreign_keys("virtual_machines")
        )
        with database.engine.connect() as connection:
            assert connection.execute(sa.text("SELECT COUNT(*) FROM virtualization_platforms")).scalar() == 0
            assert connection.execute(sa.text("SELECT COUNT(*) FROM virtual_machines WHERE os_name IS NOT NULL OR virtualization_platform_id IS NOT NULL")).scalar() == 0
            assert connection.execute(sa.text("SELECT COUNT(*) FROM virtual_machines")).scalar() == 1

        database.upgrade(CLEANUP)
        assert "virtualization_platforms" not in sa.inspect(database.engine).get_table_names()

    def test_second_run_on_a_clean_schema_changes_nothing(self, database):
        database.upgrade("head")
        before = {table: _snapshot(database, table) for table in LEGACY}
        module_path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "e9b4c2a7d136_drop_legacy_os_and_platform_columns.py"
        import importlib.util
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext

        spec = importlib.util.spec_from_file_location("a14_cleanup_migration", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with database.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade()
        assert {table: _snapshot(database, table) for table in LEGACY} == before


# ---------------------------------------------------------------------------------------------------------------------
# SQLite: триггер защиты и целостность после пересборки
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.sqlite_only
class TestSqliteSpecifics:
    def _source_row(self, database, vm_id: str) -> None:
        with database.engine.begin() as connection:
            _insert(connection, "information_system_sources", source_type="vm", owner_id=vm_id)

    def _delete_vm(self, database, vm_id: str) -> None:
        connection = sqlite3.connect(str(database.path))
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("DELETE FROM virtual_machines WHERE id = ?", (vm_id,))
            connection.commit()
        finally:
            connection.close()

    def test_vm_guard_trigger_survives_the_table_rebuild(self, database):
        database.upgrade(NOT_NULL)
        ids = _legacy_rows(database)
        self._source_row(database, ids["vm"])
        database.upgrade(CLEANUP)

        with database.engine.connect() as connection:
            names = set(connection.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'")).scalars())
        assert names == {"trg_is_source_guard_physical_devices", "trg_is_source_guard_virtual_machines", "trg_is_source_guard_containers"}
        with pytest.raises(sqlite3.IntegrityError, match="Нельзя удалить"):
            self._delete_vm(database, ids["vm"])

    def test_triggers_and_partial_index_survive_downgrade_and_upgrade(self, database):
        database.upgrade(CLEANUP)
        _downgrade(database, NOT_NULL)
        database.upgrade(CLEANUP)
        with database.engine.connect() as connection:
            names = set(connection.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'")).scalars())
            indexes = set(connection.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'physical_devices'")).scalars())
        assert "trg_is_source_guard_virtual_machines" in names
        assert "uq_device_rack_slot" in indexes

    def test_no_dangling_references_after_the_rebuild(self, database):
        database.upgrade(NOT_NULL)
        _legacy_rows(database)
        database.upgrade(CLEANUP)
        with database.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
            assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"

    def test_old_sqlite_stops_with_a_clear_message_and_changes_nothing(self, database, monkeypatch):
        database.upgrade(NOT_NULL)
        monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 34, 1))
        with pytest.raises(RuntimeError, match="SQLite не ниже 3.35"):
            database.upgrade(CLEANUP)
        assert _revision(database) == NOT_NULL
        assert LEGACY["physical_devices"] <= set(_columns(database, "physical_devices"))
