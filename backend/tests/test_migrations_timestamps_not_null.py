"""R1-02 код-ревью: миграция a7d3f1c8e925 переводит created_at/updated_at в NOT NULL, не потеряв ни данных, ни остальной схемы.

Что проверяется (одним сценарием на SQLite и на PostgreSQL):
  • строки с NULL в метках времени получают значения: created_at — текущий момент UTC, updated_at — created_at той же строки;
    уже заполненные значения не меняются;
  • ни одна строка не пропала, в том числе дочерние (auth_sessions → users, diagram_layouts → saved_diagrams): пересборка таблицы
    в SQLite при включённых внешних ключах каскадно стёрла бы их;
  • схема не изменилась ничем, кроме NOT NULL у перечисленных колонок (колонки, внешние ключи с ON DELETE, индексы, уникальные
    ограничения); триггеры защиты источников ИС на месте;
  • downgrade возвращает NULLABLE и тоже не теряет строки.

Запуск: pytest backend/tests/test_migrations_timestamps_not_null.py (SQLite);
        INFRA_REGISTRY_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/любая_база pytest ... (PostgreSQL).
"""
from __future__ import annotations

import importlib.util
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from migration_support import BACKEND_DIR, insert_row, migrate

PREVIOUS = "e4b1c7d9a362"
MIGRATION_FILE = BACKEND_DIR / "alembic" / "versions" / "a7d3f1c8e925_timestamps_not_null.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("a7d3f1c8e925_timestamps_not_null", MIGRATION_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION = _load_migration()
T0 = datetime(2024, 5, 17, 9, 30, 0)  # заведомо «старая» метка: после миграции она обязана остаться как есть


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ----------------------------------------------------------------------------------------------------------------------
# Снимок схемы и данных
# ----------------------------------------------------------------------------------------------------------------------

def _relaxed(table: str, column: str) -> bool:
    return column in MIGRATION.TIMESTAMP_COLUMNS.get(table, ())


def schema_snapshot(engine: sa.engine.Engine) -> dict[str, dict]:
    """Описание схемы без признака NOT NULL у колонок из миграции — его она и меняет."""
    inspector = sa.inspect(engine)
    snapshot: dict[str, dict] = {}
    for table in sorted(inspector.get_table_names()):
        columns = [
            (c["name"], str(c["type"]), None if _relaxed(table, c["name"]) else c["nullable"], str(c.get("default")))
            for c in inspector.get_columns(table)
        ]
        foreign_keys = sorted(
            (fk.get("name") or "", tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]), (fk.get("options") or {}).get("ondelete") or "")
            for fk in inspector.get_foreign_keys(table)
        )
        indexes = sorted((i["name"], tuple(i["column_names"]), bool(i["unique"])) for i in inspector.get_indexes(table))
        uniques = sorted((u.get("name") or "", tuple(u["column_names"])) for u in inspector.get_unique_constraints(table))
        snapshot[table] = {
            "columns": columns,
            "primary_key": tuple(inspector.get_pk_constraint(table)["constrained_columns"]),
            "foreign_keys": foreign_keys,
            "indexes": indexes,
            "uniques": uniques,
        }
    return snapshot


