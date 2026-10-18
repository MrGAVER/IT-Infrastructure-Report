"""Цепочка миграций Alembic на PostgreSQL (docker-compose запускает `alembic upgrade head` на пустом томе).

Раньше цепочка на чистой PostgreSQL не проходила (булевы литералы, `PRAGMA`, пересборка таблиц для SQLite), и серверный
режим работал только на схеме из `create_all`. Здесь это закрепляется тестами; выполняются они только при
INFRA_REGISTRY_TEST_DATABASE_URL (маркер postgres_only), каждый — в собственной временной базе, чтобы не трогать
базу самих тестов.

Что проверяется:
  • цепочка на пустой базе доходит до единственного head, повторный `upgrade head` ничего не делает;
  • схема из миграций пригодна для приложения: все таблицы и колонки моделей на месте, уникальность и внешние ключи моделей
    действуют, остатки старых колонок не мешают вставкам, даты без часового пояса, как в моделях;
  • VLAN уникален в пределах домена, а не глобально (смысл миграции c9a4e7d2f610);
  • ветки миграций, которые работают с **данными** (на пустой базе они не выполняются), — на строках старой схемы.

Запуск: INFRA_REGISTRY_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/любая_база pytest backend/tests/test_migrations_postgres.py
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

import app.config as app_config
from app.models import Base

pytestmark = pytest.mark.postgres_only

BACKEND_DIR = Path(__file__).resolve().parent.parent
ADMIN_URL = os.environ.get("INFRA_REGISTRY_TEST_DATABASE_URL", "").strip()


def _config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False
    return cfg


class ScratchDatabase:
    """Временная база на том же сервере: создаётся пустой, удаляется после теста."""

    def __init__(self) -> None:
        self.name = f"infra_migr_{uuid.uuid4().hex[:10]}"
        admin = make_url(ADMIN_URL)
        self.url = admin.set(database=self.name).render_as_string(hide_password=False)
        self._admin_engine = sa.create_engine(admin.set(database=admin.database).render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
        with self._admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{self.name}"')
        self.engine = sa.create_engine(self.url, future=True)

    def upgrade(self, revision: str = "head") -> None:
        """env.py читает app.config.DATABASE_URL при каждом запуске команды — подставляем адрес на время миграции."""
        original = app_config.DATABASE_URL
        app_config.DATABASE_URL = self.url
        try:
            command.upgrade(_config(), revision)
        finally:
            app_config.DATABASE_URL = original

    def close(self) -> None:
        self.engine.dispose()
        with self._admin_engine.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)')
        self._admin_engine.dispose()


@pytest.fixture()
def scratch():
    database = ScratchDatabase()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture(scope="module")
def migrated():
    """Одна база с полностью применённой цепочкой на все проверки структуры."""
    database = ScratchDatabase()
    try:
        database.upgrade("head")
        yield database
    finally:
        database.close()


def _down_revision(revision: str) -> str:
    return ScriptDirectory.from_config(_config()).get_revision(revision).down_revision


# ----- вставка строк в схему любой ревизии: недостающие NOT NULL-значения и родительские строки создаются сами -----------

def _dummy(column_type, name: str):
    if isinstance(column_type, sa.Boolean):
        return False
    if isinstance(column_type, sa.DateTime):
        return datetime.now()
    if isinstance(column_type, sa.Date):
        return date.today()
    if isinstance(column_type, (sa.Integer, sa.Float, sa.Numeric)):
        return 0
    return f"{name}-{uuid.uuid4().hex[:8]}"


def _insert(connection, table: str, **values) -> str | None:
    """INSERT одной строки; id и обязательные колонки без значения по умолчанию заполняются заглушками, а обязательные
    внешние ключи — новой родительской строкой. Возвращает id вставленной строки."""
    inspector = sa.inspect(connection)
    foreign = {fk["constrained_columns"][0]: fk["referred_table"] for fk in inspector.get_foreign_keys(table) if len(fk["constrained_columns"]) == 1}
    row = dict(values)
    for column in inspector.get_columns(table):
        name = column["name"]
        if name in row:
            continue
        if name == "id":
            row[name] = str(uuid.uuid4())
        elif column["nullable"] or column.get("default") is not None or column.get("autoincrement") is True:
            continue
        elif name in foreign:
            row[name] = _insert(connection, foreign[name])
        else:
            row[name] = _dummy(column["type"], name)
    names = ", ".join(f'"{key}"' for key in row)
    marks = ", ".join(f":{key}" for key in row)
    connection.execute(sa.text(f'INSERT INTO "{table}" ({names}) VALUES ({marks})'), row)
    return row.get("id")


# ----- структура схемы -----------------------------------------------------------------------------------------------

class TestChain:
    def test_chain_has_a_single_head_and_the_database_is_stamped_with_it(self, migrated):
        heads = ScriptDirectory.from_config(_config()).get_heads()
        assert len(heads) == 1
        with migrated.engine.connect() as connection:
            assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars().all() == heads

    def test_second_upgrade_changes_nothing(self, migrated):
        before = sa.inspect(migrated.engine).get_table_names()
        migrated.upgrade("head")
        assert sa.inspect(migrated.engine).get_table_names() == before


class TestSchemaMatchesWhatTheAppNeeds:
    def test_every_model_table_and_column_exists(self, migrated):
        inspector = sa.inspect(migrated.engine)
        tables = set(inspector.get_table_names())
        missing_tables = {table.name for table in Base.metadata.tables.values()} - tables
        assert not missing_tables
        missing_columns = {
            f"{table.name}.{column.name}"
            for table in Base.metadata.tables.values()
            for column in table.columns
            if column.name not in {c["name"] for c in inspector.get_columns(table.name)}
        }
        assert not missing_columns

    def test_columns_left_behind_by_old_migrations_never_block_an_insert(self, migrated):
        """Остатки прежних схем (например, os_name у устройства) допустимы, пока они необязательны: ORM их не заполняет."""
        inspector = sa.inspect(migrated.engine)
        blocking = []
        for table in Base.metadata.tables.values():
            model_columns = {column.name for column in table.columns}
            for column in inspector.get_columns(table.name):
                required = not column["nullable"] and column.get("default") is None and column.get("autoincrement") is not True
                if column["name"] not in model_columns and required:
                    blocking.append(f"{table.name}.{column['name']}")
        assert not blocking

    def test_datetime_columns_are_timezone_naive_like_the_models(self, migrated):
        with migrated.engine.connect() as connection:
            aware = connection.execute(sa.text("SELECT table_name || '.' || column_name FROM information_schema.columns WHERE table_schema = 'public' AND data_type = 'timestamp with time zone'")).scalars().all()
        assert aware == []

    def test_model_uniqueness_is_enforced(self, migrated):
        inspector = sa.inspect(migrated.engine)
        absent = []
        for table in Base.metadata.tables.values():
            wanted = {tuple(sorted(c.name for c in constraint.columns)) for constraint in table.constraints if isinstance(constraint, sa.UniqueConstraint)}
            wanted |= {(column.name,) for column in table.columns if column.unique}
            wanted |= {tuple(sorted(c.name for c in index.columns)) for index in table.indexes if index.unique}
            have = {tuple(sorted(uc["column_names"])) for uc in inspector.get_unique_constraints(table.name)}
            have |= {tuple(sorted(ix["column_names"])) for ix in inspector.get_indexes(table.name) if ix.get("unique")}
            absent += [f"{table.name}{sorted(columns)}" for columns in wanted - have]
        assert not absent

    def test_model_foreign_keys_exist(self, migrated):
        inspector = sa.inspect(migrated.engine)
        absent = []
        for table in Base.metadata.tables.values():
            have = {(tuple(fk["constrained_columns"]), fk["referred_table"]) for fk in inspector.get_foreign_keys(table.name)}
            for foreign_key in table.foreign_key_constraints:
                key = (tuple(c.name for c in foreign_key.columns), foreign_key.referred_table.name)
                if key not in have:
                    absent.append(f"{table.name}{key[0]}→{key[1]}")
        assert not absent

    def test_vlan_number_is_unique_within_a_domain_not_globally(self, migrated):
        with migrated.engine.begin() as connection:
            first, second = _insert(connection, "vlan_domains"), _insert(connection, "vlan_domains")
            _insert(connection, "vlans", vlan_id=10, domain_id=first)
            _insert(connection, "vlans", vlan_id=10, domain_id=second)  # тот же номер в другом домене — можно
        with pytest.raises(sa.exc.IntegrityError), migrated.engine.begin() as connection:
            _insert(connection, "vlans", vlan_id=10, domain_id=first)  # повтор в том же домене — нельзя


# ----- ветки миграций, работающие с данными ---------------------------------------------------------------------------

class TestMigrationsThatMoveData:
    def test_old_management_fields_move_into_interfaces(self, scratch):
        """e8c2f1a9b430: management_port/management_ip устройства → интерфейс управления и его IP; тип подключения из cable_type."""
        revision = "e8c2f1a9b430"
        scratch.upgrade(_down_revision(revision))
        with scratch.engine.begin() as connection:
            device = _insert(connection, "physical_devices", management_port=1, management_ip="10.0.0.5")
            near = _insert(connection, "device_interfaces", physical_device_id=device, name="Gi0/1", interface_type="SFP+", speed="10G")
            far = _insert(connection, "device_interfaces", physical_device_id=_insert(connection, "physical_devices"), name="Gi0/2")
            link = _insert(connection, "connections", source_interface_id=near, destination_interface_id=far, connection_type="Ethernet", cable_type="Оптическое волокно")
        scratch.upgrade(revision)
        with scratch.engine.connect() as connection:
            interface = connection.execute(sa.text("SELECT is_management, interface_type_id FROM device_interfaces WHERE id = :i"), {"i": near}).one()
            ip = connection.execute(sa.text("SELECT is_management, purpose FROM interface_ips WHERE interface_id = :i AND ip_address = '10.0.0.5'"), {"i": near}).one()
            link_type = connection.execute(sa.text("SELECT t.name FROM connections c JOIN connection_types t ON t.id = c.connection_type_id WHERE c.id = :c"), {"c": link}).scalar_one()
        assert interface.is_management is True and interface.interface_type_id is not None
        assert ip.is_management is True and ip.purpose == "Управление"
        assert link_type == "Оптическое волокно"  # физический носитель (cable_type) важнее прежнего connection_type

    def test_vm_administration_ip_becomes_a_management_address(self, scratch):
        """e7a2c9f4d813: administration_ip ВМ → строка vm_ips с признаком управления (новая или уже существующая)."""
        revision = "e7a2c9f4d813"
        scratch.upgrade(_down_revision(revision))
        with scratch.engine.begin() as connection:
            known = _insert(connection, "virtual_machines", administration_ip="10.1.1.5")
            _insert(connection, "vm_ips", virtual_machine_id=known, ip_address="10.1.1.5", is_management=False)  # адрес уже есть, но не помечен
            fresh = _insert(connection, "virtual_machines", administration_ip="10.1.1.6")  # адреса в vm_ips нет
        scratch.upgrade(revision)
        with scratch.engine.connect() as connection:
            rows = connection.execute(sa.text("SELECT virtual_machine_id, ip_address, is_management FROM vm_ips ORDER BY ip_address")).all()
        assert [(r.virtual_machine_id, r.ip_address, r.is_management) for r in rows] == [(known, "10.1.1.5", True), (fresh, "10.1.1.6", True)]

    def test_source_ip_lists_split_into_address_rows(self, scratch):
        """d8e35a1c7f60: составное поле ip_address источника ИС («a, b») → отдельные строки ip_addresses, не управляющие."""
        revision = "d8e35a1c7f60"
        scratch.upgrade(_down_revision(revision))
        with scratch.engine.begin() as connection:
            source = _insert(connection, "information_system_sources", ip_address="10.9.9.1, 10.9.9.2,  ")
        scratch.upgrade(revision)
        with scratch.engine.connect() as connection:
            rows = connection.execute(sa.text("SELECT owner_id, ip_address, is_management FROM ip_addresses WHERE owner_type = 'information_system_source' ORDER BY ip_address")).all()
        assert [(r.owner_id, r.ip_address, r.is_management) for r in rows] == [(source, "10.9.9.1", False), (source, "10.9.9.2", False)]

    def test_separate_is_relations_become_unified_sources(self, scratch):
        """8c5d1f7a2b40: связи ИС с устройствами, ВМ, контейнерами и адресами → единая таблица источников, external_interaction — boolean."""
        revision = "8c5d1f7a2b40"
        scratch.upgrade(_down_revision(revision))
        with scratch.engine.begin() as connection:
            system = _insert(connection, "information_systems")
            device = _insert(connection, "physical_devices")
            vm = _insert(connection, "virtual_machines")
            container = _insert(connection, "containers")
            _insert(connection, "information_system_devices", information_system_id=system, physical_device_id=device, role="основной")
            _insert(connection, "information_system_vms", information_system_id=system, virtual_machine_id=vm, role="приложение")
            _insert(connection, "information_system_containers", information_system_id=system, container_id=container, role="сервис")
            _insert(connection, "information_system_ips", information_system_id=system, ip_address="203.0.113.7", purpose="внешний", external_interaction=True)
        scratch.upgrade(revision)
        with scratch.engine.connect() as connection:
            rows = connection.execute(sa.text("SELECT source_type, role, external_interaction, ip_address FROM information_system_sources ORDER BY source_type, role")).all()
        by_kind = {(r.source_type, r.role): (r.external_interaction, r.ip_address) for r in rows}
        assert by_kind[("device", "основной")] == (False, None)
        assert by_kind[("vm", "приложение")] == (False, None)
        assert by_kind[("container", "сервис")] == (False, None)
        assert any(r.ip_address == "203.0.113.7" and r.external_interaction is True for r in rows)
