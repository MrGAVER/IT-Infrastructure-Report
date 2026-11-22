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
  • ветки миграций, которые работают с **данными** (на пустой базе они не выполняются), — на строках старой схемы (TestMigrationsThatMoveData).

Запуск: INFRA_REGISTRY_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/любая_база pytest backend/tests/test_migrations_postgres.py
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app.config as app_config  # noqa: E402
from app.models import Base
from migration_support import insert_row  # noqa: E402

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

    def downgrade(self, revision: str) -> None:
        original = app_config.DATABASE_URL
        app_config.DATABASE_URL = self.url
        try:
            command.downgrade(_config(), revision)
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


def _get_or_insert(connection, table: str, lookup: dict, **extra) -> str:
    """Строка справочника, которую ранние миграции уже засеяли (порт 22/SSH, тип «Сервер»): берём её, а не вставляем дубль,
    иначе тест упёрся бы в уникальность справочника, а не в проверяемую миграцию."""
    where = " AND ".join(f"{column} = :{column}" for column in lookup)
    found = connection.execute(sa.text(f"SELECT id FROM {table} WHERE {where}"), lookup).scalar()
    return found or insert_row(connection, table, **lookup, **extra)


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
            f"{table.name}.{column.name}" for table in Base.metadata.tables.values() for column in table.columns if column.name not in {c["name"] for c in inspector.get_columns(table.name)}
        }
        assert not missing_columns

    def test_columns_left_behind_by_old_migrations_never_block_an_insert(self, migrated):
        """Остатки прежних схем допустимы, пока они необязательны: ORM их не заполняет."""
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
            aware = (
                connection.execute(sa.text("SELECT table_name || '.' || column_name FROM information_schema.columns WHERE table_schema = 'public' AND data_type = 'timestamp with time zone'"))
                .scalars()
                .all()
            )
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
            first, second = insert_row(connection, "vlan_domains"), insert_row(connection, "vlan_domains")
            insert_row(connection, "vlans", vlan_id=10, domain_id=first)
            insert_row(connection, "vlans", vlan_id=10, domain_id=second)  # тот же номер в другом домене — можно
        with pytest.raises(sa.exc.IntegrityError), migrated.engine.begin() as connection:
            insert_row(connection, "vlans", vlan_id=10, domain_id=first)  # повтор в том же домене — нельзя


# ----- ветки миграций, работающие с данными ---------------------------------------------------------------------------


