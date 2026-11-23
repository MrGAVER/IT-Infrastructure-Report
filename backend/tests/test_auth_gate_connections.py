"""A-01: middleware доступа не должно держать соединение БД на всё время запроса.

Раньше при выключенной аутентификации (режим по умолчанию) `auth_gate_middleware` закрывал свою сессию
только после ответа обработчика: каждый API-запрос занимал два соединения из пула (middleware + Depends(get_db)),
а синхронные вызовы БД выполнялись прямо в цикле событий. Здесь проверяется, что к моменту работы обработчика
сессия middleware уже закрыта в любом режиме, а обращение к БД идёт не из потока цикла событий.
"""

from __future__ import annotations

import threading

import pytest

from test_auth import _auth_headers, _bootstrap_admin, _login


class _SessionCounter:
    """Обёртка над фабрикой сессий: считает открытые (ещё не закрытые) сессии и запоминает потоки, в которых их открывали."""

    def __init__(self, inner):
        self._inner = inner
        self.open = 0
        self.created = 0
        self.creation_threads: list[int] = []

    def __call__(self):
        session = self._inner()
        self.open += 1
        self.created += 1
        self.creation_threads.append(threading.get_ident())
        original_close = session.close
        state = {"closed": False}

        def close():
            if not state["closed"]:
                state["closed"] = True
                self.open -= 1
            return original_close()

        session.close = close
        return session


class _HandlerProbe:
    """Что видел обработчик в момент выполнения: сколько сессий middleware ещё открыто и в каком потоке крутится цикл событий."""

    def __init__(self):
        self.open_at_handler: list[int] = []
        self.loop_threads: list[int] = []


@pytest.fixture()
def probe(client, db_session, monkeypatch):
    from app import db as app_db
    from app import main as app_main
    from app.db import get_db

    counter = _SessionCounter(app_db.SessionLocal)
    monkeypatch.setattr(app_db, "SessionLocal", counter)
    observed = _HandlerProbe()

    async def _probing_get_db():
        # async-зависимость выполняется в потоке цикла событий — с ним сравниваем поток, где middleware ходит в БД.
        observed.loop_threads.append(threading.get_ident())
        observed.open_at_handler.append(counter.open)
        yield db_session

    app_main.app.dependency_overrides[get_db] = _probing_get_db
    yield client, counter, observed


def test_session_is_closed_before_handler_when_auth_is_disabled(probe):
    client, counter, observed = probe
    assert client.get("/api/v1/resources/manufacturers").status_code == 200
    assert counter.created >= 1
    assert observed.open_at_handler == [0], "соединение middleware не должно жить во время работы обработчика"
    assert counter.open == 0


def test_session_is_closed_before_handler_on_public_path_with_auth_enabled(probe):
    client, counter, observed = probe
    _bootstrap_admin(client)
    observed.open_at_handler.clear()
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin1234"})
    assert r.status_code == 200, r.text
    assert observed.open_at_handler and set(observed.open_at_handler) == {0}
    assert counter.open == 0


def test_session_is_closed_before_handler_with_valid_token(probe):
    client, counter, observed = probe
    _bootstrap_admin(client)
    token = _login(client, "admin", "Admin1234")
    observed.open_at_handler.clear()
    assert client.get("/api/v1/resources/manufacturers", headers=_auth_headers(token)).status_code == 200
    assert observed.open_at_handler == [0]
    assert counter.open == 0


def test_session_is_closed_after_rejected_request(probe):
    client, counter, observed = probe
    _bootstrap_admin(client)
    created_before = counter.created
    r = client.get("/api/v1/resources/manufacturers")  # без токена
    assert r.status_code == 401
    assert counter.created > created_before, "middleware должно было обратиться к БД"
    assert counter.open == 0, "отклонённый запрос не должен оставлять открытую сессию"


def test_gate_queries_run_outside_event_loop_thread(probe):
    client, counter, observed = probe
    assert client.get("/api/v1/resources/manufacturers").status_code == 200
    assert observed.loop_threads, "async-зависимость не вызывалась"
    loop_thread = observed.loop_threads[0]
    assert counter.creation_threads, "middleware не открывало сессию"
    assert loop_thread not in counter.creation_threads, "синхронная работа с БД не должна блокировать цикл событий"


class TestPoolOptions:
    """INFRA_REGISTRY_DB_POOL_SIZE / _MAX_OVERFLOW / _POOL_TIMEOUT: необязательные, опечатка — явная ошибка."""

    def test_unset_and_blank_values_mean_sqlalchemy_defaults(self, monkeypatch):
        from app.config import _optional_number_env

        monkeypatch.delenv("INFRA_REGISTRY_DB_POOL_SIZE", raising=False)
        assert _optional_number_env("INFRA_REGISTRY_DB_POOL_SIZE", int) is None
        monkeypatch.setenv("INFRA_REGISTRY_DB_POOL_SIZE", "  ")
        assert _optional_number_env("INFRA_REGISTRY_DB_POOL_SIZE", int) is None

    def test_valid_values_are_parsed(self, monkeypatch):
        from app.config import _optional_number_env

        monkeypatch.setenv("INFRA_REGISTRY_DB_POOL_SIZE", "20")
        monkeypatch.setenv("INFRA_REGISTRY_DB_POOL_TIMEOUT", "7.5")
        assert _optional_number_env("INFRA_REGISTRY_DB_POOL_SIZE", int) == 20
        assert _optional_number_env("INFRA_REGISTRY_DB_POOL_TIMEOUT", float) == 7.5

    @pytest.mark.parametrize("raw", ["abc", "-1", "1.5"])
    def test_invalid_values_raise_clear_error(self, monkeypatch, raw):
        from app.config import _optional_number_env

        monkeypatch.setenv("INFRA_REGISTRY_DB_POOL_SIZE", raw)
        with pytest.raises(ValueError, match="INFRA_REGISTRY_DB_POOL_SIZE"):
            _optional_number_env("INFRA_REGISTRY_DB_POOL_SIZE", int)
