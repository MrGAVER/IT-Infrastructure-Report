"""
A-01 (код-ревью main @ b375f58), этап 2: частичные уникальные индексы `uq_connections_source_active` и `uq_connections_destination_active`.

Активное подключение (`is_active`; колонка NOT NULL, так что это то же, что `IS NOT FALSE` в validate_connection) занимает порт в своей роли не более одного раза: порт не может быть
источником двух активных подключений и назначением двух активных подключений. Неактивные строки индекс не видит. Случай «порт — источник в одном подключении и назначение в другом»
индексом по одной колонке не выразить: его закрывают validate_connection и блокировка строк портов (этап 1, test_connection_invariants.py).

Главная сложность — обмен соседями в форме устройства: уникальный индекс не откладывается до конца транзакции, а применение плана идёт по одному подключению, и в
промежутке порт занят двумя подключениями. Поэтому sync_interface_connections на время применения плана выключает (is_active = false) подключения, которые переставляет, и
включает их обратно, когда все стоят на новых местах.

Запуск: pytest backend/tests/test_connection_unique_ports.py -v
"""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import Connection
from connection_support import make_world
from test_interface_connections import API, _by_ports, _conn, _connection_type, _connections, _device_with_ports, _sync


@pytest.fixture
def world(db_session):
    return make_world(db_session)


def _violates(caught, index: str, column: str) -> bool:
    """PostgreSQL называет в ошибке индекс, SQLite — колонку (`UNIQUE constraint failed: connections.<колонка>`)."""
    message = str(caught.value)
    return index in message or f"connections.{column}" in message


def _add(session, source: str, destination: str, type_id: str, *, active: bool = True) -> Connection:
    connection = Connection(source_interface_id=source, destination_interface_id=destination, connection_type_id=type_id, is_active=active)
    session.add(connection)
    return connection


class TestIndexes:
    def test_port_cannot_be_the_source_of_two_active_connections(self, world, db_session):
        a, b, c, _d = world.ports
        _add(db_session, a, b, world.type_id)
        db_session.commit()
        _add(db_session, a, c, world.type_id)
        with pytest.raises(IntegrityError) as caught:
            db_session.commit()
        assert _violates(caught, "uq_connections_source_active", "source_interface_id")
        db_session.rollback()

    def test_port_cannot_be_the_destination_of_two_active_connections(self, world, db_session):
        a, b, c, _d = world.ports
        _add(db_session, a, c, world.type_id)
        db_session.commit()
        _add(db_session, b, c, world.type_id)
        with pytest.raises(IntegrityError) as caught:
            db_session.commit()
        assert _violates(caught, "uq_connections_destination_active", "destination_interface_id")
        db_session.rollback()

    def test_inactive_connections_do_not_occupy_a_port(self, world, db_session):
        a, b, c, d = world.ports
        _add(db_session, a, b, world.type_id, active=False)
        _add(db_session, a, c, world.type_id, active=False)  # два неактивных с одним источником
        _add(db_session, a, d, world.type_id, active=True)  # и одно активное рядом с ними
        db_session.commit()
        assert db_session.query(Connection).count() == 3

    def test_port_may_be_source_in_one_connection_and_destination_in_another_for_the_index(self, world, db_session):
        # Индексы по одной колонке этого не запрещают — для такого случая есть validate_connection и блокировка строк портов (этап 1).
        a, b, c, _d = world.ports
        _add(db_session, a, b, world.type_id)
        _add(db_session, c, a, world.type_id)
        db_session.commit()
        assert db_session.query(Connection).count() == 2


