"""
Тесты миграции d6c1a8f3e594 — таблица настроек аудита `audit_settings` (срок хранения журнала), A-05 код-ревью main @ b375f58.

Миграция только добавляет таблицу: строку настроек не создаёт (без неё действует «не удалять»), в audit_log ничего не меняет.
Сценарии одинаковы для SQLite (файл-БД, sqlite_only) и PostgreSQL (временная база из INFRA_REGISTRY_TEST_DATABASE_URL,
postgres_only) — фикстура `database` та
же, что у тестов e3b7a15c9d42.

Запуск: pytest backend/tests/test_migrations_audit_settings.py -v
"""

from __future__ import annotations

from datetime import datetime

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from connection_support import Database, scratch_database
from migration_support import alembic_config, insert_row

PRE_REVISION = "e3b7a15c9d42"
TARGET_REVISION = "d6c1a8f3e594"
TABLE = "audit_settings"


@pytest.fixture(
    params=[
        pytest.param("sqlite", marks=pytest.mark.sqlite_only),
        pytest.param("postgres", marks=pytest.mark.postgres_only),
    ]
)
def database(request, tmp_path):
    with scratch_database(request.param, tmp_path) as db:
        yield db


def _tables(db: Database) -> set[str]:
    return set(sa.inspect(db.engine).get_table_names())


def _version(db: Database) -> str:
    with db.engine.connect() as connection:
        return connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()


def _audit_entries(db: Database) -> int:
    with db.engine.connect() as connection:
        return connection.execute(sa.text("SELECT count(*) FROM audit_log")).scalar_one()


def _insert_settings(db: Database, **values) -> None:
    with db.engine.begin() as connection:
        connection.execute(
            sa.text(f"INSERT INTO {TABLE} (id, retention_days, last_cleanup_at, updated_at) VALUES ('singleton', :days, :cleanup, :now)"),
            {"days": values.get("retention_days"), "cleanup": values.get("last_cleanup_at"), "now": datetime(2026, 11, 15)},
        )


def test_the_migration_continues_the_single_chain():
    """Миграция продолжает цепочку, а сама цепочка остаётся линейной (одна голова). Позже в неё добавляются новые миграции, поэтому
    «голова» — не эта ревизия: проверяется, что она лежит на пути к голове."""
    script = ScriptDirectory.from_config(alembic_config())
    assert script.get_revision(TARGET_REVISION).down_revision == PRE_REVISION
    (head,) = script.get_heads()
    assert TARGET_REVISION in {revision.revision for revision in script.iterate_revisions(head, PRE_REVISION)}


def test_upgrade_creates_an_empty_settings_table_and_keeps_the_audit_log(database):
    database.migrate(PRE_REVISION)
    assert TABLE not in _tables(database)
    with database.engine.begin() as connection:
        for index in range(3):
            insert_row(connection, "audit_log", entity_type="devices", entity_id=f"e{index}", action="UPDATE", details="запись")

    database.migrate(TARGET_REVISION)

    assert _version(database) == TARGET_REVISION
    columns = {column["name"]: column for column in sa.inspect(database.engine).get_columns(TABLE)}
    assert set(columns) == {"id", "retention_days", "last_cleanup_at", "updated_at"}
    assert columns["retention_days"]["nullable"] and columns["last_cleanup_at"]["nullable"] and not columns["updated_at"]["nullable"]
    with database.engine.connect() as connection:
        assert connection.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 0, (
            "строку настроек создаёт приложение, а не миграция"
        )
    assert _audit_entries(database) == 3, "записи журнала не тронуты"


def test_the_table_rejects_a_negative_retention(database):
    database.migrate(TARGET_REVISION)

    with pytest.raises(IntegrityError):
        _insert_settings(database, retention_days=-1)
    _insert_settings(database, retention_days=0)  # 0 — «не удалять» — допустим

    with database.engine.connect() as connection:
        assert connection.execute(sa.text(f"SELECT retention_days FROM {TABLE}")).scalar_one() == 0


def test_null_retention_is_allowed_and_means_not_set(database):
    database.migrate(TARGET_REVISION)

    _insert_settings(database, retention_days=None)

    with database.engine.connect() as connection:
        assert connection.execute(sa.text(f"SELECT retention_days FROM {TABLE}")).scalar_one() is None


def test_upgrade_after_downgrade_creates_the_table_again(database):
    database.migrate(TARGET_REVISION)
    database.migrate(PRE_REVISION, downgrade=True)
    assert TABLE not in _tables(database)

    database.migrate(TARGET_REVISION)

    assert TABLE in _tables(database)


def test_upgrade_skips_a_table_that_already_exists(database):
    """Идемпотентность: база создана по моделям (таблица уже есть) или ревизию запускают повторно — готовая таблица и её данные не
    трогаются."""
    database.migrate(PRE_REVISION)
    with database.engine.begin() as connection:
        connection.execute(
            sa.text(
                f"CREATE TABLE {TABLE} (id VARCHAR(20) PRIMARY KEY, retention_days INTEGER, last_cleanup_at "
                "TIMESTAMP, updated_at TIMESTAMP NOT NULL)"
            )
        )
    _insert_settings(database, retention_days=30)

    database.migrate(TARGET_REVISION)

    assert _version(database) == TARGET_REVISION
    with database.engine.connect() as connection:
        assert connection.execute(sa.text(f"SELECT retention_days FROM {TABLE}")).scalar_one() == 30, "готовая таблица не пересоздана"


def test_downgrade_drops_the_table_and_keeps_the_audit_log(database):
    database.migrate(TARGET_REVISION)
    _insert_settings(database, retention_days=90)
    with database.engine.begin() as connection:
        insert_row(connection, "audit_log", entity_type="devices", entity_id="e", action="UPDATE", details="запись")

    database.migrate(PRE_REVISION, downgrade=True)

    assert _version(database) == PRE_REVISION
    assert TABLE not in _tables(database)
    assert _audit_entries(database) == 1
