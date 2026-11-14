"""
Тесты миграции c4a9e2d7b185 — CHECK `ck_connections_distinct_ports` (порт не может быть подключён сам к себе), A-01 код-ревью main @ b375f58.

Миграция сначала ищет в данных подключения «порт сам с собой» и, если они есть, останавливается с перечнем id: НИЧЕГО не удаляя и не меняя — данные чинит человек.
Только после этого добавляет ограничение (на SQLite — пересборкой таблицы через batch, на PostgreSQL — ALTER TABLE). Сценарии одинаковы для обеих СУБД:
SQLite-вариант идёт на файле-БД (sqlite_only), PostgreSQL-вариант — во временной базе на сервере из INFRA_REGISTRY_TEST_DATABASE_URL (postgres_only).

Запуск: pytest backend/tests/test_migrations_connections_distinct_ports.py -v
"""

from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from migration_support import insert_row, migrate

PRE_REVISION = "a7d3f1c8e925"
TARGET_REVISION = "c4a9e2d7b185"
CONSTRAINT = "ck_connections_distinct_ports"


class _Database:
    """Пустая база и её адрес; удаляется вместе с каталогом теста (SQLite) или командой DROP DATABASE (PostgreSQL)."""

    def __init__(self, url: str, engine: sa.Engine, cleanup=lambda: None) -> None:
        self.url, self.engine, self._cleanup = url, engine, cleanup

    def migrate(self, revision: str, *, downgrade: bool = False) -> None:
        migrate(self.url, revision, downgrade=downgrade)

    def close(self) -> None:
        self.engine.dispose()
        self._cleanup()


@pytest.fixture(
    params=[
        pytest.param("sqlite", marks=pytest.mark.sqlite_only),
        pytest.param("postgres", marks=pytest.mark.postgres_only),
    ]
)
def database(request, tmp_path):
    if request.param == "sqlite":
        url = f"sqlite:///{tmp_path / 'distinct_ports.db'}"
        db = _Database(url, sa.create_engine(url))
    else:
        admin = make_url(os.environ["INFRA_REGISTRY_TEST_DATABASE_URL"])
        name = f"infra_migr_{uuid.uuid4().hex[:10]}"
        admin_engine = sa.create_engine(admin.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        url = admin.set(database=name).render_as_string(hide_password=False)

        def drop() -> None:
            with admin_engine.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            admin_engine.dispose()

        db = _Database(url, sa.create_engine(url), drop)
    try:
        yield db
    finally:
        db.close()


def _version(db: _Database) -> str:
    with db.engine.connect() as connection:
        return connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()


def _count(db: _Database) -> int:
    with db.engine.connect() as connection:
        return connection.execute(sa.text("SELECT count(*) FROM connections")).scalar_one()


def _seed(db: _Database, *, loops: int = 0, inactive_loop: bool = False) -> dict[str, list[str]]:
    """Два обычных подключения (четыре разных порта) и, по запросу, подключения «порт сам с собой» (активные и/или неактивное)."""
    ids: dict[str, list[str]] = {"normal": [], "loop": []}
    with db.engine.begin() as connection:
        for _ in range(2):
            source, destination = insert_row(connection, "device_interfaces"), insert_row(connection, "device_interfaces")
            ids["normal"].append(insert_row(connection, "connections", source_interface_id=source, destination_interface_id=destination, is_active=True))
        for index in range(loops + int(inactive_loop)):
            port = insert_row(connection, "device_interfaces")
            active = index < loops
            ids["loop"].append(insert_row(connection, "connections", source_interface_id=port, destination_interface_id=port, is_active=active))
    return ids


def _insert_loop(db: _Database) -> None:
    with db.engine.begin() as connection:
        port = insert_row(connection, "device_interfaces")
        insert_row(connection, "connections", source_interface_id=port, destination_interface_id=port, is_active=True)


def _structure(db: _Database) -> tuple[set[str], set[tuple[str, str]]]:
    """Имена индексов и пары (колонка, родительская таблица) внешних ключей таблицы connections."""
    inspector = sa.inspect(db.engine)
    indexes = {index["name"] for index in inspector.get_indexes("connections")}
    foreign_keys = {(fk["constrained_columns"][0], fk["referred_table"]) for fk in inspector.get_foreign_keys("connections")}
    return indexes, foreign_keys


def test_upgrade_adds_the_constraint_and_keeps_rows_indexes_and_foreign_keys(database):
    database.migrate(PRE_REVISION)
    ids = _seed(database)
    before = _structure(database)
    assert before[0], "до миграции на connections есть индексы по портам"

    database.migrate(TARGET_REVISION)

    assert _version(database) == TARGET_REVISION
    assert _count(database) == len(ids["normal"]), "подключения сохранились"
    assert _structure(database) == before, "индексы и внешние ключи после пересборки таблицы те же"
    with pytest.raises(IntegrityError) as caught:
        _insert_loop(database)
    assert CONSTRAINT in str(caught.value)


def test_upgrade_stops_when_data_has_a_port_connected_to_itself_and_changes_nothing(database):
    database.migrate(PRE_REVISION)
    ids = _seed(database, loops=1, inactive_loop=True)  # ограничение действует и на неактивные строки — миграция проверяет все

    with pytest.raises(RuntimeError) as caught:
        database.migrate(TARGET_REVISION)

    message = str(caught.value)
    assert "порт сам с собой" in message
    assert all(loop_id in message for loop_id in ids["loop"]), "в сообщении — id всех проблемных подключений, чтобы данные можно было исправить вручную"
    assert _version(database) == PRE_REVISION, "версия схемы не сдвинулась"
    assert _count(database) == len(ids["normal"]) + len(ids["loop"]), "ничего не удалено и не изменено автоматически"
    _insert_loop(database)  # ограничения нет: схема осталась прежней


def test_upgrade_passes_after_the_data_is_fixed(database):
    database.migrate(PRE_REVISION)
    ids = _seed(database, loops=1)
    with pytest.raises(RuntimeError):
        database.migrate(TARGET_REVISION)

    with database.engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM connections WHERE id = :id"), {"id": ids["loop"][0]})
    database.migrate(TARGET_REVISION)

    assert _version(database) == TARGET_REVISION
    assert _count(database) == len(ids["normal"])


def test_downgrade_drops_the_constraint_and_keeps_the_data(database):
    database.migrate(PRE_REVISION)
    ids = _seed(database)
    before = _structure(database)
    database.migrate(TARGET_REVISION)

    database.migrate(PRE_REVISION, downgrade=True)

    assert _version(database) == PRE_REVISION
    assert _count(database) == len(ids["normal"])
    assert _structure(database) == before
    _insert_loop(database)  # ограничения больше нет
