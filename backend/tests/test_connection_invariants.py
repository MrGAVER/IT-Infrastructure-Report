"""
A-01 (код-ревью main @ b375f58), этап 1: инварианты подключений на уровне БД.

Правила «порт не соединяется сам с собой» и «порт участвует не более чем в одном активном подключении» проверял только код по схеме
«прочитал → проверил → записал». Теперь:

* CHECK `ck_connections_distinct_ports` — последний рубеж против подключения «порт сам с собой», даже если запись идёт мимо
  `validate_connection`;
* `validate_connection` и применение плана подключений формы устройства на PostgreSQL берут `SELECT ... FOR UPDATE` строк портов (по
  возрастанию id): параллельный запрос с тем же портом ждёт фиксации первого и честно получает 409, в какой бы роли (источник/назначение)
  порт ни выступал. На SQLite (один
  писатель) блокировка не нужна.

Группы: проверки на любой СУБД и сценарии с несколькими сессиями на PostgreSQL (маркер postgres_only; локально —
INFRA_REGISTRY_TEST_DATABASE_URL=postgresql+psycopg://...).
Запуск: pytest backend/tests/test_connection_invariants.py -v
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import Connection
from app.services import interface_connections, validation
from app.services.validation import lock_interfaces, validate_connection
from connection_support import make_world


@pytest.fixture()
def world(db_session):
    """Одно устройство с четырьмя портами и тип подключения; всё зафиксировано, чтобы его видели другие сессии."""
    return make_world(db_session)


def _data(source: str, destination: str, type_id: str) -> dict:
    return {"source_interface_id": source, "destination_interface_id": destination, "connection_type_id": type_id}


class TestCheckConstraint:
    def test_database_rejects_a_connection_of_a_port_to_itself(self, world, db_session):
        # Раньше БД принимала такую запись: проверка была только в validate_connection.
        db_session.add(Connection(**_data(world.ports[0], world.ports[0], world.type_id), is_active=True))
        with pytest.raises(IntegrityError) as caught:
            db_session.commit()
        assert "ck_connections_distinct_ports" in str(caught.value)
        db_session.rollback()

    def test_connection_between_two_different_ports_is_still_accepted(self, world, db_session):
        db_session.add(Connection(**_data(world.ports[0], world.ports[1], world.type_id), is_active=True))
        db_session.commit()

    def test_inactive_connection_of_a_port_to_itself_is_rejected_too(self, world, db_session):
        # Ограничение не зависит от is_active: «порт сам с собой» не имеет смысла и в архиве.
        db_session.add(Connection(**_data(world.ports[2], world.ports[2], world.type_id), is_active=False))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_validation_still_answers_422_with_a_clear_message(self, world, db_session):
        with pytest.raises(HTTPException) as caught:
            validate_connection(_data(world.ports[0], world.ports[0], world.type_id), db_session)
        assert caught.value.status_code == 422


class _FakeSession:
    """Сессия-заглушка: диалект и список выполненных запросов."""

    def __init__(self, dialect: str) -> None:
        self.dialect = dialect
        self.statements: list = []

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name=self.dialect))

    def execute(self, statement):
        self.statements.append(statement)


class TestLockInterfaces:
    def test_postgresql_locks_the_rows_in_ascending_id_order(self):
        session = _FakeSession("postgresql")
        lock_interfaces(session, ["p-3", "p-1", "p-3", "p-2", "", None])
        assert len(session.statements) == 1
        compiled = session.statements[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        sql = str(compiled)
        assert sql.rstrip().endswith("FOR UPDATE")
        assert "ORDER BY device_interfaces.id" in sql, "единый порядок захвата строк исключает взаимную блокировку двух запросов"
        for port_id in ("p-1", "p-2", "p-3"):
            assert f"'{port_id}'" in sql
        assert sql.count("'p-3'") == 1, "повторы и пустые значения отбрасываются"

    def test_many_ports_are_locked_in_ascending_chunks(self, monkeypatch):
        monkeypatch.setattr(validation, "_LOCK_CHUNK", 3)
        session = _FakeSession("postgresql")
        lock_interfaces(session, [f"id-{n:02d}" for n in reversed(range(7))])
        locked = [next(iter(statement.compile(dialect=postgresql.dialect()).params.values())) for statement in session.statements]
        assert locked == [["id-00", "id-01", "id-02"], ["id-03", "id-04", "id-05"], ["id-06"]], (
            "порции идут по возрастанию id — глобальный порядок тот же"
        )

    def test_is_a_no_op_on_sqlite_and_without_ports(self):
        sqlite_session = _FakeSession("sqlite")
        lock_interfaces(sqlite_session, ["p-1", "p-2"])
        assert sqlite_session.statements == [], "на SQLite запись и так сериализована — лишний запрос не нужен"
        postgres_session = _FakeSession("postgresql")
        lock_interfaces(postgres_session, [])
        lock_interfaces(postgres_session, [None, ""])
        assert postgres_session.statements == []

    @pytest.mark.sqlite_only  # на PostgreSQL блокировка выполняется по-настоящему
    def test_real_sqlite_session_executes_nothing(self, world, db_session, sql_log):
        lock_interfaces(db_session, world.ports)
        assert sql_log == []


class TestWhereTheLockIsTaken:
    @pytest.fixture()
    def locked(self, monkeypatch):
        calls: list[list[str]] = []
        monkeypatch.setattr(validation, "lock_interfaces", lambda session, ids: calls.append(sorted(ids)))
        return calls

    def test_validate_connection_locks_both_ports(self, world, db_session, locked):
        validate_connection(_data(world.ports[1], world.ports[0], world.type_id), db_session)
        assert locked == [sorted([world.ports[0], world.ports[1]])]

    @pytest.mark.parametrize(
        "data",
        [
            {"destination_interface_id": "x", "connection_type_id": "t"},
            {"source_interface_id": "x", "connection_type_id": "t"},
            {"source_interface_id": "missing", "destination_interface_id": "other", "connection_type_id": "t"},
        ],
        ids=["no-source", "no-destination", "unknown-port"],
    )
    def test_nothing_is_locked_for_requests_rejected_by_the_cheap_checks(self, db_session, locked, data):
        with pytest.raises(HTTPException):
            validate_connection(data, db_session)
        assert locked == []

    def test_nothing_is_locked_for_a_port_connected_to_itself_or_without_a_type(self, world, db_session, locked):
        with pytest.raises(HTTPException):
            validate_connection(_data(world.ports[0], world.ports[0], world.type_id), db_session)
        with pytest.raises(HTTPException):
            validate_connection({"source_interface_id": world.ports[0], "destination_interface_id": world.ports[1]}, db_session)
        assert locked == []

    def test_device_form_locks_all_its_ports_before_reading_their_connections(self, world, db_session, monkeypatch):
        """Форма устройства применяет несколько подключений за один запрос: все порты берутся ОДНИМ упорядоченным захватом до
        расчёта плана — иначе два запроса с пересекающимися портами, берущие их парами в разном порядке, взаимно заблокировали бы
        друг друга."""
        events: list = []
        monkeypatch.setattr(interface_connections, "lock_interfaces", lambda session, ids: events.append(("lock", sorted(ids))))
        real_connections_of = interface_connections.connections_of
        monkeypatch.setattr(
            interface_connections,
            "connections_of",
            lambda ids, session, **kw: events.append(("read", list(ids))) or real_connections_of(ids, session, **kw),
        )
        a, b, c, d = world.ifaces
        spec_ab = {"peer_interface_id": b.id, "connection_type_id": world.type_id}
        spec_cd = {"peer_row": 3, "connection_type_id": world.type_id}

        changed = interface_connections.sync_interface_connections([(d, None), (c, spec_cd), (a, spec_ab)], db_session, rows=[a, b, c, d])

        assert changed == 2  # отключение порта d удалять нечего; создаются два подключения: (c, d) и (a, b)
        assert events[0] == ("lock", sorted([a.id, b.id, c.id, d.id])), events
        assert all(kind == "read" for kind, _ in events[1:])


@pytest.mark.postgres_only  # на SQLite FOR UPDATE не рисуется, а фикстуры делят одно соединение между потоками (StaticPool)
class TestConcurrentCreationOnPostgres:
    WAIT_SECONDS = 15

    @pytest.fixture()
    def sessions(self, db_session):
        factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
        opened = []

        def make():
            session = factory()
            opened.append(session)
            return session

        yield make
        for session in opened:
            session.rollback()
            session.close()

    @staticmethod
    def _validate_in_thread(session, data: dict) -> tuple[threading.Thread, dict]:
        outcome: dict = {}

        def target() -> None:
            try:
                validate_connection(data, session)
                outcome["passed"] = True
            except HTTPException as exc:
                outcome["http"] = exc
            except Exception as exc:  # noqa: BLE001 — любая другая ошибка тоже провал сценария, но поток обязан завершиться
                outcome["error"] = exc

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        return thread, outcome

    def _wait_until_blocked(self, observer, thread: threading.Thread, outcome: dict) -> None:
        deadline = time.monotonic() + self.WAIT_SECONDS
        while time.monotonic() < deadline:
            waiting = observer.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'")
            ).scalar()
            if waiting:
                return
            if not thread.is_alive():
                raise AssertionError(
                    "проверка завершилась, не дождавшись порта, который занимает чужой незафиксированный запрос, — оба запроса "
                    f"записали бы подключение: {outcome}"
                )
            time.sleep(0.05)
        raise AssertionError("проверка не упёрлась в блокировку за отведённое время и не завершилась")

    @pytest.mark.parametrize(
        "second_pair",
        [
            pytest.param((0, 2), id="same-port-as-source-in-both"),
            pytest.param((2, 0), id="source-in-first-destination-in-second"),
            pytest.param((2, 1), id="same-port-as-destination-in-both"),
            pytest.param((1, 2), id="destination-in-first-source-in-second"),
        ],
    )
    def test_second_request_waits_for_the_first_and_then_answers_409(self, world, db_session, sessions, second_pair):
        # Первый запрос: порты 0 (источник) и 1 (назначение); подключение вставлено, но не зафиксировано. Второй использует порт 0
        # или 1 в любой роли.
        first, second, observer = sessions(), sessions(), sessions()
        first_data = _data(world.ports[0], world.ports[1], world.type_id)
        validate_connection(first_data, first)
        first.add(Connection(**first_data, is_active=True))
        first.flush()

        second_data = _data(world.ports[second_pair[0]], world.ports[second_pair[1]], world.type_id)
        thread, outcome = self._validate_in_thread(second, second_data)
        self._wait_until_blocked(observer, thread, outcome)
        first.commit()
        thread.join(timeout=self.WAIT_SECONDS)

        assert not thread.is_alive(), "вторая проверка зависла после фиксации первого запроса"
        assert "error" not in outcome, outcome.get("error")
        assert "passed" not in outcome, "второй запрос не увидел подключение первого и дал бы порту второе активное подключение"
        assert outcome["http"].status_code == 409

    def test_requests_on_different_ports_do_not_wait_for_each_other(self, world, sessions):
        first, second = sessions(), sessions()
        validate_connection(_data(world.ports[0], world.ports[1], world.type_id), first)  # держит порты 0 и 1 до конца транзакции
        thread, outcome = self._validate_in_thread(second, _data(world.ports[2], world.ports[3], world.type_id))
        thread.join(timeout=self.WAIT_SECONDS)
        assert not thread.is_alive(), "запрос про чужие порты ждёт блокировку, которая его не касается"
        assert outcome.get("passed") is True, outcome

    def test_opposite_port_order_does_not_deadlock(self, world, sessions):
        """Два запроса берут одну и ту же пару портов в разном порядке: без единого порядка захвата они взаимно заблокировались бы."""
        first, second = sessions(), sessions()
        results: dict = {}

        def run(name: str, session, data: dict) -> None:
            try:
                validate_connection(data, session)
                session.commit()
                results[name] = "passed"
            except HTTPException as exc:
                session.rollback()
                results[name] = exc.status_code
            except Exception as exc:  # noqa: BLE001 — deadlock detected и подобное
                session.rollback()
                results[name] = repr(exc)

        threads = [
            threading.Thread(target=run, args=("ab", first, _data(world.ports[0], world.ports[1], world.type_id)), daemon=True),
            threading.Thread(target=run, args=("ba", second, _data(world.ports[1], world.ports[0], world.type_id)), daemon=True),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=self.WAIT_SECONDS)
        assert not any(thread.is_alive() for thread in threads), results
        assert set(results.values()) == {"passed"}, (
            "обе проверки видят порты свободными: ничего не вставлялось, — и ни одна не должна упасть взаимной блокировкой"
        )
