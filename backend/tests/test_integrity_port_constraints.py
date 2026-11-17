"""
Нарушение ограничений портов подключения на уровне БД превращается в понятный 409, а не в безликий INTEGRITY_ERROR.

Обычно запрос, который нарушил бы ограничение, останавливает validate_connection (422/409 с объяснением). До БД дело доходит
в гонке двух запросов или при записи в обход проверки, и тогда `services/integrity.integrity_error_response` должен узнать
нарушенное ограничение. Тексты ошибок разные: PostgreSQL называет ограничение
(`violates unique constraint "uq_connections_source_active"`), а SQLite для частичного индекса пишет только колонку
(`UNIQUE constraint failed: connections.source_interface_id`), поэтому распознавание учитывает оба вида. Ответ для клиента
по-прежнему не содержит ни имён таблиц, колонок, ни самих ограничений.

Запуск: pytest backend/tests/test_integrity_port_constraints.py -v   (и с INFRA_REGISTRY_TEST_DATABASE_URL — на PostgreSQL)
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.constants import ErrorCode
from app.models import Connection
from app.services.integrity import integrity_error_response
from connection_support import make_world

API = "/api/v1/connections"
LEAKED_WORDS = ("uq_connections", "ck_connections", "connections.", "source_interface_id", "destination_interface_id", "constraint")


@pytest.fixture
def world(db_session):
    return make_world(db_session)


def _violation(session, world, source: str, destination: str, *, first: tuple[str, str] | None = None) -> IntegrityError:
    """Записывает подключение в обход validate_connection и возвращает ошибку БД. first — подключение, которое уже стоит в БД."""
    if first:
        session.add(
            Connection(
                source_interface_id=first[0],
                destination_interface_id=first[1],
                connection_type_id=world.type_id,
                is_active=True,
            )
        )
        session.commit()
    session.add(
        Connection(
            source_interface_id=source,
            destination_interface_id=destination,
            connection_type_id=world.type_id,
            is_active=True,
        )
    )
    with pytest.raises(IntegrityError) as caught:
        session.commit()
    session.rollback()
    return caught.value


def _error(exc: IntegrityError) -> HTTPException:
    return integrity_error_response("connections", exc)


def _assert_no_internals(error: HTTPException) -> None:
    text = str(error.detail["message"]).lower()
    assert not any(word in text for word in LEAKED_WORDS), text


class TestEachConstraintHasItsOwnAnswer:
    def test_a_port_that_is_already_the_source_of_an_active_connection(self, world, db_session):
        a, b, c, _d = world.ports

        error = _error(_violation(db_session, world, a, c, first=(a, b)))

        assert error.status_code == 409
        assert error.detail["code"] == ErrorCode.PORT_ALREADY_CONNECTED
        assert "уже участвует в другом активном подключении" in error.detail["message"]
        _assert_no_internals(error)

    def test_a_port_that_is_already_the_destination_of_an_active_connection(self, world, db_session):
        a, b, c, _d = world.ports

        error = _error(_violation(db_session, world, b, c, first=(a, c)))

        assert error.status_code == 409
        assert error.detail["code"] == ErrorCode.PORT_ALREADY_CONNECTED
        _assert_no_internals(error)

    def test_a_port_connected_to_itself(self, world, db_session):
        a, *_rest = world.ports

        error = _error(_violation(db_session, world, a, a))

        assert error.status_code == 409
        assert error.detail["code"] == ErrorCode.CONNECTION_SAME_PORT
        assert "к самому себе" in error.detail["message"]
        _assert_no_internals(error)

    def test_other_integrity_errors_keep_the_generic_answer(self, world, db_session):
        class Other(Exception):
            pass

        exc = IntegrityError("INSERT INTO devices ...", {}, Other("UNIQUE constraint failed: physical_devices.serial_number"))

        assert integrity_error_response("devices", exc).detail["code"] == ErrorCode.INTEGRITY_ERROR

    def test_the_rack_slot_answer_is_not_affected(self):
        exc = IntegrityError("INSERT ...", {}, Exception('duplicate key value violates unique constraint "uq_device_rack_slot"'))

        assert integrity_error_response("devices", exc).detail["code"] == ErrorCode.RACK_POSITION_OCCUPIED


class TestThroughTheHttpLayer:
    def test_a_race_that_passes_validation_gets_the_clear_409(self, client, monkeypatch):
        """Два запроса прошли проверку «порт свободен»; второй упёрся в уникальный индекс.
        Проверку обходим — так выглядит этот исход для клиента."""
        from app.services import interface_connections
        from test_interface_connections import _conn, _connection_type, _device_with_ports, _sync

        _, theirs = _device_with_ports(client, "SW-RACE", ["g1"])
        connection_type = _connection_type(client)
        first, first_ports = _device_with_ports(client, "SRV-RACE-1", ["eth0"])
        second, second_ports = _device_with_ports(client, "SRV-RACE-2", ["eth0"])

        def connect(device, ports):
            port = {"id": ports["eth0"]["id"], "name": "eth0", "connection": _conn(theirs["g1"], connection_type)}
            return _sync(client, device["id"], [port])

        assert connect(first, first_ports).status_code == 200
        monkeypatch.setattr(interface_connections, "validate_connection", lambda *args, **kwargs: None)

        response = connect(second, second_ports)

        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail["code"] == ErrorCode.PORT_ALREADY_CONNECTED, detail
        assert "Обновите данные и повторите" in detail["message"]
