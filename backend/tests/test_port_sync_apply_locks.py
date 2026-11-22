"""Применение плана согласования портов блокирует строки портов (SELECT ... FOR UPDATE).

План считается из состояния портов, а применяется позже: без блокировки правка порта другим пользователем между
расчётом и commit() молча перезаписывалась бы (на PostgreSQL, READ COMMITTED). Хеш плана защищает от устаревшего
ПРЕДПРОСМОТРА, но не от гонки внутри самого применения. Блокировка берётся до расчёта, поэтому план строится уже
из актуальных данных, а не из снимка, который чужая транзакция успеет изменить.

Две группы тестов: проверки, идущие на любой СУБД (какие порты и когда блокируются), и сценарий с двумя сессиями
на PostgreSQL (на SQLite FOR UPDATE не рисуется — там запись и так сериализована блокировкой файла).
Запуск: pytest backend/tests/test_port_sync_apply_locks.py -v
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import sessionmaker

from app.models import InterfaceVLAN
from app.services import port_sync_reconcile
from test_port_sync_reconcile import APPLY, World


@pytest.fixture()
def world(client, db_session) -> World:
    return World(client, db_session)


def _mismatching_pair(world: World, tag: str) -> tuple[str, str, str]:
    """Подключение «пустой trunk — trunk с VLAN 10, 20»: единственное расхождение, которое план исправляет."""
    (a,) = world.device(f"LK-A-{tag}", ["Gi0/1"], allowed=(10, 20, 30))
    (b,) = world.device(f"LK-B-{tag}", ["Gi0/1"], allowed=(10, 20, 30))
    world.configure(b, mode="trunk", vlans=(10, 20))
    return a, b, world.connect(a, b)


class _CallLog:
    """Пишет порядок вызовов блокировки и загрузки портов, не меняя их поведения."""

    def __init__(self, monkeypatch) -> None:
        self.events: list[str] = []
        self.locked: list[set[str]] = []
        real_lock, real_load = port_sync_reconcile._lock_interfaces, port_sync_reconcile._load_ports

        def lock(session, interface_ids):
            self.events.append("lock")
            self.locked.append(set(interface_ids))
            return real_lock(session, interface_ids)

        def load(session, interface_ids):
            self.events.append("load")
            return real_load(session, interface_ids)

        monkeypatch.setattr(port_sync_reconcile, "_lock_interfaces", lock)
        monkeypatch.setattr(port_sync_reconcile, "_load_ports", load)


class TestWhatIsLocked:
    def test_apply_locks_exactly_the_ports_of_the_selected_connections_before_computing(self, world, monkeypatch):
        a1, b1, c1 = _mismatching_pair(world, "1")
        _mismatching_pair(world, "2")  # чужое подключение вне списка: его порты блокироваться не должны
        plan = world.preview(connection_ids=[c1])
        log = _CallLog(monkeypatch)

        response = world.client.post(APPLY, json={"connection_ids": [c1], "plan_hash": plan["plan_hash"], "confirm": True})

        assert response.status_code == 200, response.text
        assert log.locked == [{a1, b1}]
        assert log.events == ["lock", "load"], (
            "блокировка должна предшествовать загрузке портов — иначе план строится из устаревшего снимка"
        )

    def test_preview_takes_no_locks(self, world, monkeypatch):
        _mismatching_pair(world, "P")
        log = _CallLog(monkeypatch)

        world.preview()

        assert log.locked == [], "предпросмотр ничего не записывает и не должен блокировать чужие правки портов"

    def test_apply_without_confirmation_locks_nothing(self, world, monkeypatch):
        _mismatching_pair(world, "C")
        log = _CallLog(monkeypatch)

        assert world.client.post(APPLY, json={"plan_hash": "x"}).status_code == 422

        assert log.locked == []


class TestLockStatement:
    IDS = ["iface-1", "iface-2"]

    def test_renders_for_update_in_a_stable_order_on_postgresql(self):
        sql = str(port_sync_reconcile._lock_statement(self.IDS).compile(dialect=postgresql.dialect()))
        assert sql.rstrip().endswith("FOR UPDATE")
        assert "ORDER BY device_interfaces.id" in sql, "единый порядок захвата строк исключает взаимную блокировку двух применений"

    def test_is_a_safe_no_op_on_sqlite(self):
        sql = str(port_sync_reconcile._lock_statement(self.IDS).compile(dialect=sqlite.dialect()))
        assert "FOR UPDATE" not in sql

    def test_refreshes_rows_already_loaded_into_the_session(self):
        assert port_sync_reconcile._lock_statement(self.IDS).get_execution_options().get("populate_existing") is True

    def test_many_ports_are_locked_in_chunks(self, db_session, monkeypatch):
        statements: list[int] = []
        real = port_sync_reconcile._lock_statement
        monkeypatch.setattr(port_sync_reconcile, "_lock_statement", lambda ids: statements.append(len(ids)) or real(ids))

        port_sync_reconcile._lock_interfaces(db_session, [f"id-{n:04d}" for n in range(port_sync_reconcile._CHUNK * 2 + 5)])

        assert statements == [port_sync_reconcile._CHUNK, port_sync_reconcile._CHUNK, 5]

    def test_duplicates_and_empty_input_are_harmless(self, db_session):
        port_sync_reconcile._lock_interfaces(db_session, [])
        port_sync_reconcile._lock_interfaces(db_session, ["missing", "missing"])


@pytest.mark.postgres_only  # на SQLite фикстуры делят одно соединение между потоками (StaticPool), а FOR UPDATE не рисуется
class TestConcurrentEditOnPostgres:
    LOCK_WAIT_SECONDS = 15

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
    def _wait_until_apply_waits_for_a_lock(observer, thread: threading.Thread, outcome: dict) -> None:
        """Ждёт, пока применение упрётся в чужую блокировку. Если оно успело завершиться, не дожидаясь, — это и есть
        ошибка: порт, который правит другой пользователь, не заблокирован, и его правка будет перезаписана."""
        deadline = time.monotonic() + TestConcurrentEditOnPostgres.LOCK_WAIT_SECONDS
        while time.monotonic() < deadline:
            waiting = observer.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'")
            ).scalar()
            if waiting:
                return
            if not thread.is_alive():
                raise AssertionError(
                    "применение завершилось, не дождавшись порта, который правит другой пользователь, — чужая правка "
                    f"перезаписана: {outcome}"
                )
            time.sleep(0.05)
        raise AssertionError("применение не упёрлось в блокировку за отведённое время и не завершилось")

    @staticmethod
    def _run_apply_in_thread(session, body: dict) -> tuple[threading.Thread, dict]:
        outcome: dict = {}

        def target() -> None:
            try:
                outcome["result"] = port_sync_reconcile.apply_reconcile(body, session)
            except HTTPException as exc:
                outcome["http"] = exc
            except Exception as exc:  # noqa: BLE001 — любая другая ошибка тоже провал сценария, но поток обязан завершиться
                outcome["error"] = exc

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        return thread, outcome

    def test_edit_committed_during_apply_is_not_overwritten_and_the_plan_is_recomputed(self, world, db_session, sessions):
        _a1, _b1, _c1 = _mismatching_pair(world, "X1")
        a2, _b2, _c2 = _mismatching_pair(world, "X2")
        plan = world.preview()
        assert plan["summary"]["applicable"] == 2
        db_session.rollback()  # предпросмотр оставил открытую транзакцию чтения

        editor, applier, observer = sessions(), sessions(), sessions()
        # Другой пользователь правит порт a2 и ещё не сохранил: блокирует строку порта и выравнивает VLAN с соседом,
        # после чего подключение перестаёт быть расхождением и из плана выпадает.
        editor.execute(text("UPDATE device_interfaces SET sort_order = sort_order WHERE id = :id"), {"id": a2})
        editor.add_all(InterfaceVLAN(interface_id=a2, vlan_id=world.vlan(number).id, mode="trunk") for number in (10, 20))
        editor.flush()

        thread, outcome = self._run_apply_in_thread(applier, {"plan_hash": plan["plan_hash"], "confirm": True})
        self._wait_until_apply_waits_for_a_lock(observer, thread, outcome)
        editor.commit()
        thread.join(timeout=self.LOCK_WAIT_SECONDS)

        assert not thread.is_alive(), "применение зависло после сохранения чужой правки"
        assert "error" not in outcome, outcome.get("error")
        assert "http" in outcome and outcome["http"].status_code == 409, (
            f"применение должно пересчитать план и отклонить устаревший хеш, а получило {outcome}"
        )
        assert world.port(a2)["vlans"] == [10, 20], "правка другого пользователя сохранилась"

    def test_ports_outside_the_plan_are_not_blocked(self, world, db_session, sessions):
        _a1, _b1, c1 = _mismatching_pair(world, "Y1")
        a2, _b2, _c2 = _mismatching_pair(world, "Y2")
        plan = world.preview(connection_ids=[c1])
        db_session.rollback()

        editor, applier = sessions(), sessions()
        editor.execute(
            text("UPDATE device_interfaces SET sort_order = sort_order WHERE id = :id"), {"id": a2}
        )  # держит порт чужого подключения

        thread, outcome = self._run_apply_in_thread(applier, {"connection_ids": [c1], "plan_hash": plan["plan_hash"], "confirm": True})
        thread.join(timeout=self.LOCK_WAIT_SECONDS)

        assert not thread.is_alive(), "применение ждёт порт, которого нет в его плане"
        assert outcome.get("result", {}).get("applied") == {"ports": 1, "connections": 1}, outcome
        editor.rollback()

    def test_unchanged_ports_apply_normally_after_a_concurrent_lock_is_released(self, world, db_session, sessions):
        a1, _b1, _c1 = _mismatching_pair(world, "Z1")
        plan = world.preview()
        db_session.rollback()

        editor, applier, observer = sessions(), sessions(), sessions()
        editor.execute(
            text("UPDATE device_interfaces SET sort_order = sort_order WHERE id = :id"), {"id": a1}
        )  # правка без смысловых изменений

        thread, outcome = self._run_apply_in_thread(applier, {"plan_hash": plan["plan_hash"], "confirm": True})
        self._wait_until_apply_waits_for_a_lock(observer, thread, outcome)
        editor.commit()
        thread.join(timeout=self.LOCK_WAIT_SECONDS)

        assert not thread.is_alive()
        assert outcome.get("result", {}).get("applied") == {"ports": 1, "connections": 1}, outcome
        assert world.port(a1)["vlans"] == [10, 20]