class TestMigrationsThatMoveData:
    def test_old_management_fields_move_into_interfaces(self, scratch):
        """e8c2f1a9b430: management_port/management_ip устройства → интерфейс управления и его IP; тип подключения из cable_type."""
        revision = "e8c2f1a9b430"
        scratch.upgrade(_down_revision(revision))
        with scratch.engine.begin() as connection:
            device = insert_row(connection, "physical_devices", management_port=1, management_ip="10.0.0.5")
            near = insert_row(connection, "device_interfaces", physical_device_id=device, name="Gi0/1", interface_type="SFP+", speed="10G")
            far = insert_row(connection, "device_interfaces", physical_device_id=insert_row(connection, "physical_devices"), name="Gi0/2")
            link = insert_row(connection, "connections", source_interface_id=near, destination_interface_id=far, connection_type="Ethernet", cable_type="Оптическое волокно")
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
            known = insert_row(connection, "virtual_machines", administration_ip="10.1.1.5")
            insert_row(connection, "vm_ips", virtual_machine_id=known, ip_address="10.1.1.5", is_management=False)  # адрес уже есть, но не помечен
            fresh = insert_row(connection, "virtual_machines", administration_ip="10.1.1.6")  # адреса в vm_ips нет
        scratch.upgrade(revision)
        with scratch.engine.connect() as connection:
            rows = connection.execute(sa.text("SELECT virtual_machine_id, ip_address, is_management FROM vm_ips ORDER BY ip_address")).all()
        assert [(r.virtual_machine_id, r.ip_address, r.is_management) for r in rows] == [(known, "10.1.1.5", True), (fresh, "10.1.1.6", True)]

    def test_source_ip_lists_split_into_address_rows(self, scratch):
        """d8e35a1c7f60: составное поле ip_address источника ИС («a, b») → отдельные строки ip_addresses, не управляющие."""
        revision = "d8e35a1c7f60"
        scratch.upgrade(_down_revision(revision))
        with scratch.engine.begin() as connection:
            source = insert_row(connection, "information_system_sources", ip_address="10.9.9.1, 10.9.9.2,  ")
        scratch.upgrade(revision)
        with scratch.engine.connect() as connection:
            rows = connection.execute(sa.text("SELECT owner_id, ip_address, is_management FROM ip_addresses WHERE owner_type = 'information_system_source' ORDER BY ip_address")).all()
        assert [(r.owner_id, r.ip_address, r.is_management) for r in rows] == [(source, "10.9.9.1", False), (source, "10.9.9.2", False)]

    def test_status_columns_are_dropped_and_templates_lose_references_to_them(self, scratch):
        """b3f7a2c91d54: колонки status удалены (ALTER TABLE … DROP COLUMN), данные строк целы, сохранённые шаблоны переписаны, откат возвращает колонки."""
        revision = "b3f7a2c91d54"
        scratch.upgrade(_down_revision(revision))
        config = {
            "sheets": [
                {
                    "rows": [
                        {
                            "repeat": True,
                            "data_source": {"root_entity": "information-systems", "filters": [{"path": "status", "op": "eq", "value": "active"}], "sort_by": "name"},
                            "cells": [{"col": 0, "kind": "field", "path": "name"}, {"col": 1, "kind": "field", "path": "status"}],
                        }
                    ]
                }
            ]
        }
        with scratch.engine.begin() as connection:
            device = insert_row(connection, "physical_devices", serial_number="SN-9", status="retired")
            system = insert_row(connection, "information_systems", name="ИС-9", status="planned")
            vm = insert_row(connection, "virtual_machines", name="vm-9", status="stopped")
            template = insert_row(connection, "report_templates", name="С фильтром", format="xlsx", config=json.dumps(config, ensure_ascii=False))
            version = insert_row(connection, "report_template_versions", report_template_id=template, version_number=1, name="С фильтром", format="xlsx", config=json.dumps(config, ensure_ascii=False))
        scratch.upgrade(revision)
        inspector = sa.inspect(scratch.engine)
        assert not any("status" in {c["name"] for c in inspector.get_columns(table)} for table in ("physical_devices", "information_systems", "virtual_machines"))
        with scratch.engine.connect() as connection:
            assert connection.execute(sa.text("SELECT serial_number FROM physical_devices WHERE id = :i"), {"i": device}).scalar_one() == "SN-9"
            assert connection.execute(sa.text("SELECT name FROM information_systems WHERE id = :i"), {"i": system}).scalar_one() == "ИС-9"
            assert connection.execute(sa.text("SELECT name FROM virtual_machines WHERE id = :i"), {"i": vm}).scalar_one() == "vm-9"
            for table, row_id in (("report_templates", template), ("report_template_versions", version)):
                stored = json.loads(connection.execute(sa.text(f"SELECT config FROM {table} WHERE id = :i"), {"i": row_id}).scalar_one())
                row = stored["sheets"][0]["rows"][0]
                assert row["data_source"]["filters"] == [] and row["cells"][1] == {"col": 1, "kind": "static", "text": ""} and "status" not in json.dumps(stored)
        scratch.downgrade(_down_revision(revision))
        inspector = sa.inspect(scratch.engine)
        assert all("status" in {c["name"] for c in inspector.get_columns(table)} for table in ("physical_devices", "information_systems", "virtual_machines"))

    def test_group_single_ip_moves_into_the_new_table_and_downgrade_keeps_the_first_address(self, scratch):
        """d5a8c3e7b196: единственный IP группы портов (ip_address/prefix_length/ip_purpose) → строка interface_group_ips,
        колонки сняты (ALTER TABLE … DROP COLUMN); адреса каскадно удаляются вместе с группой (настоящий FK); откат
        возвращает колонки и первый адрес группы, остальные в старой схеме негде хранить."""
        revision = "d5a8c3e7b196"
        scratch.upgrade(_down_revision(revision))
        with scratch.engine.begin() as connection:
            device = insert_row(connection, "physical_devices")
            with_ip = insert_row(connection, "interface_groups", physical_device_id=device, name="С IP", ip_address="10.0.0.5", prefix_length=24, ip_purpose="Управление")
            without_ip = insert_row(connection, "interface_groups", physical_device_id=device, name="Без IP")
        scratch.upgrade(revision)
        assert not {"ip_address", "prefix_length", "ip_purpose"} & {c["name"] for c in sa.inspect(scratch.engine).get_columns("interface_groups")}
        with scratch.engine.connect() as connection:
            rows = connection.execute(sa.text("SELECT group_id, ip_address, prefix_length, purpose FROM interface_group_ips")).all()
        assert [tuple(r) for r in rows] == [(with_ip, "10.0.0.5", 24, "Управление")]  # у группы без IP строк нет

        with scratch.engine.begin() as connection:  # второй адрес (позже первого) и каскад
            insert_row(connection, "interface_group_ips", group_id=with_ip, ip_address="10.0.1.5", prefix_length=24, created_at=datetime(2099, 1, 1), updated_at=datetime(2099, 1, 1))
            extra = insert_row(connection, "interface_groups", physical_device_id=device, name="Удаляемая")
            insert_row(connection, "interface_group_ips", group_id=extra, ip_address="10.0.2.5")
            connection.execute(sa.text("DELETE FROM interface_groups WHERE id = :i"), {"i": extra})
        with scratch.engine.connect() as connection:
            assert connection.execute(sa.text("SELECT COUNT(*) FROM interface_group_ips")).scalar_one() == 2

        scratch.downgrade(_down_revision(revision))
        assert not sa.inspect(scratch.engine).has_table("interface_group_ips")
        with scratch.engine.connect() as connection:
            restored = {r.id: (r.ip_address, r.prefix_length, r.ip_purpose) for r in connection.execute(sa.text("SELECT id, ip_address, prefix_length, ip_purpose FROM interface_groups"))}
        assert restored[with_ip] == ("10.0.0.5", 24, "Управление") and restored[without_ip] == (None, None, None)

    def test_separate_is_relations_become_unified_sources(self, scratch):
        """8c5d1f7a2b40: связи ИС с устройствами, ВМ, контейнерами и адресами → единая таблица источников, external_interaction — boolean."""
        revision = "8c5d1f7a2b40"
        scratch.upgrade(_down_revision(revision))
        with scratch.engine.begin() as connection:
            system = insert_row(connection, "information_systems")
            device = insert_row(connection, "physical_devices")
            vm = insert_row(connection, "virtual_machines")
            container = insert_row(connection, "containers")
            insert_row(connection, "information_system_devices", information_system_id=system, physical_device_id=device, role="основной")
            insert_row(connection, "information_system_vms", information_system_id=system, virtual_machine_id=vm, role="приложение")
            insert_row(connection, "information_system_containers", information_system_id=system, container_id=container, role="сервис")
            insert_row(connection, "information_system_ips", information_system_id=system, ip_address="203.0.113.7", purpose="внешний", external_interaction=True)
        scratch.upgrade(revision)
        with scratch.engine.connect() as connection:
            rows = connection.execute(sa.text("SELECT source_type, role, external_interaction, ip_address FROM information_system_sources ORDER BY source_type, role")).all()
        by_kind = {(r.source_type, r.role): (r.external_interaction, r.ip_address) for r in rows}
        assert by_kind[("device", "основной")] == (False, None)
        assert by_kind[("vm", "приложение")] == (False, None)
        assert by_kind[("container", "сервис")] == (False, None)
        assert any(r.ip_address == "203.0.113.7" and r.external_interaction is True for r in rows)

    def test_source_owner_columns_collapse_into_owner_id(self, scratch):
        """944bd490d967: три необязательных FK источника ИС (устройство/ВМ/контейнер) → единый owner_id по source_type; у ручного источника владельца нет."""
        revision = "944bd490d967"
        scratch.upgrade(_down_revision(revision))
        with scratch.engine.begin() as connection:
            device, vm, container = (insert_row(connection, "physical_devices"), insert_row(connection, "virtual_machines"), insert_row(connection, "containers"))
            insert_row(connection, "information_system_sources", source_type="device", physical_device_id=device)
            insert_row(connection, "information_system_sources", source_type="vm", virtual_machine_id=vm)
            insert_row(connection, "information_system_sources", source_type="container", container_id=container)
            insert_row(connection, "information_system_sources", source_type="manual")
        scratch.upgrade(revision)
        with scratch.engine.connect() as connection:
            owners = {r.source_type: r.owner_id for r in connection.execute(sa.text("SELECT source_type, owner_id FROM information_system_sources"))}
        assert owners == {"device": device, "vm": vm, "container": container, "manual": None}

    def test_open_ports_without_a_catalog_entry_get_one(self, scratch):
        """a1b7c9d3e502: open_ports.protocol_catalog_id заполняется (запись справочника — существующая, новая или по транспорту) и становится обязательным."""
        revision = "a1b7c9d3e502"
        scratch.upgrade(_down_revision(revision))
        with scratch.engine.begin() as connection:
            device = insert_row(connection, "physical_devices")
            known = _get_or_insert(connection, "protocol_port_catalogs", {"port": 22, "protocol_type": "SSH"})  # порт 22/SSH справочник уже содержит
            for port, protocol, transport in ((22, "SSH", None), (443, "HTTPS", None), (443, "HTTPS", None), (444, "HTTPS", None), (53, None, "UDP")):
                values = {"transport_protocol": transport} if transport else {}
                insert_row(connection, "open_ports", owner_type="physical_device", owner_id=device, port=port, protocol=protocol, **values)
        scratch.upgrade(revision)
        with scratch.engine.connect() as connection:
            rows = connection.execute(
                sa.text("SELECT p.port, k.protocol_type, k.id AS catalog_id FROM open_ports p JOIN protocol_port_catalogs k ON k.id = p.protocol_catalog_id ORDER BY p.port, k.id")
            ).all()
        assert [(r.port, r.protocol_type) for r in rows] == [(22, "SSH"), (53, "UDP"), (443, "HTTPS"), (443, "HTTPS"), (444, "HTTPS")]
        assert rows[0].catalog_id == known  # существующая запись не задвоена
        assert rows[2].catalog_id == rows[3].catalog_id  # одинаковые 443/HTTPS делят одну новую запись
        assert {c["name"]: c["nullable"] for c in sa.inspect(scratch.engine).get_columns("open_ports")}["protocol_catalog_id"] is False

    def test_free_text_os_moves_into_the_catalog_and_repeats_share_one_entry(self, scratch):
        """c4e8a7d91b20: свободный текст ОС устройств и ВМ → каталог operating_systems («Другое»), платформа виртуализации → «Гипервизор».
        Повтор без версии (version IS NULL) находит прежнюю запись, а не плодит дубль: на PostgreSQL сравнение `version IS :version`
        было синтаксической ошибкой, и миграция падала на первой же базе с данными."""
        revision = "c4e8a7d91b20"
        scratch.upgrade(_down_revision(revision))
        with scratch.engine.begin() as connection:
            platform = insert_row(connection, "virtualization_platforms", name="VMware ESXi", vendor="VMware", version="8")
            windows_a = insert_row(connection, "physical_devices", os_name="Windows Server", os_version="2019")
            debian_a = insert_row(connection, "physical_devices", os_name="Debian", os_version=None)
            windows_b = insert_row(connection, "physical_devices", os_name="Windows Server", os_version="2019")
            debian_b = insert_row(connection, "physical_devices", os_name="Debian", os_version=None)
            vm = insert_row(connection, "virtual_machines", os_name="Ubuntu", os_version="22.04", virtualization_platform_id=platform)
        scratch.upgrade(revision)
        with scratch.engine.connect() as connection:
            devices = {r.id: r.operating_system_id for r in connection.execute(sa.text("SELECT id, operating_system_id FROM physical_devices"))}
            vm_row = connection.execute(sa.text("SELECT operating_system_id, hypervisor_os_id FROM virtual_machines WHERE id = :i"), {"i": vm}).one()
            debian_entries = connection.execute(sa.text("SELECT COUNT(*) FROM operating_systems WHERE name = 'Debian'")).scalar_one()
            hypervisor = connection.execute(
                sa.text("SELECT o.name, o.version FROM operating_systems o JOIN operating_system_categories c ON c.id = o.category_id WHERE o.id = :i AND c.name = 'Гипервизор'"),
                {"i": vm_row.hypervisor_os_id},
            ).one()
        assert all(devices.values())
        assert devices[windows_a] == devices[windows_b] and devices[debian_a] == devices[debian_b] and devices[windows_a] != devices[debian_a]
        assert debian_entries == 1
        assert vm_row.operating_system_id is not None and tuple(hypervisor) == ("VMware ESXi", "8")

    def test_dropping_network_and_security_device_types_removes_everything_hanging_on_them(self, scratch):
        """38e9b2624a53: типы «Сетевое оборудование»/«Средство защиты информации» и ВСЁ зависимое (интерфейсы, подключения, ВМ, контейнеры, источники ИС,
        открытые порты) удаляются; устройства прочих типов и их интерфейсы целы, у каждого оставшегося типа появляется категория."""
        revision = "38e9b2624a53"
        scratch.upgrade(_down_revision(revision))
        with scratch.engine.begin() as connection:
            server_type = _get_or_insert(connection, "device_types", {"name": "Сервер"})
            network_type = _get_or_insert(connection, "device_types", {"name": "Сетевое оборудование"})
            kept_device = insert_row(connection, "physical_devices", device_type_id=server_type)
            doomed_device = insert_row(connection, "physical_devices", device_type_id=network_type)
            doomed_interface = insert_row(connection, "device_interfaces", physical_device_id=doomed_device, name="Gi0/1")
            kept_interface = insert_row(connection, "device_interfaces", physical_device_id=kept_device, name="Gi0/2")
            insert_row(connection, "connections", source_interface_id=doomed_interface, destination_interface_id=kept_interface)
            doomed_vm = insert_row(connection, "virtual_machines", physical_device_id=doomed_device)
            doomed_container = insert_row(connection, "containers", virtual_machine_id=doomed_vm)
            insert_row(connection, "information_system_sources", source_type="device", physical_device_id=doomed_device)
            insert_row(connection, "information_system_sources", source_type="vm", virtual_machine_id=doomed_vm)
            insert_row(connection, "information_system_sources", source_type="container", container_id=doomed_container)
            insert_row(connection, "open_ports", owner_type="physical_device", owner_id=doomed_device, port=22)
            insert_row(connection, "open_ports", owner_type="virtual_machine", owner_id=doomed_vm, port=80)
        scratch.upgrade(revision)
        tables = ("physical_devices", "virtual_machines", "containers", "device_interfaces", "connections", "information_system_sources", "open_ports")
        with scratch.engine.connect() as connection:
            left = {table: connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one() for table in tables}
            types = {r.name: r.category_id for r in connection.execute(sa.text("SELECT name, category_id FROM device_types"))}
        assert left == {"physical_devices": 1, "virtual_machines": 0, "containers": 0, "device_interfaces": 1, "connections": 0, "information_system_sources": 0, "open_ports": 0}
        assert "Сетевое оборудование" not in types and all(types.values())

    def test_not_null_type_migration_refuses_rows_without_a_type_and_changes_nothing(self, scratch):
        """d7a3f1c8b254: связь без типа — остановка с понятной ошибкой, база не тронута; после исправления данных колонка становится NOT NULL."""
        revision = "d7a3f1c8b254"
        scratch.upgrade(_down_revision(revision))
        with scratch.engine.begin() as connection:
            link = insert_row(connection, "connections")  # connection_type_id остаётся NULL
        with pytest.raises(RuntimeError, match=f"{revision} остановлена"):
            scratch.upgrade(revision)
        with scratch.engine.begin() as connection:
            assert connection.execute(sa.text("SELECT connection_type_id FROM connections WHERE id = :i"), {"i": link}).scalar() is None
            connection.execute(sa.text("UPDATE connections SET connection_type_id = :t"), {"t": insert_row(connection, "connection_types")})
        scratch.upgrade(revision)
        assert {c["name"]: c["nullable"] for c in sa.inspect(scratch.engine).get_columns("connections")}["connection_type_id"] is False

    def test_legacy_os_columns_are_dropped_only_when_every_value_is_in_the_catalog(self, scratch):
        """e9b4c2a7d136: устройство со свободным текстом ОС, которого нет в каталоге, останавливает миграцию (иначе значение пропало бы
        вместе с колонкой); после переноса в каталог os_name/os_version и таблица платформ удаляются, ссылка на ОС сохраняется."""
        revision = "e9b4c2a7d136"
        scratch.upgrade(_down_revision(revision))
        with scratch.engine.begin() as connection:
            device = insert_row(connection, "physical_devices", os_name="Legacy OS", os_version="1")  # operating_system_id остаётся NULL
        with pytest.raises(RuntimeError, match=f"{revision} остановлена"):
            scratch.upgrade(revision)
        with scratch.engine.begin() as connection:
            os_id = insert_row(connection, "operating_systems", name="Legacy OS", version="1")
            connection.execute(sa.text("UPDATE physical_devices SET operating_system_id = :o WHERE id = :d"), {"o": os_id, "d": device})
        scratch.upgrade(revision)
        inspector = sa.inspect(scratch.engine)
        assert not {"os_name", "os_version"} & {c["name"] for c in inspector.get_columns("physical_devices")}
        assert not inspector.has_table("virtualization_platforms")
        with scratch.engine.connect() as connection:
            assert connection.execute(sa.text("SELECT operating_system_id FROM physical_devices WHERE id = :d"), {"d": device}).scalar_one() == os_id