def row_counts(engine: sa.engine.Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {table: connection.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar() for table in sorted(sa.inspect(connection).get_table_names())}


def nullability(engine: sa.engine.Engine) -> dict[tuple[str, str], bool]:
    inspector = sa.inspect(engine)
    return {
        (table, column): next(c["nullable"] for c in inspector.get_columns(table) if c["name"] == column)
        for table, columns in MIGRATION.TIMESTAMP_COLUMNS.items()
        for column in columns
    }


def sqlite_triggers(engine: sa.engine.Engine) -> list[str]:
    with engine.connect() as connection:
        return sorted(row[0] for row in connection.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'")))


# ----------------------------------------------------------------------------------------------------------------------
# Сценарий
# ----------------------------------------------------------------------------------------------------------------------

def _seed_rows_with_null_timestamps(engine: sa.engine.Engine) -> dict[str, str]:
    """Строки на схеме ПРЕДЫДУЩЕЙ ревизии: часть с NULL в метках времени, часть с явными значениями, плюс дочерние строки каскадов."""
    ids: dict[str, str] = {}
    with engine.begin() as connection:
        ids["user"] = insert_row(connection, "users", created_at=None, updated_at=None)
        ids["session"] = insert_row(connection, "auth_sessions", user_id=ids["user"], created_at=None)
        ids["diagram"] = insert_row(connection, "saved_diagrams", created_at=T0, updated_at=None)  # updated_at обязан стать T0
        ids["layout"] = insert_row(connection, "diagram_layouts", saved_diagram_id=ids["diagram"], created_at=None, updated_at=None)
        ids["method_kept"] = insert_row(connection, "support_methods", created_at=T0, updated_at=T0 + timedelta(days=3))
        ids["settings"] = insert_row(connection, "auth_settings", id="singleton", updated_at=None)  # синглтон: id задан моделью
    return ids


def _fetch(engine: sa.engine.Engine, table: str, row_id: str) -> dict:
    with engine.connect() as connection:
        return dict(connection.execute(sa.text(f'SELECT * FROM "{table}" WHERE id = :i'), {"i": row_id}).mappings().one())


def _as_datetime(value) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def run_scenario(url: str) -> None:
    engine = sa.create_engine(url)
    try:
        migrate(url, PREVIOUS)
        nullable_before = nullability(engine)
        assert any(nullable_before.values()), "тест бессмыслен: на предыдущей ревизии все метки времени уже NOT NULL"
        ids = _seed_rows_with_null_timestamps(engine)
        schema_before, counts_before = schema_snapshot(engine), row_counts(engine)
        triggers_before = sqlite_triggers(engine) if engine.dialect.name == "sqlite" else []
        started = _utc_now()

        migrate(url, "head")
        finished = _utc_now()

        # 1. Все перечисленные колонки стали NOT NULL.
        assert not [key for key, nullable in nullability(engine).items() if nullable]

        # 2. NULL заполнены, заполненное сохранено.
        user, session, layout = (_fetch(engine, t, ids[k]) for t, k in (("users", "user"), ("auth_sessions", "session"), ("diagram_layouts", "layout")))
        for value in (user["created_at"], session["created_at"], layout["created_at"]):
            assert started - timedelta(seconds=1) <= _as_datetime(value) <= finished + timedelta(seconds=1)
        assert _as_datetime(user["updated_at"]) == _as_datetime(user["created_at"])
        assert _as_datetime(layout["updated_at"]) == _as_datetime(layout["created_at"])
        diagram = _fetch(engine, "saved_diagrams", ids["diagram"])
        assert _as_datetime(diagram["created_at"]) == T0 and _as_datetime(diagram["updated_at"]) == T0
        kept = _fetch(engine, "support_methods", ids["method_kept"])
        assert (_as_datetime(kept["created_at"]), _as_datetime(kept["updated_at"])) == (T0, T0 + timedelta(days=3))
        assert started - timedelta(seconds=1) <= _as_datetime(_fetch(engine, "auth_settings", ids["settings"])["updated_at"]) <= finished + timedelta(seconds=1)

        # 3. Ни одна строка не пропала (в том числе дочерние), схема не изменилась ничем, кроме NOT NULL.
        assert row_counts(engine) == counts_before
        assert schema_snapshot(engine) == schema_before
        if engine.dialect.name == "sqlite":
            assert sqlite_triggers(engine) == triggers_before and triggers_before, "триггеры защиты источников ИС пропали"

        # 4. Downgrade возвращает NULLABLE и не теряет строки; повторный upgrade снова чист.
        migrate(url, PREVIOUS, downgrade=True)
        assert nullability(engine) == nullable_before
        assert row_counts(engine) == counts_before
        migrate(url, "head")
        assert row_counts(engine) == counts_before
        assert not [key for key, nullable in nullability(engine).items() if nullable]
    finally:
        engine.dispose()


@pytest.mark.sqlite_only
def test_sqlite_null_timestamps_are_filled_and_nothing_else_changes():
    with tempfile.TemporaryDirectory() as directory:
        run_scenario(f"sqlite:///{Path(directory) / 'timestamps.db'}")


@pytest.mark.postgres_only
def test_postgres_null_timestamps_are_filled_and_nothing_else_changes():
    from test_migrations_postgres import ScratchDatabase

    database = ScratchDatabase()
    try:
        run_scenario(database.url)
    finally:
        database.close()


# ----------------------------------------------------------------------------------------------------------------------
# SQLite: внешние ключи и защитные проверки
# ----------------------------------------------------------------------------------------------------------------------

def _upgrade_through_operations(connection: sa.engine.Connection) -> None:
    """Выполняет upgrade() миграции на УЖЕ открытом соединении (так можно проверить миграцию при включённых внешних ключах)."""
    with Operations.context(MigrationContext.configure(connection)):
        MIGRATION.upgrade()


@pytest.mark.sqlite_only
def test_sqlite_children_survive_even_if_the_connection_enforces_foreign_keys():
    """Если соединение открыто с PRAGMA foreign_keys=ON, миграция сама выключает ключи: иначе DROP TABLE users каскадно стёр бы сессии."""
    with tempfile.TemporaryDirectory() as directory:
        url = f"sqlite:///{Path(directory) / 'fk_on.db'}"
        migrate(url, PREVIOUS)
        engine = sa.create_engine(url)
        try:
            ids = _seed_rows_with_null_timestamps(engine)
            counts_before = row_counts(engine)

            strict = sa.create_engine(url)  # отдельный движок: слушатель обязан сработать на первом же соединении

            @sa.event.listens_for(strict, "connect")
            def _enforce_foreign_keys(dbapi_connection, _record):
                dbapi_connection.execute("PRAGMA foreign_keys=ON")

            try:
                with strict.connect() as connection:
                    assert connection.execute(sa.text("PRAGMA foreign_keys")).scalar() == 1
                    _upgrade_through_operations(connection)
                    connection.commit()
            finally:
                strict.dispose()
            assert row_counts(engine) == counts_before
            assert _fetch(engine, "auth_sessions", ids["session"])["user_id"] == ids["user"]
        finally:
            engine.dispose()


class _FakeBind:
    """Соединение, на котором внешние ключи не выключаются (как внутри открытой транзакции)."""

    def execute(self, statement):
        class _Result:
            @staticmethod
            def scalar():
                return 1

        return _Result()


def test_migration_refuses_to_rebuild_tables_when_foreign_keys_cannot_be_disabled():
    with pytest.raises(RuntimeError, match="внешние ключи SQLite"):
        MIGRATION._disable_sqlite_foreign_keys(_FakeBind())


@pytest.mark.sqlite_only
def test_sqlite_migration_refuses_to_drop_triggers_silently():
    with tempfile.TemporaryDirectory() as directory:
        url = f"sqlite:///{Path(directory) / 'triggers.db'}"
        migrate(url, PREVIOUS)
        engine = sa.create_engine(url)
        try:
            with engine.begin() as connection:
                connection.execute(sa.text("CREATE TRIGGER trg_probe AFTER INSERT ON users BEGIN SELECT 1; END"))
                with pytest.raises(RuntimeError, match="триггеры SQLite"):
                    MIGRATION._assert_no_triggers_on(connection, "users")
                MIGRATION._assert_no_triggers_on(connection, "support_methods")  # у таблицы без триггеров — тихо
        finally:
            engine.dispose()


def test_migration_covers_every_timestamp_column_the_models_require():
    """Список миграции не должен отставать от моделей: колонки-метки времени, которые модель объявляет обязательными, перечислены."""
    from app.models import Base

    required = {
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.name in ("created_at", "updated_at") and not column.nullable
    }
    listed = {(table, column) for table, columns in MIGRATION.TIMESTAMP_COLUMNS.items() for column in columns}
    # Таблицы, где NOT NULL задан с самого начала (и в миграциях), в списке не нужны, но всё из списка обязано быть в моделях.
    assert listed <= required, sorted(listed - required)