class TestNeighbourSwapKeepsWorkingUnderTheIndexes:
    """Обмен соседями в одном запросе: в промежутке порт занят двумя подключениями, индекс этого не допускает — отсюда выключение на время применения."""

    def test_two_ports_swap_their_neighbours_and_connections_stay_active(self, client):
        _, theirs = _device_with_ports(client, "SW-U-SWAP", ["g1", "g2"])
        ct = _connection_type(client)
        dev, own = _device_with_ports(client, "SRV-U-SWAP", ["eth0", "eth1"])
        first = [
            {"id": own["eth0"]["id"], "name": "eth0", "connection": _conn(theirs["g1"], ct)},
            {"id": own["eth1"]["id"], "name": "eth1", "connection": _conn(theirs["g2"], ct)},
        ]
        assert _sync(client, dev["id"], first).status_code == 200
        ids = {c["id"] for c in _connections(client)}

        swapped = [
            {"id": own["eth0"]["id"], "name": "eth0", "connection": _conn(theirs["g2"], ct)},
            {"id": own["eth1"]["id"], "name": "eth1", "connection": _conn(theirs["g1"], ct)},
        ]
        response = _sync(client, dev["id"], swapped)

        assert response.status_code == 200, response.text
        after = _by_ports(client)
        assert set(after) == {frozenset((own["eth0"]["id"], theirs["g2"]["id"])), frozenset((own["eth1"]["id"], theirs["g1"]["id"]))}
        assert {c["id"] for c in after.values()} == ids, "подключения переставлены на месте, а не пересозданы"
        assert all(c["is_active"] is True for c in after.values()), "после обмена оба подключения снова активны"

    def test_three_ports_rotate_their_neighbours(self, client):
        _, theirs = _device_with_ports(client, "SW-U-ROT", ["g1", "g2", "g3"])
        ct = _connection_type(client)
        dev, own = _device_with_ports(client, "SRV-U-ROT", ["eth0", "eth1", "eth2"])
        names = ["eth0", "eth1", "eth2"]

        def payload(order: list[str]) -> list[dict]:
            return [{"id": own[name]["id"], "name": name, "connection": _conn(theirs[peer], ct)} for name, peer in zip(names, order)]

        assert _sync(client, dev["id"], payload(["g1", "g2", "g3"])).status_code == 200
        response = _sync(client, dev["id"], payload(["g2", "g3", "g1"]))  # циклический сдвиг: каждый занимает порт, который освобождает другой

        assert response.status_code == 200, response.text
        expected = {frozenset((own[name]["id"], theirs[peer]["id"])) for name, peer in zip(names, ["g2", "g3", "g1"])}
        assert set(_by_ports(client)) == expected
        assert all(c["is_active"] is True for c in _connections(client))

    def test_swap_works_when_the_connections_were_created_in_the_opposite_direction(self, client):
        """Подключения «сосед → порт» (порт — назначение): при обмене меняется источник, а не назначение — другой индекс."""
        _, theirs = _device_with_ports(client, "SW-U-REV", ["g1", "g2"])
        ct = _connection_type(client)
        dev, own = _device_with_ports(client, "SRV-U-REV", ["eth0", "eth1"])
        for remote, local in (("g1", "eth0"), ("g2", "eth1")):
            created = client.post(f"{API}/resources/connections", json={"source_interface_id": theirs[remote]["id"], "destination_interface_id": own[local]["id"], "connection_type_id": ct["id"]})
            assert created.status_code in (200, 201), created.text

        response = _sync(
            client,
            dev["id"],
            [
                {"id": own["eth0"]["id"], "name": "eth0", "connection": _conn(theirs["g2"], ct)},
                {"id": own["eth1"]["id"], "name": "eth1", "connection": _conn(theirs["g1"], ct)},
            ],
        )

        assert response.status_code == 200, response.text
        after = _connections(client)
        assert {(c["source_interface_id"], c["destination_interface_id"]) for c in after} == {
            (theirs["g2"]["id"], own["eth0"]["id"]),
            (theirs["g1"]["id"], own["eth1"]["id"]),
        }, "направление подключений сохранилось: источником остаётся порт соседа"
        assert all(c["is_active"] is True for c in after)

    def test_connection_whose_neighbour_does_not_change_is_not_switched_off(self, client, db_session):
        _, theirs = _device_with_ports(client, "SW-U-KEEP", ["g1"])
        ct = _connection_type(client)
        dev, own = _device_with_ports(client, "SRV-U-KEEP", ["eth0"])
        body = [{"id": own["eth0"]["id"], "name": "eth0", "connection": _conn(theirs["g1"], ct, "было")}]
        assert _sync(client, dev["id"], body).status_code == 200
        (before,) = _connections(client)

        body[0]["connection"]["description"] = "стало"  # меняется только описание: соседний порт тот же
        assert _sync(client, dev["id"], body).status_code == 200

        (after,) = _connections(client)
        assert (after["description"], after["is_active"]) == ("стало", True)
        assert after["id"] == before["id"]

    def test_failed_swap_rolls_everything_back_and_leaves_connections_active(self, client):
        """409 посреди применения откатывает и выключение подключений: ни одно не остаётся неактивным."""
        _, theirs = _device_with_ports(client, "SW-U-FAIL", ["g1", "g2"])
        ct = _connection_type(client)
        dev, own = _device_with_ports(client, "SRV-U-FAIL", ["eth0", "eth1"])
        assert (
            _sync(
                client,
                dev["id"],
                [
                    {"id": own["eth0"]["id"], "name": "eth0", "connection": _conn(theirs["g1"], ct)},
                    {"id": own["eth1"]["id"], "name": "eth1", "connection": _conn(theirs["g2"], ct)},
                ],
            ).status_code
            == 200
        )
        before = {(c["id"], c["source_interface_id"], c["destination_interface_id"], c["is_active"]) for c in _connections(client)}

        response = _sync(
            client,
            dev["id"],
            [
                {"id": own["eth0"]["id"], "name": "eth0", "connection": _conn(theirs["g2"], ct)},
                {"id": own["eth1"]["id"], "name": "eth1"},  # подключение eth1—g2 остаётся: порт g2 занять нельзя
            ],
        )

        assert response.status_code == 409, response.text
        assert {(c["id"], c["source_interface_id"], c["destination_interface_id"], c["is_active"]) for c in _connections(client)} == before


