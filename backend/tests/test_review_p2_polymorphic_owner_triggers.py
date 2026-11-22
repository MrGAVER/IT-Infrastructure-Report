"""Триггеры БД, удаляющие полиморфных потомков (open_ports, deployed_software, ip_addresses) вместе с владельцем.

Миграция 7c3d9a5e1b24 (1) один раз удаляет уже осиротевшие строки и пишет итог в журнал аудита, (2) создаёт триггеры AFTER DELETE на
таблицах владельцев. Проверяется РЕАЛЬНОЕ поведение (прямой SQL DELETE, каскад внешнего ключа), а не только наличие триггеров: пересборка
таблицы в будущей SQLite-миграции молча удаляет её триггеры, и только такой тест это ловит.

Главная защита — тест полноты: каждое значение `app.constants.OwnerType` обязано (а) иметь владельца в integrity._OWNER_MODEL_BY_TYPE,
(б) быть описано в реестре очистки deletion._POLYMORPHIC_OWNER_CLEANUP, (в) удалять потомков триггером. Новый тип владельца без защиты роняет тест.

Базы: SQLite — файл во временном каталоге (маркер sqlite_only), PostgreSQL — временная база на сервере из INFRA_REGISTRY_TEST_DATABASE_URL
(маркер postgres_only). Схема строится цепочкой миграций, а не create_all: триггеры существуют только в ней.

Запуск: pytest backend/tests/test_review_p2_polymorphic_owner_triggers.py -v
"""

from __future__ import annotations

import importlib.util
import os
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.constants import OwnerType
from app.db import configure_sqlite_connection
from app.services.crud.deletion import _POLYMORPHIC_OWNER_CLEANUP
from app.services.integrity import _OWNER_MODEL_BY_TYPE
from migration_support import insert_row, migrate

BACKEND_DIR = Path(__file__).resolve().parent.parent
REVISION = "7c3d9a5e1b24"
PREVIOUS_REVISION = "d6c1a8f3e594"
CHILD_TABLES = ("open_ports", "deployed_software", "ip_addresses")
EXPECTED_TRIGGERS = {
    f"trg_owner_cleanup_{table}"
    for table in ("physical_devices", "virtual_machines", "device_interfaces", "device_subinterfaces", "information_system_sources")
}
OWNER_TYPES = sorted(value for name, value in vars(OwnerType).items() if not name.startswith("_") and isinstance(value, str))
BACKENDS = [pytest.param("sqlite", marks=pytest.mark.sqlite_only), pytest.param("postgres", marks=pytest.mark.postgres_only)]


class ScratchDatabase:
    """Пустая временная база выбранной СУБД; схему строит `upgrade()` (цепочка миграций)."""

    def __init__(self, backend: str, directory: Path) -> None:
        self._admin_engine = None
        if backend == "sqlite":
            self.url = f"sqlite:///{directory / f'scratch_{uuid.uuid4().hex[:8]}.db'}"
            self.engine = sa.create_engine(self.url)
            sa.event.listen(self.engine, "connect", lambda dbapi_connection, _record: configure_sqlite_connection(dbapi_connection))
        else:
            admin = make_url(os.environ["INFRA_REGISTRY_TEST_DATABASE_URL"])
            name = f"infra_owner_{uuid.uuid4().hex[:10]}"
            self.url = admin.set(database=name).render_as_string(hide_password=False)
            self._admin_engine = sa.create_engine(admin.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
            with self._admin_engine.connect() as connection:
                connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
            self.name = name
            self.engine = sa.create_engine(self.url)

    def upgrade(self, revision: str = "head") -> None:
        migrate(self.url, revision)

    def downgrade(self, revision: str) -> None:
        migrate(self.url, revision, downgrade=True)

    def triggers(self) -> set[str]:
        query = (
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            if self.engine.dialect.name == "sqlite"
            else "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"
        )
        with self.engine.connect() as connection:
            return {row[0] for row in connection.execute(sa.text(query))}

    def close(self) -> None:
        self.engine.dispose()
        if self._admin_engine is not None:
            with self._admin_engine.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)')
            self._admin_engine.dispose()


@pytest.fixture(scope="module", params=BACKENDS)
def head_database(request, tmp_path_factory):
    database = ScratchDatabase(request.param, tmp_path_factory.mktemp("owner_triggers"))
    try:
        database.upgrade("head")
        yield database
    finally:
        database.close()


def _count(connection, table: str, **where) -> int:
    clause = " AND ".join(f"{column} = :{column}" for column in where)
    return connection.execute(sa.text(f"SELECT count(*) FROM {table} WHERE {clause}"), where).scalar_one()


def _add_children(connection, owner_type: str, owner_id: str) -> None:
    for table in CHILD_TABLES:
        insert_row(connection, table, owner_type=owner_type, owner_id=owner_id)


def _children_of(connection, owner_type: str, owner_id: str) -> int:
    return sum(_count(connection, table, owner_type=owner_type, owner_id=owner_id) for table in CHILD_TABLES)


