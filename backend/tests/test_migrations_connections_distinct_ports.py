"""
Тесты миграции c4a9e2d7b185 — CHECK `ck_connections_distinct_ports` (порт не может быть подключён сам к себе), A-01 код-ревью main @ b375f58.

Миграция сначала ищет в данных подключения «порт сам с собой» и, если они есть, останавливается с перечнем id: НИЧЕГО не удаляя и не меняя — данные чинит человек.
Только после этого добавляет ограничение (на SQLite — пересборкой таблицы через batch, на PostgreSQL — ALTER TABLE). Сценарии одинаковы для обеих СУБД:
SQLite-вариант идёт на файле-БД (sqlite_only), PostgreSQL-вариант — во временной базе на сервере из INFRA_REGISTRY_TEST_DATABASE_URL (postgres_only).

Запуск: pytest backend/tests/test_migrations_connections_distinct_ports.py -v
"""

from __future__ import annotations


import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from connection_support import Database, scratch_database
from migration_support import insert_row

PRE_REVISION = "a7d3f1c8e925"
TARGET_REVISION = "c4a9e2d7b185"
CONSTRAINT = "ck_connections_distinct_ports"


@pytest.fixture(
    params=[
        pytest.param("sqlite", marks=pytest.mark.sqlite_only),
        pytest.param("postgres", marks=pytest.mark.postgres_only),
    ]
)
def database(request, tmp_path):
    with scratch_database(request.param, tmp_path) as db:
        yield db


def _version(db: Database) -> str:
    with db.engine.connect() as connection:
        return connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()


def _count(db: Database) -> int:
    with db.engine.connect() as connection:
        return connection.execute(sa.text("SELECT count(*) FROM connections")).scalar_one()


def _seed(db: Database, *, loops: int = 0, inactive_loop: bool = False) -> dict[str, list[str]]:
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


def _insert_loop(db: Database) -> None:
    with db.engine.begin() as connection:
        port = insert_row(connection, "device_interfaces")
        insert_row(connection, "connections", source_interface_id=port, destination_interface_id=port, is_active=True)


def _structure(db: Database) -> tuple[set[str], set[tuple[str, str]]]:
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


def _check_constraint_names(db: Database) -> list[str]:
    return [constraint["name"] for constraint in sa.inspect(db.engine).get_check_constraints("connections") if constraint["name"]]


def test_upgrade_skips_a_constraint_that_already_exists(database):
    """База создана по моделям (create_all + stamp) или ревизия запущена повторно: ограничение уже есть. Как и соседние миграции,
    эта пропускает его, а не падает на ALTER TABLE … ADD CONSTRAINT с занятым именем (PostgreSQL) и не плодит копию (SQLite)."""
    database.migrate(TARGET_REVISION)
    assert _check_constraint_names(database) == [CONSTRAINT]
    with database.engine.begin() as connection:
        # схема прежняя «по версии», ограничение на месте
        connection.execute(sa.text("UPDATE alembic_version SET version_num = :revision"), {"revision": PRE_REVISION})

    database.migrate(TARGET_REVISION)

    assert _version(database) == TARGET_REVISION
    assert _check_constraint_names(database) == [CONSTRAINT], "ограничение одно"
    with pytest.raises(IntegrityError):
        _insert_loop(database)