@pytest.mark.postgres_only  # на SQLite фикстуры делят одно соединение между потоками (StaticPool)
class TestIndexProtectsEvenWithoutTheLockOnPostgres:
    """Запись мимо validate_connection (а значит, и мимо блокировки портов) всё равно не создаст второе активное подключение: индекс держит и конкурентную вставку."""

    WAIT_SECONDS = 15

    def test_concurrent_insert_of_a_duplicate_waits_and_then_fails_on_the_index(self, world, db_session):
        factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
        first, second, observer = factory(), factory(), factory()
        a, b, c, _d = world.ports
        outcome: dict = {}
        try:
            _add(first, a, b, world.type_id)
            first.flush()  # вставлено, не зафиксировано

            def duplicate() -> None:
                try:
                    _add(second, a, c, world.type_id)
                    second.commit()
                    outcome["committed"] = True
                except IntegrityError as exc:
                    outcome["integrity"] = str(exc)
                except Exception as exc:  # noqa: BLE001
                    outcome["error"] = exc

            thread = threading.Thread(target=duplicate, daemon=True)
            thread.start()
            deadline = time.monotonic() + self.WAIT_SECONDS
            while time.monotonic() < deadline and thread.is_alive():
                if observer.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'")).scalar():
                    break
                time.sleep(0.05)
            assert thread.is_alive(), f"вторая вставка не дождалась первой: {outcome}"
            first.commit()
            thread.join(timeout=self.WAIT_SECONDS)

            assert not thread.is_alive()
            assert "committed" not in outcome and "error" not in outcome, outcome
            assert "uq_connections_source_active" in outcome["integrity"]
        finally:
            for session in (first, second, observer):
                session.rollback()
                session.close()
