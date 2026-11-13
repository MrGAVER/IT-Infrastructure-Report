"""Тест-страж: схема после `alembic upgrade head` совпадает с models.py (A-14, R1-02).

Раньше CI этого не проверял, и схема из миграций тихо разошлась с моделями: у `created_at`/`updated_at` в базе из миграций
стоял NULLABLE, а модель обещает NOT NULL; часть индексов и ограничений существовала под другими именами или только в базе.
Пользовательские базы (EXE, PostgreSQL) строятся именно миграциями, а тесты по умолчанию — `create_all`, поэтому расхождение было
невидимо. Расхождения устранены миграцией `a7d3f1c8e925` и правкой моделей; белого списка больше нет.

Как работает. Применяем всю цепочку миграций к пустой базе и сравниваем результат с `Base.metadata` тем же механизмом, что
`alembic check` / `--autogenerate` (`compare_type=True` и тот же `include_object`, что в alembic/env.py). Каждое расхождение
превращается в строку-ключ; ожидаемых нет (`EXPECTED_DRIFT` пуст). Тест падает, если появилось любое расхождение: нужна миграция
(`alembic revision`) или правка модели, а не строка в `EXPECTED_DRIFT`.

SQLite: ограничения UNIQUE в сравнении пропускаются (безымянные UNIQUE SQLite отдаёт без имени, см. app/alembic_filters.py), поэтому
их наличие проверяет `test_sqlite_model_uniqueness_exists_in_the_database` — по колонкам, а не по именам.

Запуск: `pytest backend/tests/test_migrations_match_models.py` (SQLite);
        INFRA_REGISTRY_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/любая_база pytest backend/tests/test_migrations_match_models.py (PostgreSQL).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from migration_support import BACKEND_DIR, migrate

from app.alembic_filters import make_include_object
from app.models import Base

_migrate = migrate


# ----------------------------------------------------------------------------------------------------------------------
# Ожидаемые расхождения «миграции ↔ модели»: их нет (R1-02 код-ревью). Раньше здесь был белый список из 49 пунктов — NOT NULL у
# created_at/updated_at, индексы без описания в моделях, ограничения под разными именами; все они устранены миграцией и правкой
# моделей. Любое расхождение — ошибка: нужна миграция (или правка модели), а не строка в этом множестве.
# ----------------------------------------------------------------------------------------------------------------------
EXPECTED_DRIFT: set[str] = set()


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
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "include_object": make_include_object(connection.dialect.name)}
        )
        return {_describe(item) for item in _flatten(compare_metadata(context, metadata))}


def _assert_matches_whitelist(drift: set[str], expected: set[str]) -> None:
    new, fixed = sorted(drift - expected), sorted(expected - drift)
    problems = []
    if new:
        problems.append(
            "Схема из миграций разошлась с models.py. Нужна миграция (alembic revision) или правка модели — НЕ дописывайте строки в EXPECTED_DRIFT:\n  "
            + "\n  ".join(new)
        )
    if fixed:
        problems.append("Эти расхождения уже исправлены — удалите их из EXPECTED_DRIFT, чтобы страж не молчал о новых:\n  " + "\n  ".join(fixed))
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
    _check_guard(sqlite_url, EXPECTED_DRIFT)


@pytest.mark.sqlite_only
def test_sqlite_missing_foreign_key_indexes_exist(sqlite_url):
    _check_missing_indexes_are_created(sqlite_url)


def _uniqueness_declared_by_models(metadata: sa.MetaData) -> dict[str, set[frozenset[str]]]:
    """Таблица → наборы колонок, которые модели объявляют уникальными (UniqueConstraint, `unique=True`, unique-индексы)."""
    result: dict[str, set[frozenset[str]]] = {}
    for table in metadata.tables.values():
        keys = {frozenset(column.name for column in constraint.columns) for constraint in table.constraints if isinstance(constraint, sa.UniqueConstraint)}
        keys |= {frozenset(column.name for column in index.columns) for index in table.indexes if index.unique}
        if keys:
            result[table.name] = keys
    return result


def missing_uniqueness(engine: sa.engine.Engine, metadata: sa.MetaData = Base.metadata) -> list[str]:
    """Уникальности из моделей, которых нет в базе ни как ограничение, ни как unique-индекс над теми же колонками (имена не важны)."""
    inspector = sa.inspect(engine)
    missing = []
    for table, wanted in _uniqueness_declared_by_models(metadata).items():
        present = {frozenset(item["column_names"]) for item in inspector.get_unique_constraints(table)}
        present |= {frozenset(item["column_names"]) for item in inspector.get_indexes(table) if item["unique"]}
        missing += [f"{table}({', '.join(sorted(columns))})" for columns in wanted - present]
    return sorted(missing)


@pytest.mark.sqlite_only
def test_sqlite_model_uniqueness_exists_in_the_database(sqlite_url):
    """Фильтр `include_object` не сравнивает UNIQUE на SQLite — эта проверка закрывает пробел: уникальность каждой модели есть в базе."""
    engine = sa.create_engine(sqlite_url)
    try:
        assert missing_uniqueness(engine) == []
        # Проверка обязана ловить пропажу (иначе она бесполезна): модель, требующая уникальности там, где её нет, даёт расхождение.
        broken = _models_copy()
        broken.tables["ip_addresses"].append_constraint(sa.UniqueConstraint("purpose", name="uq_probe_without_migration"))
        assert missing_uniqueness(engine, broken) == ["ip_addresses(purpose)"]
    finally:
        engine.dispose()


def test_ci_runs_alembic_check_on_sqlite_and_postgres():
    """`alembic check` — часть слияния: шаги в CI не должны пропасть при правке workflow (R1-02)."""
    import yaml

    workflow = yaml.safe_load((BACKEND_DIR.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    for job in ("test", "test-postgres-migrations"):
        runs = [step.get("run", "") for step in workflow["jobs"][job]["steps"]]
        assert any("alembic upgrade head" in run and "alembic check" in run for run in runs), f"в job {job} нет шага alembic check"


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
    _check_guard(postgres_database.url, EXPECTED_DRIFT)


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