# ---------------------------------------------------------------------------------------------------------------------
# Полнота: новый тип владельца нельзя добавить без защиты
# ---------------------------------------------------------------------------------------------------------------------
def _migration_module():
    path = next((BACKEND_DIR / "alembic" / "versions").glob(f"{REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location("owner_cleanup_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_owner_type_values_are_found():
    assert {"physical_device", "virtual_machine", "device_interface", "device_subinterface", "information_system_source"} <= set(OWNER_TYPES)


def test_migration_covers_exactly_the_owner_types_and_tables_of_the_application():
    """Список в миграции заморожен: новый OwnerType (или другая таблица владельца) требует НОВОЙ миграции с триггером."""
    migration = _migration_module()
    assert dict((owner_type, table) for table, owner_type in migration._OWNERS) == {
        owner_type: model.__tablename__ for owner_type, model in _OWNER_MODEL_BY_TYPE.items()
    }
    assert {owner_type for _, owner_type in migration._OWNERS} == set(OWNER_TYPES)
    assert [table for table, _ in migration._CHILDREN] == list(CHILD_TABLES)


def test_every_owner_type_is_described_for_the_integrity_diagnostics():
    assert set(_OWNER_MODEL_BY_TYPE) == set(OWNER_TYPES), "новый OwnerType не добавлен в integrity._OWNER_MODEL_BY_TYPE"


def test_every_owner_type_has_a_cleanup_registry_entry():
    """Прикладная очистка (deletion.py) — первая линия защиты, триггер — последний рубеж; новый тип нельзя оставить только на одном."""
    in_registry = {owner_type for entries in _POLYMORPHIC_OWNER_CLEANUP.values() for _, owner_type in entries}
    in_registry.add(OwnerType.DEVICE_SUBINTERFACE)  # подинтерфейсы чистит purge_subinterfaces_of_interfaces (services/crud/subinterfaces.py)
    assert set(OWNER_TYPES) <= in_registry, f"нет прикладной очистки для: {sorted(set(OWNER_TYPES) - in_registry)}"


# ---------------------------------------------------------------------------------------------------------------------
# Поведение на схеме после миграций
# ---------------------------------------------------------------------------------------------------------------------
def test_triggers_exist_at_head(head_database):
    assert EXPECTED_TRIGGERS <= head_database.triggers()


def test_a_clean_database_gets_no_cleanup_noise_in_the_audit_log(head_database):
    with head_database.engine.connect() as connection:
        assert _count(connection, "audit_log", entity_id=REVISION) == 0


@pytest.mark.parametrize("owner_type", OWNER_TYPES)
def test_raw_delete_of_an_owner_removes_its_children_and_only_its_own(head_database, owner_type):
    assert owner_type in _OWNER_MODEL_BY_TYPE, f"тип владельца {owner_type!r} не описан в integrity._OWNER_MODEL_BY_TYPE"
    owner_table = _OWNER_MODEL_BY_TYPE[owner_type].__tablename__
    other_type = next(value for value in OWNER_TYPES if value != owner_type)
    with head_database.engine.begin() as connection:
        owner_id = insert_row(connection, owner_table)
        _add_children(connection, owner_type, owner_id)
        _add_children(connection, other_type, owner_id)  # тот же id, другой тип владельца: не наш потомок
        assert _children_of(connection, owner_type, owner_id) == 3

        connection.execute(sa.text(f"DELETE FROM {owner_table} WHERE id = :id"), {"id": owner_id})

        assert _children_of(connection, owner_type, owner_id) == 0, (
            f"у {owner_type} после удаления владельца остались потомки: триггер не создан или не срабатывает"
        )
        assert _children_of(connection, other_type, owner_id) == 3, "триггер удалил чужих потомков (тот же id, другой owner_type)"


def test_foreign_key_cascade_from_the_interface_cleans_the_subinterface_children(head_database):
    """FK ON DELETE CASCADE убирает подинтерфейсы порта, но не их полиморфных потомков (IP, открытые порты) — это и закрывает триггер:
    он срабатывает на строки, удалённые самим каскадом (устройство → порт в БД каскада не имеет — удаляется только пустое устройство)."""
    with head_database.engine.begin() as connection:
        interface_id = insert_row(connection, "device_interfaces")
        subinterface_id = insert_row(connection, "device_subinterfaces", parent_interface_id=interface_id)
        owners = {OwnerType.DEVICE_INTERFACE: interface_id, OwnerType.DEVICE_SUBINTERFACE: subinterface_id}
        for owner_type, owner_id in owners.items():
            _add_children(connection, owner_type, owner_id)

        connection.execute(sa.text("DELETE FROM device_interfaces WHERE id = :id"), {"id": interface_id})

        assert _count(connection, "device_subinterfaces", id=subinterface_id) == 0, "каскад должен был удалить подинтерфейс"
        assert {owner_type: _children_of(connection, owner_type, owner_id) for owner_type, owner_id in owners.items()} == {
            owner_type: 0 for owner_type in owners
        }


def test_deleting_the_owner_through_the_orm_works_with_the_triggers(head_database):
    """Прикладной путь (delete_resource: потомки удаляются явно, затем владелец) не ломается: триггеру остаётся 0 строк."""
    from sqlalchemy.orm import Session

    from app.models import IPAddress, VirtualMachine

    with Session(head_database.engine) as session:
        vm = VirtualMachine(name=f"vm-{uuid.uuid4().hex[:8]}")
        session.add(vm)
        session.flush()
        session.add(IPAddress(owner_type=OwnerType.VIRTUAL_MACHINE, owner_id=vm.id, ip_address="10.0.0.5"))
        session.flush()
        session.query(IPAddress).filter(IPAddress.owner_id == vm.id).delete()
        session.delete(vm)
        session.commit()
        assert session.query(IPAddress).filter(IPAddress.owner_id == vm.id).count() == 0


# ---------------------------------------------------------------------------------------------------------------------
# Миграция на данных: разовая чистка сирот и откат
# ---------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module", params=BACKENDS)
def migration_run(request, tmp_path_factory):
    """Схема на ревизии ДО миграции с сиротами и живыми записями → upgrade → снимок состояния → downgrade → снимок триггеров."""
    database = ScratchDatabase(request.param, tmp_path_factory.mktemp("owner_chain"))
    try:
        database.upgrade(PREVIOUS_REVISION)
        assert database.triggers() & EXPECTED_TRIGGERS == set(), "до миграции триггеров быть не должно"
        with database.engine.begin() as connection:
            device_id, vm_id = insert_row(connection, "physical_devices"), insert_row(connection, "virtual_machines")
            kept = {
                "device_port": insert_row(connection, "open_ports", owner_type=OwnerType.PHYSICAL_DEVICE, owner_id=device_id),
                "device_software": insert_row(connection, "deployed_software", owner_type=OwnerType.PHYSICAL_DEVICE, owner_id=device_id),
                "vm_ip": insert_row(connection, "ip_addresses", owner_type=OwnerType.VIRTUAL_MACHINE, owner_id=vm_id),
                "alien_type": insert_row(connection, "open_ports", owner_type="alien_owner", owner_id="no-such-owner"),
            }
            orphans = {
                "port_of_missing_device": insert_row(connection, "open_ports", owner_type=OwnerType.PHYSICAL_DEVICE, owner_id="missing-device"),
                "port_of_missing_interface": insert_row(connection, "open_ports", owner_type=OwnerType.DEVICE_INTERFACE, owner_id="missing-interface"),
                "software_of_missing_vm": insert_row(connection, "deployed_software", owner_type=OwnerType.VIRTUAL_MACHINE, owner_id="missing-vm"),
                "ip_of_missing_subinterface": insert_row(connection, "ip_addresses", owner_type=OwnerType.DEVICE_SUBINTERFACE, owner_id="missing-subinterface"),
                "ip_of_missing_source": insert_row(connection, "ip_addresses", owner_type=OwnerType.INFORMATION_SYSTEM_SOURCE, owner_id="missing-source"),
            }
        tables = {"open_ports", "deployed_software", "ip_addresses"}
        database.upgrade("head")
        with database.engine.connect() as connection:
            present = {
                key: connection.execute(sa.text(f"SELECT 1 FROM {table} WHERE id = :id"), {"id": row_id}).first() is not None
                for group in (kept, orphans)
                for key, row_id in group.items()
                for table in tables
                if _row_in(connection, table, row_id)
            }
            audit = connection.execute(
                sa.text("SELECT entity_type, action, details FROM audit_log WHERE entity_id = :revision ORDER BY entity_type"), {"revision": REVISION}
            ).all()
        triggers_at_head = database.triggers()
        database.downgrade(PREVIOUS_REVISION)
        yield {
            "kept": set(kept),
            "orphans": set(orphans),
            "present": set(present),
            "audit": audit,
            "triggers_at_head": triggers_at_head,
            "triggers_after_downgrade": database.triggers(),
        }
    finally:
        database.close()


def _row_in(connection, table: str, row_id: str) -> bool:
    return connection.execute(sa.text(f"SELECT 1 FROM {table} WHERE id = :id"), {"id": row_id}).first() is not None


def test_migration_removes_orphans_and_keeps_everything_else(migration_run):
    assert migration_run["present"] == migration_run["kept"], "удалены только сироты: живые записи и запись с неизвестным owner_type остаются"


def test_migration_logs_what_it_removed_in_the_audit_log(migration_run):
    by_resource = {entity_type: details for entity_type, action, details in migration_run["audit"] if action == "DELETE"}
    assert set(by_resource) == {"open-ports", "deployed-software", "ip-addresses"}
    assert (
        "удалены записи без владельца — 2" in by_resource["open-ports"]
        and "device_interface: 1" in by_resource["open-ports"]
        and "physical_device: 1" in by_resource["open-ports"]
    )
    assert "— 1 (virtual_machine: 1)" in by_resource["deployed-software"]
    assert "— 2" in by_resource["ip-addresses"] and REVISION in by_resource["ip-addresses"]


def test_migration_creates_the_triggers(migration_run):
    assert EXPECTED_TRIGGERS <= migration_run["triggers_at_head"]


def test_downgrade_drops_the_triggers(migration_run):
    assert migration_run["triggers_after_downgrade"] & EXPECTED_TRIGGERS == set()
