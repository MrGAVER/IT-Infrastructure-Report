"""Тест-страж: схема после `alembic upgrade head` совпадает с models.py (A-14).

Раньше CI этого не проверял, и схема из миграций тихо разошлась с моделями: у `created_at`/`updated_at` в базе из миграций
стоит NULLABLE, а модель обещает NOT NULL; у ряда внешних ключей не было индексов; остались устаревшие колонки. Пользовательские
базы (EXE, PostgreSQL) строятся именно миграциями, а тесты по умолчанию — `create_all`, поэтому расхождение было невидимо.

Как работает. Применяем всю цепочку миграций к пустой базе и сравниваем результат с `Base.metadata` тем же механизмом, что
`alembic revision --autogenerate` (`compare_type=True`, как в alembic/env.py). Каждое расхождение превращается в строку-ключ.
Ожидаемые расхождения перечислены ниже (whitelist) — каждое с причиной, по которой оно оставлено. Тест падает в обе стороны:
  • появилось расхождение, которого нет в whitelist, — забыта миграция (или модель изменена без неё);
  • расхождение из whitelist исчезло — уберите строку из списка, чтобы страж не «молчал» про уже исправленное.

Что делать при падении: добавить миграцию (`alembic revision`), а в whitelist ничего не вносить. Whitelist правится только
осознанным решением: он фиксирует вопросы, которые должен решить владелец продукта.

Запуск: `pytest tests/test_migrations_match_models.py` (SQLite);
        INFRA_REGISTRY_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/любая_база pytest tests/test_migrations_match_models.py (PostgreSQL).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

import app.config as app_config
from app.models import Base

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False
    return cfg


def _migrate(url: str, revision: str = "head", *, downgrade: bool = False) -> None:
    """env.py читает app.config.DATABASE_URL при каждом запуске команды — подставляем адрес на время миграции."""
    original = app_config.DATABASE_URL
    app_config.DATABASE_URL = url
    try:
        (command.downgrade if downgrade else command.upgrade)(_alembic_config(), revision)
    finally:
        app_config.DATABASE_URL = original


# ----------------------------------------------------------------------------------------------------------------------
# Whitelist: расхождения «миграции ↔ модели», которые сознательно оставлены. Формат ключа — см. _describe().
# ----------------------------------------------------------------------------------------------------------------------

# 1. NOT NULL у created_at/updated_at. Модели (TimestampMixin) объявляют их обязательными, а миграции создавали без NOT NULL.
#    Значения проставляет приложение (default=utcnow_naive), но в старых строках NULL возможен. Выравнивание требует бэкфилла
#    и решения владельца продукта: ужесточить БД или ослабить модели. До решения — только фиксируем.
NULLABLE_TIMESTAMP_TABLES = (
    "auth_sessions", "auth_settings", "crypto_protection_means", "device_categories", "device_type_vlans",
    "diagram_group_states", "diagram_icons", "diagram_layouts", "embedded_operating_systems", "interface_speeds",
    "is_placement_assets", "physical_device_vlans", "placement_assets", "port_sync_rules", "protocol_port_catalogs",
    "report_template_versions", "saved_diagrams", "structural_units", "support_methods", "support_organizations", "users",
)
# У двух таблиц нет одной из колонок (auth_sessions — только created_at, auth_settings — только updated_at).
_TIMESTAMP_COLUMNS = {"auth_sessions": ("created_at",), "auth_settings": ("updated_at",)}
NULLABLE_TIMESTAMPS = {
    f"modify_nullable {table}.{column}: db=NULL model=NOT NULL"
    for table in NULLABLE_TIMESTAMP_TABLES for column in _TIMESTAMP_COLUMNS.get(table, ("created_at", "updated_at"))
}

COMMON = NULLABLE_TIMESTAMPS | {
    # 2. Внешние ключи, обязательные в модели, но допускающие NULL в базе (модель требует значение, старые строки — нет).
    "modify_nullable connections.connection_type_id: db=NULL model=NOT NULL",
    "modify_nullable device_models.device_type_id: db=NULL model=NOT NULL",
    # 3. Устаревшие колонки и таблица: данные перенесены миграциями (c4e8a7d91b20, 4ea6658f69bf и др.), но сами объекты не
    #    удалены. Удаление деструктивно — только по отдельному решению владельца.
    "remove_column physical_devices.os_name",
    "remove_column physical_devices.os_version",
    "remove_column virtual_machines.os_name",
    "remove_column virtual_machines.os_version",
    "remove_column virtual_machines.virtualization_platform_id",
    "remove_fk virtual_machines",
    "remove_table virtualization_platforms",
    # 4. Индексы, которые есть в базе, но не объявлены в моделях. Безвредны (ускоряют запросы), в моделях не описаны.
    "remove_index deployed_software(owner_type,owner_id) ix_deployed_software_owner",
    "remove_index deployed_software(software_asset_id) ix_deployed_software_software_asset_id",
    "remove_index ip_addresses(owner_type,owner_id) ix_ip_addresses_owner",
    # 5. Одно и то же, выраженное по-разному: UNIQUE-ограничение в базе против unique-индекса в модели (`unique=True,
    #    index=True` у одной колонки), либо индекс под другим именем. Свойство (уникальность/быстрый поиск) обеспечено.
    "add_index auth_sessions(token_hash) ix_auth_sessions_token_hash",
    "remove_constraint UniqueConstraint auth_sessions.uq_auth_sessions_token_hash",
    "add_index diagram_layouts(saved_diagram_id) ix_diagram_layouts_saved_diagram_id",
    "remove_index diagram_layouts(saved_diagram_id) ix_diagram_layouts_saved_diagram_id",
    "add_index physical_device_vlans(physical_device_id) ix_physical_device_vlans_physical_device_id",
    "remove_index physical_device_vlans(physical_device_id) ix_physical_device_vlans_device_id",
}

# Расхождения, зависящие от СУБД: цепочка миграций ведёт себя по-разному (пересборка таблиц на SQLite, ALTER на PostgreSQL).
SQLITE_ONLY = {
    # vlans: UNIQUE(domain_id, vlan_id) на SQLite потерян пересборкой таблицы; на PostgreSQL он есть. Добавление ограничения
    # на существующие данные может упасть при уже накопленных дублях — отдельное решение.
    "add_constraint UniqueConstraint vlans.uq_vlan_domain_id",
}
POSTGRES_ONLY = {
    "modify_nullable information_system_sources.created_at: db=NULL model=NOT NULL",
    "modify_nullable information_system_sources.updated_at: db=NULL model=NOT NULL",
    # Безымянное UNIQUE у diagram_layouts.saved_diagram_id (начальная схема PostgreSQL) — то же, что unique-индекс модели.
    "remove_constraint UniqueConstraint diagram_layouts.diagram_layouts_saved_diagram_id_key",
}


def _flatten(items):
    for item in items:
        if isinstance(item, list):
            yield from _flatten(item)
        else:
            yield item


def _describe(item) -> str:
    """Стабильный текстовый ключ расхождения (не зависит от порядка и от объектов SQLAlchemy)."""
    kind = item[0]
    if kind in ("add_index", "remove_index"):
        index = item[1]
        return f"{kind} {index.table.name}({','.join(column.name for column in index.columns)}) {index.name}"
    if kind == "modify_nullable":
        _, _schema, table, column, _kw, existing, new = item
        return f"modify_nullable {table}.{column}: db={'NULL' if existing else 'NOT NULL'} model={'NULL' if new else 'NOT NULL'}"
    if kind == "modify_type":
        _, _schema, table, column, _kw, existing, new = item
        return f"modify_type {table}.{column}: db={existing} model={new}"
    if kind in ("add_column", "remove_column"):
        return f"{kind} {item[2]}.{item[3].name}"
    if kind in ("add_table", "remove_table"):
        return f"{kind} {item[1].name}"
    if kind in ("add_constraint", "remove_constraint"):
        constraint = item[1]
        return f"{kind} {type(constraint).__name__} {constraint.table.name}.{constraint.name}"
    if kind in ("add_fk", "remove_fk"):
        fk = item[1]
        return f"{kind} {fk.parent.name if getattr(fk, 'parent', None) is not None else fk}"
    return f"{kind} {item[1:]!r}"[:200]


def schema_drift(engine: sa.engine.Engine, metadata: sa.MetaData = Base.metadata) -> set[str]:
    """Расхождения между базой и metadata; compare_type — как в alembic/env.py."""
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return {_describe(item) for item in _flatten(compare_metadata(context, metadata))}


def _assert_matches_whitelist(drift: set[str], expected: set[str]) -> None:
    new, fixed = sorted(drift - expected), sorted(expected - drift)
    problems = []
    if new:
        problems.append(
            "Схема из миграций разошлась с models.py. Нужна миграция (alembic revision) — НЕ дописывайте строки в whitelist:\n  "
            + "\n  ".join(new)
        )
    if fixed:
        problems.append("Эти расхождения уже исправлены — удалите их из whitelist, чтобы страж не молчал о новых:\n  " + "\n  ".join(fixed))
    assert not problems, "\n\n".join(problems)


def _models_copy() -> sa.MetaData:
    """Копия metadata, которую можно портить в тесте, не трогая глобальные модели."""
    copy = sa.MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(copy)
    return copy


# ----------------------------------------------------------------------------------------------------------------------
# Общие проверки (вызываются и на SQLite, и на PostgreSQL)
# ----------------------------------------------------------------------------------------------------------------------

def _check_guard(url: str, expected: set[str]) -> None:
    engine = sa.create_engine(url)
    try:
        _assert_matches_whitelist(schema_drift(engine), expected)
        # Страж обязан ловить новое поле модели без миграции (иначе whitelist превратился бы в заглушку).
        broken = _models_copy()
        broken.tables["manufacturers"].append_column(sa.Column("a14_probe_without_migration", sa.String(10)))
        assert "add_column manufacturers.a14_probe_without_migration" in schema_drift(engine, broken)
        broken_table = _models_copy()
        sa.Table("a14_probe_table_without_migration", broken_table, sa.Column("id", sa.Integer, primary_key=True))
        assert "add_table a14_probe_table_without_migration" in schema_drift(engine, broken_table)
    finally:
        engine.dispose()


def _check_roundtrip(url: str) -> None:
    """`upgrade head → downgrade -1 → upgrade head` проходит и возвращает ту же схему (критерий приёмки A-14)."""
    engine = sa.create_engine(url)
    try:
        _migrate(url)
        before = schema_drift(engine)
        _migrate(url, "-1", downgrade=True)
        _migrate(url)
        assert schema_drift(engine) == before
    finally:
        engine.dispose()


def _check_missing_indexes_are_created(url: str) -> None:
    """Индексы внешних ключей, добавленные миграцией c5d2e8a4b713, действительно есть на цепочке из миграций."""
    engine = sa.create_engine(url)
    try:
        inspector = sa.inspect(engine)
        for table, column in (
            ("containers", "physical_device_id"),
            ("vlan_domain_devices", "domain_id"),
            ("vlan_domain_devices", "physical_device_id"),
            ("vlan_domains", "source_device_id"),
            ("information_systems", "support_method_id"),
            ("information_systems", "crypto_protection_description_id"),
            ("information_systems", "support_organization_id"),
        ):
            assert any(list(index["column_names"]) == [column] for index in inspector.get_indexes(table)), (table, column)
    finally:
        engine.dispose()


# ----------------------------------------------------------------------------------------------------------------------
# SQLite
# ----------------------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sqlite_url():
    with tempfile.TemporaryDirectory() as directory:
        url = f"sqlite:///{Path(directory) / 'migrated.db'}"
        _migrate(url)
        yield url


@pytest.mark.sqlite_only
def test_sqlite_schema_from_migrations_matches_models(sqlite_url):
    _check_guard(sqlite_url, COMMON | SQLITE_ONLY)


@pytest.mark.sqlite_only
def test_sqlite_missing_foreign_key_indexes_exist(sqlite_url):
    _check_missing_indexes_are_created(sqlite_url)


@pytest.mark.sqlite_only
def test_sqlite_upgrade_downgrade_upgrade_roundtrip():
    with tempfile.TemporaryDirectory() as directory:
        _check_roundtrip(f"sqlite:///{Path(directory) / 'roundtrip.db'}")


@pytest.mark.sqlite_only
def test_the_index_migration_is_idempotent_on_sqlite():
    """Повторный запуск ревизии (база уже с индексами) ничего не ломает и не плодит дубли."""
    with tempfile.TemporaryDirectory() as directory:
        url = f"sqlite:///{Path(directory) / 'idempotent.db'}"
        _migrate(url)
        engine = sa.create_engine(url)
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("UPDATE alembic_version SET version_num = 'b3f7a1d95c24'")
            _migrate(url)
            indexes = sa.inspect(engine).get_indexes("containers")
            assert [index["name"] for index in indexes].count("ix_containers_physical_device_id") == 1
            assert sum(1 for index in indexes if list(index["column_names"]) == ["physical_device_id"]) == 1
        finally:
            engine.dispose()


# ----------------------------------------------------------------------------------------------------------------------
# PostgreSQL (INFRA_REGISTRY_TEST_DATABASE_URL)
# ----------------------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def postgres_database():
    from test_migrations_postgres import ScratchDatabase  # временная база на сервере из INFRA_REGISTRY_TEST_DATABASE_URL

    database = ScratchDatabase()
    try:
        database.upgrade("head")
        yield database
    finally:
        database.close()


@pytest.mark.postgres_only
def test_postgres_schema_from_migrations_matches_models(postgres_database):
    _check_guard(postgres_database.url, COMMON | POSTGRES_ONLY)


@pytest.mark.postgres_only
def test_postgres_missing_foreign_key_indexes_exist(postgres_database):
    _check_missing_indexes_are_created(postgres_database.url)


@pytest.mark.postgres_only
def test_postgres_upgrade_downgrade_upgrade_roundtrip():
    from test_migrations_postgres import ScratchDatabase

    database = ScratchDatabase()
    try:
        _check_roundtrip(database.url)
    finally:
        database.close()
