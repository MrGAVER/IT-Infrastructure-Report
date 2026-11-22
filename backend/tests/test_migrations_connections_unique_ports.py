"""
Тесты миграции e3b7a15c9d42 — частичные уникальные индексы `uq_connections_source_active` и `uq_connections_destination_active`, A-01 (этап
2) код-ревью main @ b375f58.

Миграция сначала ищет в данных активные подключения с общим портом в одной роли (источник или назначение) и, если они есть, останавливается
с перечнем портов и id подключений: НИЧЕГО не удаляя и не меняя — какое из двух подключений настоящее, решает человек. Неактивные
подключения индексам не мешают.
Сценарии одинаковы для SQLite (файл-БД, sqlite_only) и PostgreSQL (временная база на сервере из INFRA_REGISTRY_TEST_DATABASE_URL,
postgres_only) — фикстура
`database` та же, что у тестов c4a9e2d7b185 (connection_support.scratch_database).

Запуск: pytest backend/tests/test_migrations_connections_unique_ports.py -v
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from connection_support import Database, scratch_database
from migration_support import insert_row

PRE_REVISION = "c4a9e2d7b185"
TARGET_REVISION = "e3b7a15c9d42"
SOURCE_INDEX = "uq_connections_source_active"
DESTINATION_INDEX = "uq_connections_destination_active"


@pytest.fixture(
    params=[
        pytest.param("sqlite", marks=pytest.mark.sqlite_only),
        pytest.param("postgres", marks=pytest.mark.postgres_only),
    ]
)
def database(request, tmp_path):
    with scratch_database(request.param, tmp_path) as db:
        yield db


def _connect(connection: sa.Connection, source: str, destination: str, *, active: bool = True) -> str:
    return insert_row(connection, "connections", source_interface_id=source, destination_interface_id=destination, is_active=active)


def _seed_clean(db: Database) -> list[str]:
    """Данные, которые индексам не мешают: обычное подключение и ТРИ неактивных на одном и том же порту (архив) рядом с одним активным."""
    ids: list[str] = []
    with db.engine.begin() as connection:
        a, b, c, d, e = (insert_row(connection, "device_interfaces") for _ in range(5))
        ids.append(_connect(connection, a, b))
        ids.append(_connect(connection, c, d, active=False))
        ids.append(_connect(connection, c, e, active=False))  # общий источник c — но оба неактивны
        ids.append(_connect(connection, e, d, active=False))  # общее назначение d — тоже неактивно
    return ids


def _seed_shared_port(db: Database, role: str) -> dict[str, list[str]]:
    """Два активных подключения с общим портом в роли `role` ('source' | 'destination') и одно обычное; возвращает {'port': [...],
    'connections': [...]}."""
    with db.engine.begin() as connection:
        shared, first, second, x, y = (insert_row(connection, "device_interfaces") for _ in range(5))
        _connect(connection, x, y)
        if role == "source":
            ids = [_connect(connection, shared, first), _connect(connection, shared, second)]
        else:
            ids = [_connect(connection, first, shared), _connect(connection, second, shared)]
    return {"port": [shared], "connections": ids}


def _count(db: Database) -> int:
    with db.engine.connect() as connection:
        return connection.execute(sa.text("SELECT count(*) FROM connections")).scalar_one()


def _version(db: Database) -> str:
    with db.engine.connect() as connection:
        return connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()


def _indexes(db: Database) -> set[str]:
    return {index["name"] for index in sa.inspect(db.engine).get_indexes("connections")}


def _insert_second_active_on_source(db: Database) -> None:
    with db.engine.begin() as connection:
        shared, first, second = (insert_row(connection, "device_interfaces") for _ in range(3))
        _connect(connection, shared, first)
        _connect(connection, shared, second)


def test_upgrade_creates_both_indexes_and_keeps_all_rows_including_inactive_duplicates(database):
    database.migrate(PRE_REVISION)
    ids = _seed_clean(database)
    before = _indexes(database)
    assert not {SOURCE_INDEX, DESTINATION_INDEX} & before

    database.migrate(TARGET_REVISION)

    assert _version(database) == TARGET_REVISION
    assert _count(database) == len(ids), "ни одно подключение (в том числе неактивное с общим портом) не тронуто"
    assert _indexes(database) == before | {SOURCE_INDEX, DESTINATION_INDEX}
    unique = {index["name"] for index in sa.inspect(database.engine).get_indexes("connections") if index["unique"]}
    assert {SOURCE_INDEX, DESTINATION_INDEX} <= unique


def test_indexes_work_after_upgrade(database):
    database.migrate(PRE_REVISION)
    database.migrate(TARGET_REVISION)

    with pytest.raises(IntegrityError) as caught:
        _insert_second_active_on_source(database)

    message = str(caught.value)
    assert SOURCE_INDEX in message or "connections.source_interface_id" in message  # PostgreSQL называет индекс, SQLite — колонку
    assert _count(database) == 0, "вставка откатилась целиком"


@pytest.mark.parametrize("role", ["source", "destination"])
def test_upgrade_stops_on_a_port_shared_by_active_connections_and_changes_nothing(database, role):
    database.migrate(PRE_REVISION)
    shared = _seed_shared_port(database, role)
    before = _indexes(database)
    rows = _count(database)

    with pytest.raises(RuntimeError) as caught:
        database.migrate(TARGET_REVISION)

    message = str(caught.value)
    assert ("как источник" if role == "source" else "как назначение") in message
    assert shared["port"][0] in message, "в сообщении — id порта, занятого дважды"
    assert all(connection_id in message for connection_id in shared["connections"]), (
        "и id обоих подключений, чтобы человек мог выбрать, какое оставить"
    )
    assert "в БД ничего не изменено" in message
    assert _version(database) == PRE_REVISION, "версия схемы не сдвинулась"
    assert _count(database) == rows, "ничего не удалено и не изменено автоматически"
    assert _indexes(database) == before, "ни один индекс не создан (в том числе тот, чьё правило данные не нарушают)"


def test_upgrade_passes_after_the_duplicate_is_deactivated(database):
    database.migrate(PRE_REVISION)
    shared = _seed_shared_port(database, "source")
    with pytest.raises(RuntimeError):
        database.migrate(TARGET_REVISION)

    with database.engine.begin() as connection:  # человек отключает лишнее подключение (но не удаляет)
        connection.execute(
            sa.text("UPDATE connections SET is_active = :off WHERE id = :id"), {"off": False, "id": shared["connections"][1]}
        )
    database.migrate(TARGET_REVISION)

    assert _version(database) == TARGET_REVISION
    assert {SOURCE_INDEX, DESTINATION_INDEX} <= _indexes(database)


def test_downgrade_drops_both_indexes_and_keeps_the_data(database):
    database.migrate(PRE_REVISION)
    ids = _seed_clean(database)
    before = _indexes(database)
    database.migrate(TARGET_REVISION)

    database.migrate(PRE_REVISION, downgrade=True)

    assert _version(database) == PRE_REVISION
    assert _count(database) == len(ids)
    assert _indexes(database) == before
    _insert_second_active_on_source(database)  # индексов больше нет — дубль вставляется (CHECK c4a9e2d7b185 остаётся, но он про другое)
